import json
import os
import re
import sqlite3
import uuid
from datetime import datetime
from typing import Any


THEMES_DB_FILE = os.getenv("DASHBOARD_THEMES_DB", "dashboard_themes.sqlite3")

THEME_COLOR_KEYS = [
    "background",
    "backgroundSoft",
    "panel",
    "panelStrong",
    "field",
    "foreground",
    "muted",
    "mutedStrong",
    "primary",
    "primaryStrong",
    "primaryInk",
    "secondary",
    "highlight",
    "destructive",
]

DEFAULT_THEME_AUTHOR = "CSRP Utilities"

SEED_THEMES = [
    {
        "id": "csrp-default",
        "name": "CSRP Default",
        "description": "A clean emerald control panel for day-to-day staff work.",
        "author": DEFAULT_THEME_AUTHOR,
        "tags": ["default", "staff", "green"],
        "downloads": 0,
        "updated_at": "2026-05-10T00:00:00",
        "rating": 4.8,
        "colors": {
            "background": "#090a0a",
            "backgroundSoft": "#0f1010",
            "panel": "#141514",
            "panelStrong": "#191b19",
            "field": "#0d0e0e",
            "foreground": "#f7f5ef",
            "muted": "#a5aaa4",
            "mutedStrong": "#c8cdc6",
            "primary": "#57d69b",
            "primaryStrong": "#32b77d",
            "primaryInk": "#06120d",
            "secondary": "#9b8cff",
            "highlight": "#f4bd5e",
            "destructive": "#ef6868",
        },
    },
    {
        "id": "midnight-theme",
        "name": "Midnight Theme",
        "description": "Deep black surfaces with vivid violet actions and soft text.",
        "author": DEFAULT_THEME_AUTHOR,
        "tags": ["midnight", "purple", "high contrast"],
        "downloads": 0,
        "updated_at": "2024-12-23T00:00:00",
        "rating": 4.1,
        "colors": {
            "background": "#050008",
            "backgroundSoft": "#08000f",
            "panel": "#0d0314",
            "panelStrong": "#160326",
            "field": "#07000c",
            "foreground": "#f7efff",
            "muted": "#9f7abc",
            "mutedStrong": "#c9a9e6",
            "primary": "#8427f6",
            "primaryStrong": "#5f18b7",
            "primaryInk": "#080010",
            "secondary": "#4b1389",
            "highlight": "#f0c85a",
            "destructive": "#d73562",
        },
    },
    {
        "id": "discord-dark-mode",
        "name": "Discord Dark Mode",
        "description": "Familiar graphite panels with bright blurple accents.",
        "author": DEFAULT_THEME_AUTHOR,
        "tags": ["discord", "dark mode", "blue"],
        "downloads": 0,
        "updated_at": "2025-01-20T00:00:00",
        "rating": 4.1,
        "colors": {
            "background": "#1e1f22",
            "backgroundSoft": "#25262b",
            "panel": "#2b2d31",
            "panelStrong": "#313338",
            "field": "#1e1f22",
            "foreground": "#f2f3f5",
            "muted": "#b5bac1",
            "mutedStrong": "#dbdee1",
            "primary": "#5865f2",
            "primaryStrong": "#4752c4",
            "primaryInk": "#ffffff",
            "secondary": "#3f4147",
            "highlight": "#fee75c",
            "destructive": "#ed4245",
        },
    },
    {
        "id": "crimson-moon",
        "name": "Crimson Moon",
        "description": "A red command-room theme with warm contrast.",
        "author": DEFAULT_THEME_AUTHOR,
        "tags": ["discord", "crimson", "red"],
        "downloads": 0,
        "updated_at": "2025-01-07T00:00:00",
        "rating": 5,
        "colors": {
            "background": "#080101",
            "backgroundSoft": "#150202",
            "panel": "#240505",
            "panelStrong": "#430707",
            "field": "#120202",
            "foreground": "#fff5f2",
            "muted": "#d5aaa4",
            "mutedStrong": "#f1c9c2",
            "primary": "#c23b35",
            "primaryStrong": "#7e120f",
            "primaryInk": "#fff8f5",
            "secondary": "#3f3f3f",
            "highlight": "#ffb55f",
            "destructive": "#ff1d32",
        },
    },
    {
        "id": "civic-blue",
        "name": "Civic Blue",
        "description": "Calm navy, bright cyan, and tidy operational surfaces.",
        "author": DEFAULT_THEME_AUTHOR,
        "tags": ["blue", "operations", "clean"],
        "downloads": 0,
        "updated_at": "2026-04-18T00:00:00",
        "rating": 4.7,
        "colors": {
            "background": "#061016",
            "backgroundSoft": "#0b1821",
            "panel": "#10212b",
            "panelStrong": "#142b38",
            "field": "#08141c",
            "foreground": "#eef9ff",
            "muted": "#95afbc",
            "mutedStrong": "#bad2dc",
            "primary": "#34c6e5",
            "primaryStrong": "#1597b5",
            "primaryInk": "#031115",
            "secondary": "#86b7ff",
            "highlight": "#f3cf63",
            "destructive": "#ff6c7c",
        },
    },
    {
        "id": "ember-terminal",
        "name": "Ember Terminal",
        "description": "Dark charcoal, amber highlights, and strong danger states.",
        "author": DEFAULT_THEME_AUTHOR,
        "tags": ["terminal", "amber", "contrast"],
        "downloads": 0,
        "updated_at": "2026-02-14T00:00:00",
        "rating": 4.5,
        "colors": {
            "background": "#0d0c0a",
            "backgroundSoft": "#15120e",
            "panel": "#1d1812",
            "panelStrong": "#272016",
            "field": "#100d0a",
            "foreground": "#fff7e8",
            "muted": "#b9a98e",
            "mutedStrong": "#e2cfaa",
            "primary": "#f2a93b",
            "primaryStrong": "#c2731d",
            "primaryInk": "#180d02",
            "secondary": "#55c6a1",
            "highlight": "#ffe06e",
            "destructive": "#f15f4c",
        },
    },
]


