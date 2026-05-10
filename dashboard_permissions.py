import copy
import json
from typing import Iterable

from config import BOT_ADMINISTRATION

PERMISSIONS_FILE = "dashboard_permissions.json"

FEATURES = [
    ("moderation", "Moderation Commands"),
    ("infractions", "Infractions"),
    ("staff_management", "Retire / Reinstate"),
    ("erlc", "ERLC Controls"),
    ("partnerships", "Partnerships"),
    ("modlogs", "Modlogs"),
    ("embed_wizard", "Embed Wizard"),
    ("command_blacklist", "Command Blacklist"),
    ("docker_commands", "Docker Commands"),
    ("bot_updates", "Bot Updates"),
    ("bot_settings", "Bot Settings"),
    ("access_manager", "Access Manager"),
]

DEFAULT_PERMISSIONS = {
    "full_access_roles": list(BOT_ADMINISTRATION),
    "features": {feature_key: [] for feature_key, _ in FEATURES},
}


def load_permissions() -> dict:
    try:
        with open(PERMISSIONS_FILE, "r") as file:
            data = json.load(file)
    except (FileNotFoundError, json.JSONDecodeError):
        data = copy.deepcopy(DEFAULT_PERMISSIONS)
        save_permissions(data)
        return data

    if "full_access_roles" not in data:
        data["full_access_roles"] = copy.deepcopy(DEFAULT_PERMISSIONS["full_access_roles"])
    if "features" not in data:
        data["features"] = {}

    for feature_key, _ in FEATURES:
        data["features"].setdefault(feature_key, [])
    return data


def save_permissions(data: dict) -> None:
    with open(PERMISSIONS_FILE, "w") as file:
        json.dump(data, file, indent=4)


def update_permission(feature_key: str, role_ids: Iterable[int]) -> None:
    data = load_permissions()
    if feature_key == "full_access":
        data["full_access_roles"] = sorted({int(role_id) for role_id in role_ids})
    else:
        data["features"][feature_key] = sorted({int(role_id) for role_id in role_ids})
    save_permissions(data)


def member_has_access(member_role_ids: Iterable[int], feature_key: str | None = None) -> bool:
    data = load_permissions()
    role_ids = {int(role_id) for role_id in member_role_ids}
    if role_ids & set(data.get("full_access_roles", [])):
        return True
    if feature_key is None:
        return any(role_ids & set(feature_roles) for feature_roles in data.get("features", {}).values())
    return bool(role_ids & set(data.get("features", {}).get(feature_key, [])))
