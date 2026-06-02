import json
import os
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

from config import BASE_DIR, casefile, modlogs_file


MODLOGS_DB_FILE = Path(os.getenv("MODLOGS_DB_FILE", BASE_DIR / "modlogs.sqlite3"))
_DB_LOCK = threading.RLock()
INFRACTION_ACTION_PREFIX = "Infraction:"


def _connect() -> sqlite3.Connection:
    connection = sqlite3.connect(MODLOGS_DB_FILE)
    connection.row_factory = sqlite3.Row
    return connection


def _get_meta(connection: sqlite3.Connection, key: str, default: str | None = None) -> str | None:
    row = connection.execute("SELECT value FROM modlog_meta WHERE key = ?", (key,)).fetchone()
    if row is None:
        return default
    return row["value"]


def _set_meta(connection: sqlite3.Connection, key: str, value: Any) -> None:
    connection.execute(
        """
        INSERT INTO modlog_meta (key, value)
        VALUES (?, ?)
        ON CONFLICT(key) DO UPDATE SET value = excluded.value
        """,
        (key, str(value)),
    )


def _read_legacy_casefile() -> int:
    try:
        with open(casefile, "r", encoding="utf-8") as file:
            return int(file.read().strip() or 0)
    except (FileNotFoundError, ValueError, OSError):
        return 0


def _load_legacy_modlogs() -> list[dict[str, Any]]:
    try:
        with open(modlogs_file, "r", encoding="utf-8") as file:
            data = json.load(file)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return []
    return data if isinstance(data, list) else []


def _migrate_legacy_modlogs(connection: sqlite3.Connection) -> None:
    if _get_meta(connection, "legacy_modlogs_migrated"):
        return

    for entry in _load_legacy_modlogs():
        try:
            connection.execute(
                """
                INSERT OR IGNORE INTO modlogs (
                    user_id,
                    action,
                    reason,
                    moderator_id,
                    case_id,
                    timestamp,
                    source
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    int(entry["user_id"]),
                    str(entry["action"]).strip(),
                    str(entry.get("reason", "")).strip(),
                    int(entry["moderator_id"]),
                    int(entry["case_id"]),
                    int(entry.get("timestamp") or time.time()),
                    "legacy-json",
                ),
            )
        except (KeyError, TypeError, ValueError):
            continue

    _set_meta(connection, "legacy_modlogs_migrated", int(time.time()))


def _repair_case_ids_polluted_by_infractions(connection: sqlite3.Connection) -> None:
    if _get_meta(connection, "case_id_infraction_repair_v1"):
        return

    infraction_row = connection.execute(
        """
        SELECT MIN(case_id) AS first_infraction_case_id
        FROM modlogs
        WHERE action LIKE ?
        """,
        (f"{INFRACTION_ACTION_PREFIX}%",),
    ).fetchone()
    first_infraction_case_id = int(infraction_row["first_infraction_case_id"] or 0) if infraction_row else 0
    if first_infraction_case_id <= 0:
        _set_meta(connection, "case_id_infraction_repair_v1", int(time.time()))
        return

    previous_row = connection.execute(
        """
        SELECT COALESCE(MAX(case_id), 0) AS max_case_id
        FROM modlogs
        WHERE action NOT LIKE ?
          AND case_id < ?
        """,
        (f"{INFRACTION_ACTION_PREFIX}%", first_infraction_case_id),
    ).fetchone()
    next_case_id = int(previous_row["max_case_id"] or 0) if previous_row else 0

    polluted_rows = connection.execute(
        """
        SELECT id
        FROM modlogs
        WHERE action NOT LIKE ?
          AND case_id >= ?
        ORDER BY timestamp ASC, id ASC
        """,
        (f"{INFRACTION_ACTION_PREFIX}%", first_infraction_case_id),
    ).fetchall()

    for row in polluted_rows:
        next_case_id += 1
        connection.execute(
            "UPDATE modlogs SET case_id = ? WHERE id = ?",
            (next_case_id, int(row["id"])),
        )

    _set_meta(connection, "case_id_infraction_repair_v1", int(time.time()))


def _seed_next_case(connection: sqlite3.Connection) -> None:
    current_value = int(_get_meta(connection, "next_case_id", "0") or 0)
    max_case_row = connection.execute(
        """
        SELECT COALESCE(MAX(case_id), 0) AS max_case
        FROM modlogs
        WHERE action NOT LIKE ?
        """,
        (f"{INFRACTION_ACTION_PREFIX}%",),
    ).fetchone()
    max_case_id = int(max_case_row["max_case"]) if max_case_row else 0
    legacy_case_id = _read_legacy_casefile()
    target_value = max(max_case_id, legacy_case_id)
    if current_value < target_value:
        _set_meta(connection, "next_case_id", target_value)
    elif current_value > target_value and current_value - target_value > 1000000:
        _set_meta(connection, "next_case_id", target_value)


def _initialize_database() -> None:
    with _DB_LOCK:
        connection = _connect()
        try:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS modlogs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    action TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    moderator_id INTEGER NOT NULL,
                    case_id INTEGER NOT NULL UNIQUE,
                    timestamp INTEGER NOT NULL,
                    source TEXT NOT NULL DEFAULT 'native',
                    source_guild_id INTEGER,
                    source_channel_id INTEGER,
                    source_message_id INTEGER UNIQUE
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS modlog_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
                """
            )
            _migrate_legacy_modlogs(connection)
            _repair_case_ids_polluted_by_infractions(connection)
            _seed_next_case(connection)
            connection.commit()
        finally:
            connection.close()


