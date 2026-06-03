import asyncio
import json
import re
import secrets
import subprocess
import time
import uuid
from datetime import timedelta
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlparse

import discord
from discord.ext import commands
from werkzeug.utils import secure_filename

from config import (
    INFRACTION_CHANNEL,
    REPORT_GUILD_ID,
    SERVER_KEY,
    blacklisted_command,
    report_blacklists,
)
from cogs.helpers import CSRP_ICON, api_get, api_post, normalize_display_mentions
from cogs.moderation import (
    clear_all_modlogs_data,
    clear_user_modlogs,
    get_next_case,
    parse_time,
    save_modlog,
)
from cogs.settings import (
    DEFAULT_SETTINGS,
    PERMISSION_ROLE_LABELS,
    PERMISSION_USER_LABELS,
    RANK_ORDER,
    get_guild_settings,
    update_guild_setting,
    update_permission_role_setting,
    update_permission_user_setting,
    update_rank_role,
)
from cogs.staffmgmt import (
    DEMOTION_MAP,
    _can_manage_rank,
    _get_member_highest_rank,
    _get_target_role_ids,
    get_retirement,
    load_retirements,
    remove_retirement,
    save_retirement,
)
from modlog_store import count_modlogs, get_modlogs_for_user as get_modlogs_for_user_db

PRC_API = "https://api.erlc.gg/v1"
PRC_HEADERS = {"Content-Type": "application/json", "Server-Key": SERVER_KEY}
DEFAULT_GUILD_ID = REPORT_GUILD_ID
ERLC_CUSTOM_ACTIONS_FILE = "dashboard_erlc_actions.json"
MAX_ERLC_CUSTOM_ACTION_STEPS = 10
MAX_ERLC_CUSTOM_ACTION_WAIT_SECONDS = 60
MAX_ERLC_CUSTOM_ACTION_TOTAL_WAIT_SECONDS = 300
MAX_ERLC_CUSTOM_ACTIONS = 50
EVIDENCE_LOGS_FILE = "dashboard_evidence_logs.json"
EVIDENCE_UPLOAD_DIR = Path("dashboard_evidence_uploads")
EVIDENCE_REQUESTS_FILE = "dashboard_evidence_requests.json"
EVIDENCE_REQUEST_UPLOAD_DIR = Path("dashboard_evidence_request_uploads")
MAX_EVIDENCE_MEDIA_ITEMS = 3
MAX_EVIDENCE_DESCRIPTION_LENGTH = 1500
MAX_EVIDENCE_USERNAME_LENGTH = 100
IMAGE_EVIDENCE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp"}
VIDEO_EVIDENCE_EXTENSIONS = {".mp4", ".mov", ".webm", ".m4v"}


class DashboardSentMessage:
    def __init__(self, content=None, embed=None, embeds=None):
        self.content = content
        self.embed = embed
        self.embeds = embeds or ([embed] if embed else [])
        self.deleted = False

    async def edit(self, **kwargs):
        self.content = kwargs.get("content", self.content)
        if "embed" in kwargs:
            self.embed = kwargs["embed"]
            self.embeds = [self.embed] if self.embed else []
        if "embeds" in kwargs:
            self.embeds = kwargs["embeds"] or []
            self.embed = self.embeds[0] if self.embeds else None
        return self

    async def delete(self, *args, **kwargs):
        self.deleted = True


class _NoopTyping:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False


class DashboardCommandContext:
    def __init__(self, bot, guild: discord.Guild, author: discord.Member, channel=None):
        self.bot = bot
        self.guild = guild
        self.author = author
        self.channel = channel
        self.me = guild.me
        self.message = None
        self.interaction = None
        self.command = None
        self.invoked_subcommand = None
        self.prefix = "/"
        self.clean_prefix = "/"
        self.sent_messages: list[DashboardSentMessage] = []

    async def send(self, content=None, **kwargs):
        kwargs.pop("ephemeral", None)
        message = DashboardSentMessage(
            content=content,
            embed=kwargs.get("embed"),
            embeds=kwargs.get("embeds"),
        )
        self.sent_messages.append(message)
        if self.channel is None:
            return message
        return await self.channel.send(content=content, **kwargs)

    async def reply(self, content=None, **kwargs):
        kwargs.pop("mention_author", None)
        return await self.send(content=content, **kwargs)

    async def defer(self, *args, **kwargs):
        return None

    def typing(self):
        return _NoopTyping()


def _message_summary(message: DashboardSentMessage) -> str:
    if message.content:
        return str(message.content)

    embeds = message.embeds or ([message.embed] if message.embed else [])
    for embed in embeds:
        if embed is None:
            continue
        title = getattr(embed, "title", None)
        description = getattr(embed, "description", None)
        if title and description:
            return f"{title}: {description}"
        if title:
            return str(title)
        if description:
            return str(description)

    return ""


def _looks_like_command_failure(summary: str) -> bool:
    lowered = summary.casefold()
    failure_markers = [
        "action blocked",
        "blacklisted",
        "cannot ",
        "connection error",
        "failed",
        "invalid",
        "insufficient rank",
        "manual handling required",
        "missing ",
        "no record",
        "not configured",
        "not banned",
        "not found",
        "not permitted",
        "not staff",
        "rate limited",
        "role not",
        "server offline",
        "unauthorized",
        "unexpected error",
    ]
    non_fatal_markers = [
        "dm failed",
    ]
    return any(marker in lowered for marker in failure_markers) and not any(
        marker in lowered for marker in non_fatal_markers
    )


def _load_json_file(path: str, fallback: Any):
    try:
        with open(path, "r") as file:
            return json.load(file)
    except (FileNotFoundError, json.JSONDecodeError):
        return fallback


def _load_lines(path: str) -> list[str]:
    try:
        with open(path, "r") as file:
            return [line.strip() for line in file if line.strip()]
    except FileNotFoundError:
        return []


def _save_lines(path: str, lines: list[str]) -> None:
    with open(path, "w") as file:
        file.write("\n".join(lines) + ("\n" if lines else ""))


def _evidence_code() -> str:
    return secrets.token_urlsafe(5).replace("-", "").replace("_", "")[:8]


def _evidence_media_type(filename_or_url: str) -> str | None:
    suffix = Path(urlparse(filename_or_url).path).suffix.lower()
    if suffix in IMAGE_EVIDENCE_EXTENSIONS:
        return "image"
    if suffix in VIDEO_EVIDENCE_EXTENSIONS:
        return "video"
    return None