def _connect():
    connection = sqlite3.connect(THEMES_DB_FILE)
    connection.row_factory = sqlite3.Row
    return connection


def _utc_now():
    return datetime.utcnow().replace(microsecond=0).isoformat()


def _format_date(value: str):
    try:
        parsed = datetime.fromisoformat(value)
        return f"{parsed.month}/{parsed.day}/{parsed.year}"
    except (TypeError, ValueError):
        return value


def _refresh_download_counts(connection: sqlite3.Connection, theme_id: str | None = None):
    statement = """
        UPDATE themes
        SET downloads = (
            SELECT COUNT(*)
            FROM theme_installs
            WHERE theme_installs.theme_id = themes.id
                AND (themes.author_id IS NULL OR theme_installs.user_id != themes.author_id)
        )
    """
    if theme_id is None:
        connection.execute(statement)
    else:
        connection.execute(f"{statement} WHERE id = ?", (theme_id,))


def _sync_seed_theme_metadata(connection: sqlite3.Connection):
    connection.executemany(
        "UPDATE themes SET author_id = NULL, author_name = ? WHERE id = ?",
        [(DEFAULT_THEME_AUTHOR, theme["id"]) for theme in SEED_THEMES],
    )
    _refresh_download_counts(connection)


def init_theme_store():
    with _connect() as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS themes (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                description TEXT NOT NULL,
                author_id TEXT,
                author_name TEXT NOT NULL,
                tags_json TEXT NOT NULL,
                colors_json TEXT NOT NULL,
                downloads INTEGER NOT NULL DEFAULT 0,
                rating REAL NOT NULL DEFAULT 5,
                is_public INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS theme_installs (
                user_id TEXT NOT NULL,
                theme_id TEXT NOT NULL,
                installed_at TEXT NOT NULL,
                PRIMARY KEY (user_id, theme_id),
                FOREIGN KEY (theme_id) REFERENCES themes(id) ON DELETE CASCADE
            )
            """
        )
        connection.execute("CREATE INDEX IF NOT EXISTS idx_themes_public ON themes (is_public, updated_at)")
        connection.execute("CREATE INDEX IF NOT EXISTS idx_themes_author ON themes (author_id)")
        for theme in SEED_THEMES:
            connection.execute(
                """
                INSERT OR IGNORE INTO themes (
                    id,
                    name,
                    description,
                    author_id,
                    author_name,
                    tags_json,
                    colors_json,
                    downloads,
                    rating,
                    is_public,
                    created_at,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
                """,
                (
                    theme["id"],
                    theme["name"],
                    theme["description"],
                    None,
                    theme["author"],
                    json.dumps(theme["tags"]),
                    json.dumps(theme["colors"]),
                    int(theme["downloads"]),
                    float(theme["rating"]),
                    theme["updated_at"],
                    theme["updated_at"],
                ),
            )
        _sync_seed_theme_metadata(connection)
        connection.commit()


def _theme_payload(row: sqlite3.Row, source: str):
    return {
        "id": row["id"],
        "name": row["name"],
        "description": row["description"],
        "author": row["author_name"],
        "tags": json.loads(row["tags_json"]),
        "downloads": int(row["downloads"]),
        "updated": _format_date(row["updated_at"]),
        "rating": float(row["rating"]),
        "source": source,
        "colors": json.loads(row["colors_json"]),
    }


def list_public_themes():
    init_theme_store()
    with _connect() as connection:
        rows = connection.execute(
            """
            SELECT *
            FROM themes
            WHERE is_public = 1
            ORDER BY datetime(updated_at) DESC, name COLLATE NOCASE ASC
            """
        ).fetchall()
    return [_theme_payload(row, "marketplace") for row in rows]


def list_user_themes(user_id: str):
    init_theme_store()
    with _connect() as connection:
        rows = connection.execute(
            """
            SELECT DISTINCT themes.*
            FROM themes
            LEFT JOIN theme_installs
                ON theme_installs.theme_id = themes.id
                AND theme_installs.user_id = ?
            WHERE themes.author_id = ?
                OR theme_installs.user_id = ?
                OR themes.id = 'csrp-default'
            ORDER BY datetime(themes.updated_at) DESC, themes.name COLLATE NOCASE ASC
            """,
            (user_id, user_id, user_id),
        ).fetchall()
    return [_theme_payload(row, "custom") for row in rows]


def get_theme(theme_id: str):
    init_theme_store()
    with _connect() as connection:
        return connection.execute("SELECT * FROM themes WHERE id = ?", (theme_id,)).fetchone()


def install_theme(user_id: str, theme_id: str):
    init_theme_store()
    now = _utc_now()
    with _connect() as connection:
        theme = connection.execute("SELECT * FROM themes WHERE id = ? AND is_public = 1", (theme_id,)).fetchone()
        if theme is None:
            return None
        connection.execute(
            "INSERT OR IGNORE INTO theme_installs (user_id, theme_id, installed_at) VALUES (?, ?, ?)",
            (user_id, theme_id, now),
        )
        _refresh_download_counts(connection, theme_id)
        connection.commit()
        theme = connection.execute("SELECT * FROM themes WHERE id = ?", (theme_id,)).fetchone()
    return _theme_payload(theme, "custom")


def uninstall_theme(user_id: str, theme_id: str):
    init_theme_store()
    if theme_id == "csrp-default":
        return False
    with _connect() as connection:
        theme = connection.execute("SELECT author_id FROM themes WHERE id = ?", (theme_id,)).fetchone()
        if theme is None:
            return False
        if theme["author_id"] == user_id:
            connection.execute("DELETE FROM theme_installs WHERE theme_id = ?", (theme_id,))
            connection.execute("DELETE FROM themes WHERE id = ?", (theme_id,))
            result = "deleted"
        else:
            connection.execute("DELETE FROM theme_installs WHERE user_id = ? AND theme_id = ?", (user_id, theme_id))
            _refresh_download_counts(connection, theme_id)
            result = "removed"
        connection.commit()
    return result


def _clean_text(value: Any, fallback: str, limit: int):
    text = str(value or fallback).strip()
    text = re.sub(r"\s+", " ", text)
    return (text or fallback)[:limit]


def _validate_colors(colors: Any):
    if not isinstance(colors, dict):
        raise ValueError("Theme colors are required.")
    normalized = {}
    for key in THEME_COLOR_KEYS:
        value = colors.get(key)
        if not isinstance(value, str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", value):
            raise ValueError(f"Theme color '{key}' must be a 6 digit hex value.")
        normalized[key] = value.lower()
    return normalized


def _validate_tags(tags: Any):
    if not isinstance(tags, list):
        return ["custom"]
    normalized = []
    for tag in tags:
        clean_tag = _clean_text(tag, "", 28).lower()
        if clean_tag and clean_tag not in normalized:
            normalized.append(clean_tag)
        if len(normalized) == 8:
            break
    return normalized or ["custom"]


def create_theme(payload: dict[str, Any], author_id: str, author_name: str):
    init_theme_store()
    colors = _validate_colors(payload.get("colors"))
    tags = _validate_tags(payload.get("tags"))
    now = _utc_now()
    theme_id = f"theme-{uuid.uuid4().hex[:12]}"
    name = _clean_text(payload.get("name"), "Untitled Theme", 80)
    description = _clean_text(payload.get("description"), "Custom dashboard theme.", 220)

    with _connect() as connection:
        connection.execute(
            """
            INSERT INTO themes (
                id,
                name,
                description,
                author_id,
                author_name,
                tags_json,
                colors_json,
                downloads,
                rating,
                is_public,
                created_at,
                updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 0, 5, 1, ?, ?)
            """,
            (
                theme_id,
                name,
                description,
                author_id,
                author_name,
                json.dumps(tags),
                json.dumps(colors),
                now,
                now,
            ),
        )
        connection.execute(
            "INSERT OR IGNORE INTO theme_installs (user_id, theme_id, installed_at) VALUES (?, ?, ?)",
            (author_id, theme_id, now),
        )
        connection.commit()
        row = connection.execute("SELECT * FROM themes WHERE id = ?", (theme_id,)).fetchone()
    return _theme_payload(row, "custom")