def get_next_case() -> int:
    _initialize_database()
    with _DB_LOCK:
        connection = _connect()
        try:
            current_value = int(_get_meta(connection, "next_case_id", "0") or 0)
            next_case_id = current_value + 1
            _set_meta(connection, "next_case_id", next_case_id)
            connection.commit()
            return next_case_id
        finally:
            connection.close()


def save_modlog(
    user_id: int,
    action: str,
    reason: str,
    moderator_id: int,
    case_id: int,
    *,
    timestamp: int | None = None,
    source: str = "native",
    source_guild_id: int | None = None,
    source_channel_id: int | None = None,
    source_message_id: int | None = None,
    skip_duplicates: bool = False,
) -> bool:
    _initialize_database()
    timestamp = int(timestamp or time.time())
    query = """
        INSERT INTO modlogs (
            user_id,
            action,
            reason,
            moderator_id,
            case_id,
            timestamp,
            source,
            source_guild_id,
            source_channel_id,
            source_message_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """
    if skip_duplicates:
        query = query.replace("INSERT INTO", "INSERT OR IGNORE INTO", 1)

    with _DB_LOCK:
        connection = _connect()
        try:
            cursor = connection.execute(
                query,
                (
                    int(user_id),
                    str(action).strip(),
                    str(reason).strip(),
                    int(moderator_id),
                    int(case_id),
                    timestamp,
                    source,
                    int(source_guild_id) if source_guild_id is not None else None,
                    int(source_channel_id) if source_channel_id is not None else None,
                    int(source_message_id) if source_message_id is not None else None,
                ),
            )
            _seed_next_case(connection)
            connection.commit()
            return cursor.rowcount > 0
        finally:
            connection.close()


def get_modlogs_for_user(user_id: int) -> list[dict[str, Any]]:
    _initialize_database()
    with _DB_LOCK:
        connection = _connect()
        try:
            rows = connection.execute(
                """
                SELECT user_id, action, reason, moderator_id, case_id, timestamp
                FROM modlogs
                WHERE user_id = ?
                  AND action NOT LIKE ?
                ORDER BY case_id DESC, timestamp DESC
                """,
                (int(user_id), f"{INFRACTION_ACTION_PREFIX}%"),
            ).fetchall()
            return [dict(row) for row in rows]
        finally:
            connection.close()


def count_modlogs() -> int:
    _initialize_database()
    with _DB_LOCK:
        connection = _connect()
        try:
            row = connection.execute(
                "SELECT COUNT(*) AS count FROM modlogs WHERE action NOT LIKE ?",
                (f"{INFRACTION_ACTION_PREFIX}%",),
            ).fetchone()
            return int(row["count"]) if row else 0
        finally:
            connection.close()


def clear_user_modlogs(user_id: int) -> None:
    _initialize_database()
    with _DB_LOCK:
        connection = _connect()
        try:
            connection.execute(
                "DELETE FROM modlogs WHERE user_id = ? AND action NOT LIKE ?",
                (int(user_id), f"{INFRACTION_ACTION_PREFIX}%"),
            )
            connection.commit()
        finally:
            connection.close()


def clear_all_modlogs() -> None:
    _initialize_database()
    with _DB_LOCK:
        connection = _connect()
        try:
            connection.execute(
                "DELETE FROM modlogs WHERE action NOT LIKE ?",
                (f"{INFRACTION_ACTION_PREFIX}%",),
            )
            connection.commit()
        finally:
            connection.close()