def _safe_evidence_url(url: str) -> str:
    cleaned_url = str(url or "").strip()
    parsed = urlparse(cleaned_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise RuntimeError("Evidence links must be valid http or https URLs.")
    if _evidence_media_type(cleaned_url) is None:
        raise RuntimeError("Evidence links must point to an image, GIF, or video file.")
    return cleaned_url


def _sanitize_evidence_request_submission(entry: dict) -> dict | None:
    if not isinstance(entry, dict):
        return None

    submission_id = str(entry.get("id", "")).strip()
    submitter_name = str(entry.get("submitter_name", "")).strip()
    description = str(entry.get("description", "")).strip()
    raw_media_items = entry.get("media_items", [])
    if not isinstance(raw_media_items, list):
        raw_media_items = []
    media_items = [
        item
        for item in (_sanitize_evidence_media_item(media_item) for media_item in raw_media_items)
        if item
    ]

    if not submission_id or not submitter_name or not media_items:
        return None

    return {
        "id": submission_id,
        "submitter_name": submitter_name[:MAX_EVIDENCE_USERNAME_LENGTH],
        "description": description[:MAX_EVIDENCE_DESCRIPTION_LENGTH],
        "media_items": media_items[:MAX_EVIDENCE_MEDIA_ITEMS],
        "created_at": int(entry.get("created_at", 0) or 0),
    }


def _sanitize_evidence_request(entry: dict) -> dict | None:
    if not isinstance(entry, dict):
        return None

    request_id = str(entry.get("id", "")).strip()
    target_username = str(entry.get("target_username", "")).strip()
    prompt = str(entry.get("prompt", "")).strip()
    raw_submissions = entry.get("submissions", [])
    if not isinstance(raw_submissions, list):
        raw_submissions = []
    submissions = [
        submission
        for submission in (_sanitize_evidence_request_submission(item) for item in raw_submissions)
        if submission
    ]

    if not request_id or not target_username or not prompt:
        return None

    return {
        "id": request_id,
        "target_user_id": str(entry.get("target_user_id", "")).strip(),
        "target_username": target_username[:MAX_EVIDENCE_USERNAME_LENGTH],
        "target_lookup": str(entry.get("target_lookup", "")).strip() or _normalize_user_lookup(target_username),
        "prompt": prompt[:MAX_EVIDENCE_DESCRIPTION_LENGTH],
        "status": "closed" if str(entry.get("status", "")).strip().lower() == "closed" else "open",
        "created_by": str(entry.get("created_by", "")).strip(),
        "created_at": int(entry.get("created_at", 0) or 0),
        "submissions": sorted(submissions, key=lambda item: item["created_at"], reverse=True),
    }


def _sanitize_evidence_media_item(item: dict) -> dict | None:
    if not isinstance(item, dict):
        return None

    media_source = str(item.get("media_source", item.get("source", ""))).strip()
    media_type = str(item.get("media_type", item.get("type", ""))).strip()
    media_url = str(item.get("media_url", item.get("url", ""))).strip()
    filename = str(item.get("filename", "")).strip()

    if media_source not in {"upload", "link"} or media_type not in {"image", "video"}:
        return None
    if media_source == "upload" and not filename:
        return None
    if media_source == "link" and not media_url:
        return None

    return {
        "media_source": media_source,
        "media_type": media_type,
        "media_url": media_url,
        "filename": filename,
    }


def _sanitize_evidence_entry(entry: dict) -> dict | None:
    if not isinstance(entry, dict):
        return None

    evidence_id = str(entry.get("id", "")).strip()
    target_username = str(entry.get("target_username", "")).strip()
    description = str(entry.get("description", "")).strip()
    raw_media_items = entry.get("media_items", [])
    if not isinstance(raw_media_items, list):
        raw_media_items = []
    media_items = [
        item
        for item in (_sanitize_evidence_media_item(media_item) for media_item in raw_media_items)
        if item
    ]
    if not media_items:
        legacy_media_item = _sanitize_evidence_media_item(entry)
        if legacy_media_item:
            media_items = [legacy_media_item]

    if not evidence_id or not target_username or not description or not media_items:
        return None

    visibility = str(entry.get("visibility", entry.get("access", "all"))).strip().lower()
    if visibility not in {"all", "dashboard", "roles"}:
        visibility = "all"
    raw_viewer_role_ids = entry.get("viewer_role_ids", entry.get("allowed_role_ids", []))
    if not isinstance(raw_viewer_role_ids, list):
        raw_viewer_role_ids = []
    viewer_role_ids = sorted({
        str(role_id).strip()
        for role_id in raw_viewer_role_ids
        if str(role_id).strip().isdigit()
    })
    if visibility == "roles" and not viewer_role_ids:
        visibility = "dashboard"

    first_media_item = media_items[0]
    return {
        "id": evidence_id,
        "target_user_id": str(entry.get("target_user_id", "")).strip(),
        "target_username": target_username[:MAX_EVIDENCE_USERNAME_LENGTH],
        "target_lookup": str(entry.get("target_lookup", "")).strip() or _normalize_user_lookup(target_username),
        "description": description[:MAX_EVIDENCE_DESCRIPTION_LENGTH],
        "sensitive": bool(entry.get("sensitive")),
        "visibility": visibility,
        "viewer_role_ids": viewer_role_ids,
        "media_items": media_items[:MAX_EVIDENCE_MEDIA_ITEMS],
        "media_source": first_media_item["media_source"],
        "media_type": first_media_item["media_type"],
        "media_url": first_media_item["media_url"],
        "filename": first_media_item["filename"],
        "created_by": str(entry.get("created_by", "")).strip(),
        "created_at": int(entry.get("created_at", 0) or 0),
    }


def load_evidence_logs() -> list[dict]:
    entries = _load_json_file(EVIDENCE_LOGS_FILE, [])
    if not isinstance(entries, list):
        return []
    return [entry for entry in (_sanitize_evidence_entry(item) for item in entries) if entry]


def _save_evidence_logs(entries: list[dict]) -> None:
    with open(EVIDENCE_LOGS_FILE, "w") as file:
        json.dump(entries, file, indent=4)


def load_evidence_requests() -> list[dict]:
    entries = _load_json_file(EVIDENCE_REQUESTS_FILE, [])
    if not isinstance(entries, list):
        return []
    return [entry for entry in (_sanitize_evidence_request(item) for item in entries) if entry]


def _save_evidence_requests(entries: list[dict]) -> None:
    with open(EVIDENCE_REQUESTS_FILE, "w") as file:
        json.dump(entries, file, indent=4)


def _public_evidence_payload(entry: dict, public_origin: str) -> dict:
    media_items = []
    for media_item in entry["media_items"]:
        media_url = media_item["media_url"]
        if media_item["media_source"] == "upload":
            media_url = f"/api/evidence-media/{quote(entry['id'])}/{quote(media_item['filename'])}"
        media_items.append({
            "media_source": media_item["media_source"],
            "media_type": media_item["media_type"],
            "media_url": media_url,
            "filename": media_item["filename"],
        })

    first_media_item = media_items[0]

    return {
        "id": entry["id"],
        "target_user_id": entry.get("target_user_id", ""),
        "target_username": entry["target_username"],
        "description": entry["description"],
        "sensitive": bool(entry["sensitive"]),
        "visibility": entry.get("visibility", "all"),
        "viewer_role_ids": [str(role_id) for role_id in entry.get("viewer_role_ids", [])],
        "media_items": media_items,
        "media_source": first_media_item["media_source"],
        "media_type": first_media_item["media_type"],
        "media_url": first_media_item["media_url"],
        "public_url": f"{public_origin.rstrip('/')}/evidence/{quote(entry['id'])}",
        "created_at": int(entry.get("created_at", 0) or 0),
        "created_by": entry.get("created_by", ""),
    }


def public_evidence_payload(entry: dict, public_origin: str) -> dict:
    sanitized_entry = _sanitize_evidence_entry(entry)
    if sanitized_entry is None:
        raise RuntimeError("Evidence entry is invalid.")
    return _public_evidence_payload(sanitized_entry, public_origin)


def get_evidence_by_code(evidence_id: str) -> dict | None:
    target_id = str(evidence_id or "").strip()
    if not target_id:
        return None
    return next((entry for entry in load_evidence_logs() if entry["id"] == target_id), None)


def evidence_request_upload_directory(request_id: str, submission_id: str) -> Path:
    return EVIDENCE_REQUEST_UPLOAD_DIR / str(request_id) / str(submission_id)


def _public_evidence_request_submission_payload(request_id: str, submission: dict) -> dict:
    media_items = []
    for media_item in submission["media_items"]:
        media_url = media_item["media_url"]
        if media_item["media_source"] == "upload":
            media_url = f"/api/evidence-request-media/{quote(request_id)}/{quote(submission['id'])}/{quote(media_item['filename'])}"
        media_items.append({
            "media_source": media_item["media_source"],
            "media_type": media_item["media_type"],
            "media_url": media_url,
            "filename": media_item["filename"],
        })

    return {
        "id": submission["id"],
        "submitter_name": submission["submitter_name"],
        "description": submission.get("description", ""),
        "media_items": media_items,
        "created_at": submission["created_at"],
    }


def _public_evidence_request_payload(entry: dict, public_origin: str, include_submissions: bool) -> dict:
    payload = {
        "id": entry["id"],
        "target_user_id": entry.get("target_user_id", ""),
        "target_username": entry["target_username"],
        "prompt": entry["prompt"],
        "status": entry.get("status", "open"),
        "created_by": entry.get("created_by", ""),
        "created_at": int(entry.get("created_at", 0) or 0),
        "submission_count": len(entry.get("submissions", [])),
        "public_url": f"{public_origin.rstrip('/')}/evidence-request/{quote(entry['id'])}",
    }
    if include_submissions:
        payload["submissions"] = [
            _public_evidence_request_submission_payload(entry["id"], submission)
            for submission in entry.get("submissions", [])
        ]
    return payload


def public_evidence_request_payload(entry: dict, public_origin: str, include_submissions: bool = False) -> dict:
    sanitized_entry = _sanitize_evidence_request(entry)
    if sanitized_entry is None:
        raise RuntimeError("Evidence request is invalid.")
    return _public_evidence_request_payload(sanitized_entry, public_origin, include_submissions)


def get_evidence_request_by_code(request_id: str) -> dict | None:
    target_id = str(request_id or "").strip()
    if not target_id:
        return None
    return next((entry for entry in load_evidence_requests() if entry["id"] == target_id), None)


def get_evidence_requests_for_user(username: str, resolved_user_id: int | None, public_origin: str) -> list[dict]:
    normalized_lookup = _normalize_user_lookup(username)
    raw_username = str(username or "").strip()
    matches = []
    for entry in load_evidence_requests():
        user_id_matches = resolved_user_id is not None and entry.get("target_user_id") == str(resolved_user_id)
        raw_id_matches = raw_username.isdigit() and entry.get("target_user_id") == raw_username
        name_matches = normalized_lookup and entry.get("target_lookup") == normalized_lookup
        if user_id_matches or raw_id_matches or name_matches:
            matches.append(_public_evidence_request_payload(entry, public_origin, include_submissions=True))
    return sorted(matches, key=lambda item: item["created_at"], reverse=True)


def get_evidence_for_user(username: str, resolved_user_id: int | None, public_origin: str) -> list[dict]:
    normalized_lookup = _normalize_user_lookup(username)
    raw_username = str(username or "").strip()
    matches = []
    for entry in load_evidence_logs():
        user_id_matches = resolved_user_id is not None and entry.get("target_user_id") == str(resolved_user_id)
        raw_id_matches = raw_username.isdigit() and entry.get("target_user_id") == raw_username
        name_matches = normalized_lookup and entry.get("target_lookup") == normalized_lookup
        if user_id_matches or raw_id_matches or name_matches:
            matches.append(_public_evidence_payload(entry, public_origin))
    return sorted(matches, key=lambda item: item["created_at"], reverse=True)


def evidence_upload_directory(evidence_id: str) -> Path:
    return EVIDENCE_UPLOAD_DIR / str(evidence_id)


def _form_media_urls(form_data: dict) -> list[str]:
    media_urls = []
    if hasattr(form_data, "getlist"):
        media_urls.extend(str(url).strip() for url in form_data.getlist("media_urls"))
    media_url = str(form_data.get("media_url", "")).strip()
    if media_url:
        media_urls.append(media_url)
    return [url for url in media_urls if url]


async def create_evidence_log(bot, actor_id: int, form_data: dict, uploaded_files, public_origin: str) -> dict:
    target_username = str(form_data.get("target_username", "")).strip().lstrip("@")
    description = str(form_data.get("description", "")).strip()
    uploaded_files = [
        uploaded_file
        for uploaded_file in (uploaded_files or [])
        if uploaded_file and getattr(uploaded_file, "filename", "")
    ]
    linked_media_urls = _form_media_urls(form_data)
    evidence_item_count = len(uploaded_files) + len(linked_media_urls)
    visibility = str(form_data.get("visibility", "all")).strip().lower()
    if visibility not in {"all", "dashboard", "roles"}:
        visibility = "all"
    viewer_role_ids = []
    if hasattr(form_data, "getlist"):
        viewer_role_ids = [
            str(role_id).strip()
            for role_id in form_data.getlist("viewer_role_ids")
            if str(role_id).strip().isdigit()
        ]
    viewer_role_ids = sorted(set(viewer_role_ids))

    if not target_username:
        raise RuntimeError("Add the username this evidence belongs to.")
    if not description:
        raise RuntimeError("Add a description for the ban evidence.")
    if evidence_item_count == 0:
        raise RuntimeError("Add at least one evidence upload or link.")
    if evidence_item_count > MAX_EVIDENCE_MEDIA_ITEMS:
        raise RuntimeError(f"You can add up to {MAX_EVIDENCE_MEDIA_ITEMS} evidence uploads or links.")
    if visibility == "roles" and not viewer_role_ids:
        raise RuntimeError("Choose at least one role when evidence visibility is set to selected roles.")

    target_user_id = ""
    stored_username = target_username[:MAX_EVIDENCE_USERNAME_LENGTH]
    try:
        resolved_user = await resolve_user(bot, target_username)
        target_user_id = str(resolved_user.id)
        stored_username = (
            getattr(resolved_user, "display_name", None)
            or getattr(resolved_user, "global_name", None)
            or getattr(resolved_user, "name", target_username)
        )[:MAX_EVIDENCE_USERNAME_LENGTH]
    except RuntimeError:
        pass

    entries = load_evidence_logs()
    evidence_id = _evidence_code()
    while any(entry["id"] == evidence_id for entry in entries):
        evidence_id = _evidence_code()

    validated_links = [_safe_evidence_url(linked_media_url) for linked_media_url in linked_media_urls]
    upload_dir = evidence_upload_directory(evidence_id)
    media_items = []
    for index, uploaded_file in enumerate(uploaded_files, start=1):
        original_filename = secure_filename(uploaded_file.filename or "")
        if not original_filename:
            raise RuntimeError("Uploaded evidence needs a valid file name.")
        media_type = _evidence_media_type(original_filename) or ""
        if media_type == "":
            raise RuntimeError("Uploaded evidence must be an image, GIF, or video.")

        upload_dir.mkdir(parents=True, exist_ok=True)
        filename = f"evidence-{index}{Path(original_filename).suffix.lower()}"
        uploaded_file.save(upload_dir / filename)
        media_items.append({
            "media_source": "upload",
            "media_type": media_type,
            "media_url": "",
            "filename": filename,
        })

    for media_url in validated_links:
        media_items.append({
            "media_source": "link",
            "media_type": _evidence_media_type(media_url) or "",
            "media_url": media_url,
            "filename": "",
        })

    first_media_item = media_items[0]

    entry = {
        "id": evidence_id,
        "target_user_id": target_user_id,
        "target_username": stored_username,
        "target_lookup": _normalize_user_lookup(target_username),
        "description": description[:MAX_EVIDENCE_DESCRIPTION_LENGTH],
        "sensitive": form_data.get("sensitive") == "on",
        "visibility": visibility,
        "viewer_role_ids": viewer_role_ids,
        "media_items": media_items,
        "media_source": first_media_item["media_source"],
        "media_type": first_media_item["media_type"],
        "media_url": first_media_item["media_url"],
        "filename": first_media_item["filename"],
        "created_by": str(actor_id),
        "created_at": int(time.time()),
    }
    entries.append(entry)
    _save_evidence_logs(entries)
    return _public_evidence_payload(entry, public_origin)


async def create_evidence_request(bot, actor_id: int, form_data: dict, public_origin: str) -> dict:
    target_username = str(form_data.get("target_username", "")).strip().lstrip("@")
    prompt = str(form_data.get("prompt", "")).strip()
    if not target_username:
        raise RuntimeError("Add the username this upload request belongs to.")
    if not prompt:
        raise RuntimeError("Add instructions for the user upload request.")

    target_user_id = ""
    stored_username = target_username[:MAX_EVIDENCE_USERNAME_LENGTH]
    try:
        resolved_user = await resolve_user(bot, target_username)
        target_user_id = str(resolved_user.id)
        stored_username = (
            getattr(resolved_user, "display_name", None)
            or getattr(resolved_user, "global_name", None)
            or getattr(resolved_user, "name", target_username)
        )[:MAX_EVIDENCE_USERNAME_LENGTH]
    except RuntimeError:
        pass

    entries = load_evidence_requests()
    request_id = _evidence_code()
    while any(entry["id"] == request_id for entry in entries):
        request_id = _evidence_code()

    entry = {
        "id": request_id,
        "target_user_id": target_user_id,
        "target_username": stored_username,
        "target_lookup": _normalize_user_lookup(target_username),
        "prompt": prompt[:MAX_EVIDENCE_DESCRIPTION_LENGTH],
        "status": "open",
        "created_by": str(actor_id),
        "created_at": int(time.time()),
        "submissions": [],
    }
    entries.append(entry)
    _save_evidence_requests(entries)
    return _public_evidence_request_payload(entry, public_origin, include_submissions=True)


def submit_evidence_request(form_data: dict, uploaded_files, request_id: str, public_origin: str) -> dict:
    request_entry = get_evidence_request_by_code(request_id)
    if request_entry is None:
        raise RuntimeError("This upload request was not found.")
    if request_entry.get("status") != "open":
        raise RuntimeError("This upload request is closed.")

    submitter_name = str(form_data.get("submitter_name", "")).strip().lstrip("@")
    description = str(form_data.get("description", "")).strip()
    uploaded_files = [
        uploaded_file
        for uploaded_file in (uploaded_files or [])
        if uploaded_file and getattr(uploaded_file, "filename", "")
    ]
    linked_media_urls = _form_media_urls(form_data)
    evidence_item_count = len(uploaded_files) + len(linked_media_urls)

    if not submitter_name:
        raise RuntimeError("Add your username before submitting.")
    if evidence_item_count == 0:
        raise RuntimeError("Add at least one upload or media link.")
    if evidence_item_count > MAX_EVIDENCE_MEDIA_ITEMS:
        raise RuntimeError(f"You can submit up to {MAX_EVIDENCE_MEDIA_ITEMS} uploads or links at once.")

    validated_links = [_safe_evidence_url(linked_media_url) for linked_media_url in linked_media_urls]
    submission_id = uuid.uuid4().hex[:10]
    upload_dir = evidence_request_upload_directory(request_id, submission_id)
    media_items = []

    for index, uploaded_file in enumerate(uploaded_files, start=1):
        original_filename = secure_filename(uploaded_file.filename or "")
        if not original_filename:
            raise RuntimeError("Uploaded evidence needs a valid file name.")
        media_type = _evidence_media_type(original_filename) or ""
        if media_type == "":
            raise RuntimeError("Uploaded evidence must be an image, GIF, or video.")

        upload_dir.mkdir(parents=True, exist_ok=True)
        filename = f"submission-{index}{Path(original_filename).suffix.lower()}"
        uploaded_file.save(upload_dir / filename)
        media_items.append({
            "media_source": "upload",
            "media_type": media_type,
            "media_url": "",
            "filename": filename,
        })

    for media_url in validated_links:
        media_items.append({
            "media_source": "link",
            "media_type": _evidence_media_type(media_url) or "",
            "media_url": media_url,
            "filename": "",
        })

    submission = {
        "id": submission_id,
        "submitter_name": submitter_name[:MAX_EVIDENCE_USERNAME_LENGTH],
        "description": description[:MAX_EVIDENCE_DESCRIPTION_LENGTH],
        "media_items": media_items,
        "created_at": int(time.time()),
    }

    entries = load_evidence_requests()
    for index, entry in enumerate(entries):
        if entry["id"] == request_id:
            updated_entry = dict(entry)
            updated_entry["submissions"] = [submission, *entry.get("submissions", [])]
            entries[index] = updated_entry
            _save_evidence_requests(entries)
            return _public_evidence_request_payload(updated_entry, public_origin, include_submissions=False)

    raise RuntimeError("This upload request was not found.")


def _parse_discord_user_id(identifier: Any) -> int | None:
    if isinstance(identifier, int):
        return identifier

    raw_identifier = str(identifier or "").strip()
    mention_match = re.fullmatch(r"<@!?(\d+)>", raw_identifier)
    if mention_match:
        return int(mention_match.group(1))
    if raw_identifier.isdigit():
        return int(raw_identifier)
    return None


def _normalize_user_lookup(identifier: Any) -> str:
    return re.sub(r"\s+", " ", str(identifier or "").strip().lstrip("@")).casefold()


def _user_name_candidates(user) -> list[str]:
    candidates = [
        getattr(user, "name", ""),
        getattr(user, "display_name", ""),
        getattr(user, "global_name", ""),
        getattr(user, "nick", ""),
    ]
    name = getattr(user, "name", "")
    discriminator = getattr(user, "discriminator", "")
    if name and discriminator and discriminator != "0":
        candidates.append(f"{name}#{discriminator}")

    return [candidate for candidate in candidates if candidate]


def _user_matches_lookup(user, normalized_lookup: str) -> bool:
    return any(_normalize_user_lookup(candidate) == normalized_lookup for candidate in _user_name_candidates(user))


async def _find_member_by_name(guild: discord.Guild, identifier: Any) -> discord.Member | None:
    raw_identifier = str(identifier or "").strip().lstrip("@")
    normalized_lookup = _normalize_user_lookup(raw_identifier)
    if not normalized_lookup:
        return None

    for member in guild.members:
        if _user_matches_lookup(member, normalized_lookup):
            return member

    named_member = guild.get_member_named(raw_identifier)
    if named_member is not None:
        return named_member

    try:
        matches = await guild.query_members(raw_identifier, limit=25)
    except (AttributeError, discord.HTTPException, discord.Forbidden):
        matches = []

    exact_matches = [member for member in matches if _user_matches_lookup(member, normalized_lookup)]
    if len(exact_matches) == 1:
        return exact_matches[0]
    return None


async def _find_banned_user_by_name(guild: discord.Guild, identifier: Any):
    raw_identifier = str(identifier or "").strip().lstrip("@")
    normalized_lookup = _normalize_user_lookup(raw_identifier)
    if not normalized_lookup:
        return None

    try:
        try:
            bans = guild.bans(limit=None)
        except TypeError:
            bans = guild.bans()

        if hasattr(bans, "__aiter__"):
            async for ban_entry in bans:
                if _user_matches_lookup(ban_entry.user, normalized_lookup):
                    return ban_entry.user
        else:
            for ban_entry in await bans:
                if _user_matches_lookup(ban_entry.user, normalized_lookup):
                    return ban_entry.user
    except (AttributeError, TypeError, discord.HTTPException, discord.Forbidden):
        return None
    return None


async def resolve_member(bot, user_identifier: Any) -> discord.Member:
    guild = await get_target_guild(bot)
    user_id = _parse_discord_user_id(user_identifier)
    if user_id is not None:
        member = guild.get_member(user_id)
        if member is not None:
            return member
        try:
            return await guild.fetch_member(user_id)
        except discord.NotFound as exc:
            raise RuntimeError(f"Could not find a server member with ID {user_id}.") from exc

    member = await _find_member_by_name(guild, user_identifier)
    if member is None:
        raise RuntimeError(f"Could not find a server member matching '{str(user_identifier).strip()}'. Try their Discord user ID.")
    return member


async def resolve_user(bot, user_identifier: Any):
    guild = await get_target_guild(bot)
    user_id = _parse_discord_user_id(user_identifier)
    if user_id is not None:
        member = guild.get_member(user_id)
        if member is not None:
            return member
        try:
            return await bot.fetch_user(user_id)
        except discord.NotFound as exc:
            raise RuntimeError(f"Could not find a Discord user with ID {user_id}.") from exc

    member = await _find_member_by_name(guild, user_identifier)
    if member is not None:
        return member

    banned_user = await _find_banned_user_by_name(guild, user_identifier)
    if banned_user is not None:
        return banned_user

    raise RuntimeError(f"Could not find a Discord user matching '{str(user_identifier).strip()}'. Try their Discord user ID.")


async def resolve_user_id(bot, user_identifier: Any) -> int:
    return int((await resolve_user(bot, user_identifier)).id)


async def get_target_guild(bot) -> discord.Guild:
    guild = bot.get_guild(DEFAULT_GUILD_ID)
    if guild is None:
        raise RuntimeError(f"Bot is not connected to guild {DEFAULT_GUILD_ID}.")
    return guild


async def get_member(bot, user_id: Any) -> discord.Member:
    return await resolve_member(bot, user_id)


async def get_actor_member(bot, actor_id: int) -> discord.Member:
    return await get_member(bot, actor_id)


async def _resolve_dashboard_command_channel(bot, channel_id):
    if not channel_id:
        return None
    channel = bot.get_channel(int(channel_id))
    if channel is None:
        raise RuntimeError("Command target channel was not found.")
    return channel


async def run_dashboard_command(bot, actor_id: int, command_name: str, parameters: dict | None = None, channel_id=None) -> str:
    guild = await get_target_guild(bot)
    actor = await get_actor_member(bot, actor_id)
    command = bot.get_command(command_name)
    if command is None:
        raise RuntimeError(f"Command '/{command_name}' is not loaded.")

    ctx = DashboardCommandContext(
        bot=bot,
        guild=guild,
        author=actor,
        channel=await _resolve_dashboard_command_channel(bot, channel_id),
    )
    ctx.command = command

    try:
        can_run = await command.can_run(ctx)
    except commands.CommandError as exc:
        raise RuntimeError(str(exc) or "You are not permitted to use this command.") from exc
    if not can_run:
        raise RuntimeError("You are not permitted to use this command.")

    callback_args = [ctx]
    if command.cog is not None:
        callback_args.insert(0, command.cog)

    await command.callback(*callback_args, **(parameters or {}))

    summary = ""
    for message in reversed(ctx.sent_messages):
        summary = _message_summary(message)
        if summary:
            break

    if summary and _looks_like_command_failure(summary):
        raise RuntimeError(summary)

    return summary or f"Executed /{command_name}."


async def run_dashboard_member_command(
    bot,
    actor_id: int,
    command_name: str,
    user_identifier: Any,
    parameters: dict | None = None,
    *,
    user_parameter: str = "user",
    channel_id=None,
) -> str:
    member = await resolve_member(bot, user_identifier)
    command_parameters = dict(parameters or {})
    command_parameters[user_parameter] = member
    return await run_dashboard_command(bot, actor_id, command_name, command_parameters, channel_id=channel_id)


async def run_dashboard_ban_command(bot, actor_id: int, user_identifier: Any, reason: str) -> str:
    try:
        user_arg = await resolve_member(bot, user_identifier)
    except RuntimeError:
        user_arg = await resolve_user_id(bot, user_identifier)
    return await run_dashboard_command(bot, actor_id, "ban", {"user": user_arg, "reason": reason})


async def run_dashboard_unban_command(bot, actor_id: int, user_identifier: Any, reason: str) -> str:
    user_id = await resolve_user_id(bot, user_identifier)
    return await run_dashboard_command(bot, actor_id, "unban", {"user_id": user_id, "reason": reason})


async def collect_dashboard_stats(bot) -> dict:
    guild = await get_target_guild(bot)
    retirements = load_retirements().get(str(guild.id), {})
    command_blacklist_count = len(_load_lines(blacklisted_command))
    report_blacklist_count = len(_load_lines(report_blacklists))
    start_time = getattr(getattr(bot, "cogs", {}).get("Utility"), "start_time", None)
    uptime_seconds = int(time.time() - start_time) if start_time else 0

    erlc_server = {}
    erlc_players = []
    try:
        _, erlc_server = await api_get(f"{PRC_API}/server", headers={"Server-Key": SERVER_KEY})
        _, erlc_players = await api_get(f"{PRC_API}/server/players", headers={"Server-Key": SERVER_KEY})
    except Exception:
        pass

    return {
        "guild_name": guild.name,
        "member_count": guild.member_count or len(guild.members),
        "role_count": len(guild.roles),
        "channel_count": len(guild.channels),
        "modlog_count": count_modlogs(),
        "retirement_count": len(retirements),
        "command_blacklist_count": command_blacklist_count,
        "report_blacklist_count": report_blacklist_count,
        "bot_name": bot.user.display_name if bot.user else "Bot",
        "bot_id": bot.user.id if bot.user else None,
        "bot_latency_ms": round(bot.latency * 1000),
        "bot_created_at": bot.user.created_at if bot.user else None,
        "uptime_seconds": max(uptime_seconds, 0),
        "erlc_server": erlc_server or {},
        "erlc_player_count": len(erlc_players) if isinstance(erlc_players, list) else 0,
    }


async def fetch_erlc_players() -> list[dict]:
    status, players = await api_get(f"{PRC_API}/server/players", headers={"Server-Key": SERVER_KEY})
    if status != 200 or not isinstance(players, list):
        raise RuntimeError("Failed to fetch ERLC players.")
    return players


async def fetch_erlc_server() -> dict:
    status, data = await api_get(f"{PRC_API}/server", headers={"Server-Key": SERVER_KEY})
    if status != 200 or not isinstance(data, dict):
        raise RuntimeError("Failed to fetch ERLC server information.")
    return data


async def send_erlc_command(command: str) -> str:
    normalized = command if command.startswith(":") else f":{command}"
    status, _ = await api_post(f"{PRC_API}/server/command", headers=PRC_HEADERS, json={"command": normalized})
    if status != 200:
        raise RuntimeError(f"ERLC API returned status {status}.")
    return normalized


def _form_values(form_data: dict, key: str) -> list[str]:
    if hasattr(form_data, "getlist"):
        return [str(value).strip() for value in form_data.getlist(key)]
    value = form_data.get(key, [])
    if isinstance(value, list):
        return [str(item).strip() for item in value]
    return [str(value).strip()] if str(value).strip() else []


def _sanitize_erlc_action(action: dict) -> dict | None:
    if not isinstance(action, dict):
        return None
    action_id = str(action.get("id", "")).strip()
    name = str(action.get("name", "")).strip()
    raw_steps = action.get("steps", [])
    if not action_id or not name or not isinstance(raw_steps, list):
        return None

    steps = []
    for step in raw_steps[:MAX_ERLC_CUSTOM_ACTION_STEPS]:
        if not isinstance(step, dict):
            continue
        if step.get("type") == "wait":
            try:
                seconds = int(step.get("seconds", 0))
            except (TypeError, ValueError):
                continue
            if 1 <= seconds <= MAX_ERLC_CUSTOM_ACTION_WAIT_SECONDS:
                steps.append({"type": "wait", "seconds": seconds})
            continue

        command = str(step.get("command", "")).strip()
        if command:
            steps.append({"type": "command", "command": command[:500]})

    if not steps:
        return None

    return {
        "id": action_id,
        "name": name[:64],
        "steps": steps,
        "created_by": str(action.get("created_by", "")).strip(),
        "created_at": int(action.get("created_at", 0) or 0),
        "updated_at": int(action.get("updated_at", 0) or 0),
    }


def load_erlc_custom_actions() -> list[dict]:
    actions = _load_json_file(ERLC_CUSTOM_ACTIONS_FILE, [])
    if not isinstance(actions, list):
        return []
    return [action for action in (_sanitize_erlc_action(item) for item in actions) if action]


def _save_erlc_custom_actions(actions: list[dict]) -> None:
    with open(ERLC_CUSTOM_ACTIONS_FILE, "w") as file:
        json.dump(actions, file, indent=4)


def _parse_erlc_custom_action_steps(form_data: dict) -> list[dict]:
    step_types = _form_values(form_data, "step_type")
    step_commands = _form_values(form_data, "step_command")
    step_seconds = _form_values(form_data, "step_seconds")
    step_count = min(MAX_ERLC_CUSTOM_ACTION_STEPS, max(len(step_types), len(step_commands), len(step_seconds)))
    if step_count == 0:
        raise RuntimeError("Add at least one custom action step.")

    steps = []
    command_count = 0
    total_wait = 0
    for index in range(step_count):
        step_type = (step_types[index] if index < len(step_types) else "command").lower()
        if step_type == "wait":
            raw_seconds = step_seconds[index] if index < len(step_seconds) else ""
            try:
                seconds = int(raw_seconds)
            except ValueError as exc:
                raise RuntimeError(f"Step {index + 1} has an invalid wait time.") from exc
            if seconds < 1 or seconds > MAX_ERLC_CUSTOM_ACTION_WAIT_SECONDS:
                raise RuntimeError(
                    f"Step {index + 1} wait must be between 1 and {MAX_ERLC_CUSTOM_ACTION_WAIT_SECONDS} seconds."
                )
            total_wait += seconds
            if total_wait > MAX_ERLC_CUSTOM_ACTION_TOTAL_WAIT_SECONDS:
                raise RuntimeError(
                    f"Custom actions can wait up to {MAX_ERLC_CUSTOM_ACTION_TOTAL_WAIT_SECONDS} total seconds."
                )
            steps.append({"type": "wait", "seconds": seconds})
            continue

        command = step_commands[index] if index < len(step_commands) else ""
        if not command:
            raise RuntimeError(f"Step {index + 1} needs an ERLC command.")
        if len(command) > 500:
            raise RuntimeError(f"Step {index + 1} command is too long.")
        command_count += 1
        steps.append({"type": "command", "command": command})

    if command_count == 0:
        raise RuntimeError("Custom actions need at least one ERLC command step.")
    return steps


def create_erlc_custom_action(actor_id: int, form_data: dict) -> str:
    name = str(form_data.get("name", "")).strip()
    if not name:
        raise RuntimeError("Custom action name is required.")
    if len(name) > 64:
        raise RuntimeError("Custom action names can be up to 64 characters.")

    actions = load_erlc_custom_actions()
    if len(actions) >= MAX_ERLC_CUSTOM_ACTIONS:
        raise RuntimeError(f"You can save up to {MAX_ERLC_CUSTOM_ACTIONS} custom ERLC actions.")

    normalized_name = name.casefold()
    if any(action["name"].casefold() == normalized_name for action in actions):
        raise RuntimeError("A custom ERLC action with that name already exists.")

    timestamp = int(time.time())
    actions.append(
        {
            "id": uuid.uuid4().hex,
            "name": name,
            "steps": _parse_erlc_custom_action_steps(form_data),
            "created_by": str(actor_id),
            "created_at": timestamp,
            "updated_at": timestamp,
        }
    )
    _save_erlc_custom_actions(actions)
    return f"Created custom ERLC action '{name}'."


def delete_erlc_custom_action(action_id: str) -> str:
    actions = load_erlc_custom_actions()
    kept_actions = [action for action in actions if action["id"] != str(action_id)]
    if len(kept_actions) == len(actions):
        raise RuntimeError("Custom ERLC action was not found.")
    _save_erlc_custom_actions(kept_actions)
    return "Deleted custom ERLC action."


async def run_erlc_custom_action(bot, actor_id: int, action_id: str) -> str:
    action = next((item for item in load_erlc_custom_actions() if item["id"] == str(action_id)), None)
    if action is None:
        raise RuntimeError("Custom ERLC action was not found.")

    command_count = 0
    wait_count = 0
    for index, step in enumerate(action["steps"], start=1):
        if step["type"] == "wait":
            wait_count += 1
            await asyncio.sleep(int(step["seconds"]))
            continue

        try:
            await run_dashboard_command(bot, actor_id, "erlc command", {"command": step["command"]})
        except RuntimeError as exc:
            raise RuntimeError(f"Step {index} failed: {exc}") from exc
        command_count += 1

    return f"Ran custom ERLC action '{action['name']}' ({command_count} commands, {wait_count} waits)."


async def perform_warn(bot, actor_id: int, target_id: int, reason: str) -> str:
    actor = await get_actor_member(bot, actor_id)
    member = await get_member(bot, target_id)
    case_id = get_next_case()
    save_modlog(member.id, "Warn", reason, actor.id, case_id)
    try:
        await member.send(f"Case #{case_id}: You have been warned in {member.guild.name} for: {reason}")
    except discord.HTTPException:
        pass
    return f"Warned {member.display_name} with case #{case_id}."


async def perform_kick(bot, actor_id: int, target_id: int, reason: str) -> str:
    actor = await get_actor_member(bot, actor_id)
    member = await get_member(bot, target_id)
    case_id = get_next_case()
    try:
        await member.send(f"Case #{case_id}: You have been kicked from {member.guild.name} for: {reason}")
    except discord.HTTPException:
        pass
    await member.kick(reason=f"{reason} | Dashboard by {actor}")
    save_modlog(member.id, "Kick", reason, actor.id, case_id)
    return f"Kicked {member.display_name} with case #{case_id}."


async def perform_ban(bot, actor_id: int, target_id: int, reason: str) -> str:
    actor = await get_actor_member(bot, actor_id)
    guild = await get_target_guild(bot)
    member = guild.get_member(int(target_id))
    user = member or await bot.fetch_user(int(target_id))
    case_id = get_next_case()
    try:
        await user.send(f"Case #{case_id}: You have been banned from {guild.name} for: {reason}")
    except discord.HTTPException:
        pass
    await guild.ban(user, reason=f"{reason} | Dashboard by {actor}", delete_message_days=0)
    save_modlog(user.id, "Ban", reason, actor.id, case_id)
    return f"Banned {getattr(user, 'display_name', user.name)} with case #{case_id}."


async def perform_unban(bot, actor_id: int, target_id: int, reason: str) -> str:
    actor = await get_actor_member(bot, actor_id)
    guild = await get_target_guild(bot)
    user = await bot.fetch_user(int(target_id))
    await guild.unban(user, reason=f"{reason} | Dashboard by {actor}")
    case_id = get_next_case()
    save_modlog(user.id, "Unban", reason, actor.id, case_id)
    return f"Unbanned {user.name} with case #{case_id}."


async def perform_mute(bot, actor_id: int, target_id: int, duration_text: str, reason: str) -> str:
    actor = await get_actor_member(bot, actor_id)
    member = await get_member(bot, target_id)
    duration_seconds = parse_time(duration_text)
    if duration_seconds is None:
        raise RuntimeError("Invalid duration. Use formats like 10m, 2h, 1d, 1w.")
    await member.timeout(timedelta(seconds=duration_seconds), reason=f"{reason} | Dashboard by {actor}")
    case_id = get_next_case()
    save_modlog(member.id, "Mute", reason, actor.id, case_id)
    return f"Muted {member.display_name} for {duration_text} with case #{case_id}."


async def perform_unmute(bot, actor_id: int, target_id: int, reason: str) -> str:
    actor = await get_actor_member(bot, actor_id)
    member = await get_member(bot, target_id)
    await member.timeout(None, reason=f"{reason} | Dashboard by {actor}")
    case_id = get_next_case()
    save_modlog(member.id, "Unmute", reason, actor.id, case_id)
    return f"Removed timeout from {member.display_name} with case #{case_id}."


async def perform_infract(bot, actor_id: int, target_id: int, punishment: str, reason: str) -> str:
    actor = await get_actor_member(bot, actor_id)
    user = await resolve_user(bot, target_id)
    channel = bot.get_channel(INFRACTION_CHANNEL)
    if channel is None:
        raise RuntimeError("Infraction channel is unavailable.")

    reference_id = int(time.time())
    embed = discord.Embed(
        title="CSRP Infraction",
        description=(
            f"**User:** {user.mention}\n"
            f"**Action:** {punishment}\n"
            f"**Reason:** {reason}\n"
            f"**Reference ID:** `{reference_id}`"
        ),
        color=discord.Color.blue(),
    )
    embed.set_footer(text=f"Signed by {actor}", icon_url=actor.display_avatar.url)
    await channel.send(content=user.mention, embed=embed)

    if isinstance(user, discord.Member):
        dm_embed = discord.Embed(
            title="Infraction Notice",
            description=(
                f"You have been infracted in **{user.guild.name}**.\n\n"
                f"> **Punishment:** {punishment}\n"
                f"> **Reason:** {reason}\n"
                f"> **Reference ID:** `{reference_id}`"
            ),
            color=discord.Color.blurple(),
        )
        dm_embed.set_author(name=user.guild.name, icon_url=CSRP_ICON)
        try:
            await user.send(embed=dm_embed)
        except discord.HTTPException:
            pass

    return f"Infracted {getattr(user, 'display_name', user.name)} with reference #{reference_id}."


def get_modlogs_for_user(user_id: int) -> list[dict]:
    return get_modlogs_for_user_db(user_id)


async def clear_modlogs_for_user(target_id: int) -> str:
    clear_user_modlogs(int(target_id))
    return f"Cleared modlogs for user ID {target_id}."


async def clear_all_modlogs() -> str:
    clear_all_modlogs_data()
    return "Cleared all modlogs."


async def perform_retire(bot, actor_id: int, target_id: int) -> str:
    guild = await get_target_guild(bot)
    actor = await get_actor_member(bot, actor_id)
    member = await get_member(bot, target_id)
    settings = get_guild_settings(guild.id)

    staff_role_ids = set(settings.get("staff_roles", []))
    if not staff_role_ids:
        raise RuntimeError("Staff roles are not configured.")

    user_staff_roles = [role for role in member.roles if role.id in staff_role_ids]
    if not user_staff_roles:
        raise RuntimeError("That user does not currently have configured staff roles.")

    actor_rank = _get_member_highest_rank(actor, settings)
    target_rank = _get_member_highest_rank(member, settings)
    if not _can_manage_rank(actor_rank, target_rank):
        raise RuntimeError("You cannot retire a member with a higher saved rank than your own.")

    save_retirement(
        guild.id,
        member.id,
        {
            "previous_roles": [role.id for role in user_staff_roles],
            "highest_rank": target_rank,
            "retired_by": actor.id,
            "retired_at": int(time.time()),
        },
    )
    await member.remove_roles(*user_staff_roles, reason=f"Retired via dashboard by {actor}")
    return f"Retired {member.display_name}."


async def perform_reinstate(bot, actor_id: int, target_id: int) -> str:
    guild = await get_target_guild(bot)
    actor = await get_actor_member(bot, actor_id)
    member = await get_member(bot, target_id)
    settings = get_guild_settings(guild.id)
    retirement = get_retirement(guild.id, member.id)

    if not retirement:
        raise RuntimeError("No retirement record exists for that user.")

    highest_rank = retirement.get("highest_rank")
    actor_rank = _get_member_highest_rank(actor, settings)
    if not _can_manage_rank(actor_rank, highest_rank):
        raise RuntimeError("You cannot reinstate a member with a higher saved rank than your own.")
    if highest_rank not in DEMOTION_MAP:
        raise RuntimeError("That retirement record requires manual handling.")

    demoted_rank = DEMOTION_MAP[highest_rank]
    role_ids, warnings = _get_target_role_ids(settings, retirement, highest_rank, demoted_rank)
    if warnings:
        raise RuntimeError(" ".join(warnings))

    roles = []
    for role_id in role_ids:
        role = guild.get_role(role_id)
        if role is None:
            raise RuntimeError(f"Configured role {role_id} no longer exists.")
        roles.append(role)

    await member.add_roles(*roles, reason=f"Reinstated via dashboard by {actor}")
    remove_retirement(guild.id, member.id)
    return f"Reinstated {member.display_name} as {demoted_rank}."


async def send_partnership(bot, actor_id: int, channel_id: int, body: str) -> str:
    actor = await get_actor_member(bot, actor_id)
    channel = bot.get_channel(int(channel_id))
    if channel is None:
        raise RuntimeError("Target channel was not found.")

    guild = await get_target_guild(bot)
    embed = discord.Embed(title="Partnership", description=body, color=discord.Color.gold())
    embed.set_author(name=guild.name, icon_url=guild.icon.url if guild.icon else CSRP_ICON)
    embed.set_footer(text=f"Sent by {actor}", icon_url=actor.display_avatar.url)
    await channel.send(embed=embed)
    return f"Sent partnership embed to #{channel.name}."


def _parse_fields(raw: str) -> list[tuple[str, str, bool]]:
    fields = []
    for line in (raw or "").splitlines():
        parts = [part.strip() for part in line.split("|")]
        if len(parts) >= 2:
            fields.append((
                parts[0],
                parts[1].replace("\\n", "\n"),
                len(parts) >= 3 and parts[2].lower() in {"1", "true", "yes", "inline"},
            ))
    return fields[:25]


async def send_custom_embed(bot, actor_id: int, payload: dict) -> str:
    actor = await get_actor_member(bot, actor_id)
    channel = bot.get_channel(int(payload["channel_id"]))
    if channel is None:
        raise RuntimeError("Embed target channel was not found.")

    embed = discord.Embed(
        title=normalize_display_mentions(payload.get("title")) or None,
        description=normalize_display_mentions(payload.get("description")) or None,
        color=discord.Color(int((payload.get("color") or "2B2D31").replace("#", ""), 16)),
        url=payload.get("url") or None,
        timestamp=discord.utils.utcnow() if payload.get("timestamp") == "on" else None,
    )
    if payload.get("author_name"):
        embed.set_author(
            name=normalize_display_mentions(payload["author_name"]),
            icon_url=payload.get("author_icon_url") or None,
            url=payload.get("author_url") or None,
        )
    if payload.get("footer_text"):
        embed.set_footer(
            text=normalize_display_mentions(payload["footer_text"]),
            icon_url=payload.get("footer_icon_url") or None,
        )
    if payload.get("thumbnail_url"):
        embed.set_thumbnail(url=payload["thumbnail_url"])
    if payload.get("image_url"):
        embed.set_image(url=payload["image_url"])

    for name, value, inline in _parse_fields(payload.get("fields", "")):
        embed.add_field(
            name=normalize_display_mentions(name),
            value=normalize_display_mentions(value),
            inline=inline,
        )

    await channel.send(
        content=normalize_display_mentions(payload.get("content")) or None,
        embed=embed,
        legacy_embeds=True,
        allowed_mentions=discord.AllowedMentions.none(),
    )
    return f"Sent custom embed to #{channel.name} for {actor.display_name}."


async def blacklist_command_user(target_id: int) -> str:
    entry = f"{{userid: {int(target_id)}}}"
    lines = _load_lines(blacklisted_command)
    if entry not in lines:
        lines.append(entry)
        _save_lines(blacklisted_command, lines)
    return f"Blacklisted user ID {target_id} from ERLC commands."


async def unblacklist_command_user(target_id: int) -> str:
    entry = f"{{userid: {int(target_id)}}}"
    lines = [line for line in _load_lines(blacklisted_command) if line != entry]
    _save_lines(blacklisted_command, lines)
    return f"Removed user ID {target_id} from the ERLC command blacklist."


async def run_docker_exec(database: str, sql_command: str) -> str:
    safe_database = database.strip()
    if not re.fullmatch(r"[A-Za-z0-9_]+", safe_database):
        raise RuntimeError("Invalid database name.")

    command = [
        "sudo",
        "-n",
        "docker",
        "exec",
        "-i",
        "postgres",
        "psql",
        "-v",
        "ON_ERROR_STOP=1",
        "-U",
        "postgres",
        "-d",
        safe_database,
    ]
    result = subprocess.run(
        command,
        input=sql_command,
        capture_output=True,
        text=True,
        timeout=30,
    )
    output = result.stdout.strip() or result.stderr.strip() or "(no output)"
    if result.returncode != 0:
        raise RuntimeError(output[:4000])
    return output[:4000]


async def update_bot_status(bot, status_text: str) -> str:
    await bot.change_presence(activity=discord.Activity(type=discord.ActivityType.playing, name=status_text))
    return f"Updated bot status to '{status_text}'."


async def send_bot_message(bot, channel_id: int, content: str) -> str:
    channel = bot.get_channel(int(channel_id))
    if channel is None:
        raise RuntimeError("Target channel was not found.")
    await channel.send(content)
    return f"Sent message to #{channel.name}."


async def update_dashboard_settings(guild_id: int, form_data: dict) -> str:
    def _values(key: str) -> list[str]:
        if hasattr(form_data, "getlist"):
            listed = [str(value).strip() for value in form_data.getlist(key) if str(value).strip()]
            if listed:
                return listed
        raw_value = str(form_data.get(key, "")).strip()
        return [value.strip() for value in raw_value.split(",") if value.strip()]

    for key in [
        "staff_roles",
        "partnership_allowed_roles",
        "embed_allowed_roles",
        "retire_allowed_roles",
    ]:
        role_ids = [int(value) for value in _values(key)]
        update_guild_setting(guild_id, key, role_ids)

    for key in ["retirement_log_channel", "hostage_review_channel", "staff_feedback_channel", "partnership_log_channel"]:
        raw_value = form_data.get(key, "").strip()
        update_guild_setting(guild_id, key, int(raw_value) if raw_value else None)

    update_guild_setting(guild_id, "discord_checks_enabled", form_data.get("discord_checks_enabled") == "on")
    update_guild_setting(guild_id, "feedback_enabled", form_data.get("feedback_enabled") == "on")
    questions = [line.strip() for line in form_data.get("feedback_questions", "").splitlines() if line.strip()]
    update_guild_setting(guild_id, "feedback_questions", questions or DEFAULT_SETTINGS["feedback_questions"])

    for rank in RANK_ORDER:
        raw_value = form_data.get(f"rank::{rank}", "").strip()
        update_rank_role(guild_id, rank, int(raw_value) if raw_value else None)

    for permission_key in PERMISSION_ROLE_LABELS:
        role_ids = [int(value) for value in _values(f"permission_role::{permission_key}")]
        update_permission_role_setting(guild_id, permission_key, role_ids)

    for permission_key in PERMISSION_USER_LABELS:
        raw_value = str(form_data.get(f"permission_user::{permission_key}", "")).strip()
        parsed_user_ids = []
        for value in raw_value.replace(",", "\n").splitlines():
            value = value.strip()
            if not value:
                continue
            parsed_user_ids.append(int(value))
        update_permission_user_setting(guild_id, permission_key, parsed_user_ids)
    return "Updated bot settings."
