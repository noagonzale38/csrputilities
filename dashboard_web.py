import asyncio
import os
import shutil
import subprocess
import threading
import uuid
from functools import wraps

import requests
from flask import (
    Flask,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from flask_cors import CORS

from config import BOT_ADMINISTRATION
from cogs.settings import RANK_ORDER, get_guild_settings
from dashboard_actions import (
    blacklist_command_user,
    clear_all_modlogs,
    clear_modlogs_for_user,
    collect_dashboard_stats,
    fetch_erlc_players,
    fetch_erlc_server,
    get_actor_member,
    get_modlogs_for_user,
    get_target_guild,
    perform_ban,
    perform_infract,
    perform_kick,
    perform_mute,
    perform_reinstate,
    perform_retire,
    perform_unban,
    perform_unmute,
    perform_warn,
    run_docker_exec,
    send_bot_message,
    send_custom_embed,
    send_erlc_command,
    send_partnership,
    unblacklist_command_user,
    update_bot_status,
    update_dashboard_settings,
)
from dashboard_permissions import FEATURES, load_permissions, member_has_access, update_permission
from dashboard_themes import create_theme, install_theme, list_public_themes, list_user_themes, uninstall_theme

LOG_FILE = "logs.txt"
API_KEYS_FILE = "APIKeys.txt"
INTERNAL_API_KEY = "Yj1g5xkNssijLNLQrFCJfXhWdvUGOQCZNrrmiZnBoOk0XZ8o7I1wnhZC45ZoZLG2"

app = Flask(__name__, template_folder="templates", static_folder="static")
app.secret_key = os.getenv("DASHBOARD_SECRET_KEY", "change-me-dashboard-secret")
app.config["SESSION_COOKIE_NAME"] = "csrp_dashboard_session"
CORS(app)

_bot_provider = None
_web_thread = None
_next_process = None


def _dashboard_environment_label():
    dashboard_env = os.getenv("DASHBOARD_ENV", "").strip().lower()
    return {
        "staging": "Staging",
        "development": "Development",
        "dev": "Development",
    }.get(dashboard_env, "")


def _dashboard_public_origin():
    return os.getenv("DASHBOARD_PUBLIC_ORIGIN", "http://127.0.0.1:3000").rstrip("/")


def _dashboard_url(path=""):
    if path and not path.startswith("/"):
        path = f"/{path}"
    return f"{_dashboard_public_origin()}{path}"


def attach_bot(bot):
    global _bot_provider
    _bot_provider = lambda: bot


def get_bot():
    if _bot_provider is None:
        raise RuntimeError("Dashboard bot provider has not been configured.")
    return _bot_provider()


def run_async(coro, timeout=30):
    bot = get_bot()
    future = asyncio.run_coroutine_threadsafe(coro, bot.loop)
    return future.result(timeout=timeout)


def check_server_status():
    return "up" if os.path.exists(LOG_FILE) else "down"


def get_latency():
    return f"{int(get_bot().latency * 1000)}ms"


def load_api_keys():
    if not os.path.exists(API_KEYS_FILE):
        return set()
    with open(API_KEYS_FILE, "r") as file:
        return set(line.strip() for line in file.readlines())


def save_api_key(api_key):
    with open(API_KEYS_FILE, "a") as file:
        file.write(api_key + "\n")


def generate_api_key():
    api_key = str(uuid.uuid4())
    save_api_key(api_key)
    return api_key


def extract_auth_token():
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        return auth_header.split(" ")[1]
    return None


def authenticate():
    api_key = extract_auth_token()
    return api_key in load_api_keys()


def internal_authenticate():
    return extract_auth_token() == INTERNAL_API_KEY


def _discord_redirect_uri():
    return os.getenv("DISCORD_REDIRECT_URI") or url_for("auth_callback", _external=True)


def _discord_client_id():
    return os.getenv("DISCORD_CLIENT_ID")


def _discord_client_secret():
    return os.getenv("DISCORD_CLIENT_SECRET")


def start_next_dashboard(host=None, port=None):
    global _next_process
    if _next_process and _next_process.poll() is None:
        return _next_process

    npm = shutil.which("npm.cmd") or shutil.which("npm")
    if npm is None:
        raise RuntimeError("npm was not found. Install Node.js/npm before starting the Next.js dashboard.")

    host = host or os.getenv("NEXT_DASHBOARD_HOST", "0.0.0.0")
    port = str(port or os.getenv("NEXT_DASHBOARD_PORT", "3000"))
    env = os.environ.copy()
    env.setdefault("NEXT_PUBLIC_BACKEND_ORIGIN", os.getenv("DASHBOARD_BACKEND_ORIGIN", "http://127.0.0.1:4000"))

    subprocess.run([npm, "run", "build"], cwd=os.getcwd(), env=env, check=True)
    _next_process = subprocess.Popen(
        [npm, "run", "start", "--", "-H", host, "-p", port],
        cwd=os.getcwd(),
        env=env,
    )
    return _next_process


def current_member():
    user_id = session.get("discord_user_id")
    if not user_id:
        return None
    try:
        return run_async(get_actor_member(get_bot(), int(user_id)))
    except Exception:
        return None


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("discord_user_id"):
            return redirect(url_for("login"))
        member = current_member()
        if member is None:
            session.clear()
            flash("Your Discord account is not in the configured server.", "error")
            return redirect(url_for("index"))
        return view(*args, **kwargs)

    return wrapped


def _dashboard_context():
    bot = get_bot()
    member = current_member()
    guild = run_async(get_target_guild(bot))
    stats = run_async(collect_dashboard_stats(bot))
    settings = get_guild_settings(guild.id)
    permissions = load_permissions()
    feature_access = {
        feature_key: member_has_access([role.id for role in member.roles], feature_key)
        for feature_key, _ in FEATURES
    }
    has_full_access = member_has_access([role.id for role in member.roles], None) and any(
        role.id in permissions.get("full_access_roles", []) for role in member.roles
    )

    erlc_server = {}
    erlc_players = []
    if feature_access.get("erlc"):
        try:
            erlc_server = run_async(fetch_erlc_server())
            erlc_players = run_async(fetch_erlc_players())
        except Exception:
            pass

    modlog_user_id = request.args.get("modlog_user_id", "").strip()
    modlog_results = None
    if modlog_user_id and feature_access.get("modlogs"):
        try:
            modlog_results = get_modlogs_for_user(int(modlog_user_id))
        except ValueError:
            modlog_results = []

    return {
        "member": member,
        "guild": guild,
        "stats": stats,
        "settings": settings,
        "permissions_data": permissions,
        "features": FEATURES,
        "feature_access": feature_access,
        "has_full_access": has_full_access,
        "roles": sorted(guild.roles, key=lambda role: role.position, reverse=True),
        "channels": sorted(guild.text_channels, key=lambda channel: channel.position),
        "erlc_server": erlc_server,
        "erlc_players": erlc_players[:25],
        "modlog_results": modlog_results,
        "modlog_user_id": modlog_user_id,
        "rank_order": RANK_ORDER,
        "bot_admin_roles": BOT_ADMINISTRATION,
        "dashboard_environment_label": _dashboard_environment_label(),
    }


def _role_payload(role):
    return {
        "id": str(role.id),
        "name": role.name,
        "position": role.position,
        "color": str(role.color),
    }


def _channel_payload(channel):
    return {
        "id": str(channel.id),
        "name": channel.name,
        "position": channel.position,
    }


def _selected_role_names(role_ids, role_lookup):
    return [
        role_lookup.get(int(role_id), f"Unknown role ({role_id})")
        for role_id in role_ids
        if str(role_id).strip()
    ]


def _selected_channel_name(channel_id, channel_lookup):
    if not channel_id:
        return ""
    return channel_lookup.get(int(channel_id), f"Unknown channel ({channel_id})")


def _json_safe(value):
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    return value


def _settings_payload(settings):
    payload = dict(settings)
    for key in [
        "staff_roles",
        "partnership_allowed_roles",
        "embed_allowed_roles",
        "retire_allowed_roles",
    ]:
        payload[key] = [str(role_id) for role_id in settings.get(key, [])]
    for key in ["retirement_log_channel", "staff_feedback_channel"]:
        payload[key] = str(settings.get(key)) if settings.get(key) else ""
    payload["rank_roles"] = {
        rank: str(role_id) if role_id else ""
        for rank, role_id in settings.get("rank_roles", {}).items()
    }
    return payload


def _permissions_payload(permissions):
    return {
        "full_access_roles": [str(role_id) for role_id in permissions.get("full_access_roles", [])],
        "features": {
            feature_key: [str(role_id) for role_id in role_ids]
            for feature_key, role_ids in permissions.get("features", {}).items()
        },
    }


def _json_dashboard_context():
    context = _dashboard_context()
    roles = [_role_payload(role) for role in context["roles"]]
    channels = [_channel_payload(channel) for channel in context["channels"]]
    role_lookup = {int(role["id"]): role["name"] for role in roles}
    channel_lookup = {int(channel["id"]): channel["name"] for channel in channels}
    settings = context["settings"]
    permissions = context["permissions_data"]

    readable_settings = {
        "staff_roles": _selected_role_names(settings.get("staff_roles", []), role_lookup),
        "partnership_allowed_roles": _selected_role_names(settings.get("partnership_allowed_roles", []), role_lookup),
        "embed_allowed_roles": _selected_role_names(settings.get("embed_allowed_roles", []), role_lookup),
        "retire_allowed_roles": _selected_role_names(settings.get("retire_allowed_roles", []), role_lookup),
        "retirement_log_channel": _selected_channel_name(settings.get("retirement_log_channel"), channel_lookup),
        "staff_feedback_channel": _selected_channel_name(settings.get("staff_feedback_channel"), channel_lookup),
        "rank_roles": {
            rank: (role_lookup.get(int(role_id), f"Unknown role ({role_id})") if role_id else "")
            for rank, role_id in settings.get("rank_roles", {}).items()
        },
    }

    return {
        "member": {
            "id": str(context["member"].id),
            "display_name": context["member"].display_name,
            "avatar_url": context["member"].display_avatar.url,
        },
        "guild": {
            "id": str(context["guild"].id),
            "name": context["guild"].name,
            "icon_url": context["guild"].icon.url if context["guild"].icon else None,
        },
        "stats": _json_safe(context["stats"]),
        "settings": _settings_payload(settings),
        "readable_settings": readable_settings,
        "permissions_data": _permissions_payload(permissions),
        "features": [{"key": key, "label": label} for key, label in context["features"]],
        "feature_access": context["feature_access"],
        "has_full_access": context["has_full_access"],
        "roles": roles,
        "channels": channels,
        "erlc_server": context["erlc_server"],
        "erlc_players": context["erlc_players"],
        "modlog_results": context["modlog_results"],
        "modlog_user_id": context["modlog_user_id"],
        "rank_order": context["rank_order"],
        "bot_admin_roles": [str(role_id) for role_id in context["bot_admin_roles"]],
    }


@app.route("/")
def index():
    return redirect(_dashboard_url("/"))


@app.route("/login")
def login():
    client_id = _discord_client_id()
    if not client_id or not _discord_client_secret():
        flash("Discord OAuth is not configured. Set DISCORD_CLIENT_ID and DISCORD_CLIENT_SECRET.", "error")
        return redirect(url_for("index"))

    redirect_uri = _discord_redirect_uri()
    auth_url = (
        "https://discord.com/oauth2/authorize"
        f"?client_id={client_id}"
        f"&redirect_uri={requests.utils.quote(redirect_uri, safe='')}"
        "&response_type=code&scope=identify"
    )
    return redirect(auth_url)


@app.route("/auth/callback")
def auth_callback():
    code = request.args.get("code")
    if not code:
        flash("Discord login did not return an authorization code.", "error")
        return redirect(url_for("index"))

    response = requests.post(
        "https://discord.com/api/oauth2/token",
        data={
            "client_id": _discord_client_id(),
            "client_secret": _discord_client_secret(),
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": _discord_redirect_uri(),
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=15,
    )
    if response.status_code != 200:
        flash("Discord token exchange failed.", "error")
        return redirect(url_for("index"))

    access_token = response.json().get("access_token")
    user_response = requests.get(
        "https://discord.com/api/users/@me",
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=15,
    )
    if user_response.status_code != 200:
        flash("Unable to read your Discord user profile.", "error")
        return redirect(url_for("index"))

    user = user_response.json()
    session["discord_user_id"] = int(user["id"])
    session["discord_username"] = user.get("username", "Discord User")

    if current_member() is None:
        session.clear()
        flash("Your account does not have access to the configured server.", "error")
        return redirect(_dashboard_url("/"))

    flash("Logged in through Discord.", "success")
    return redirect(_dashboard_url("/dashboard"))


@app.route("/logout")
def logout():
    session.clear()
    flash("Logged out.", "success")
    return redirect(_dashboard_url("/"))


@app.route("/dashboard")
@login_required
def dashboard():
    return redirect(_dashboard_url("/dashboard"))


@app.route("/api/session")
def api_session():
    return jsonify({
        "logged_in": bool(session.get("discord_user_id")),
        "username": session.get("discord_username"),
        "client_id": _discord_client_id(),
    })


@app.route("/api/dashboard")
@login_required
def api_dashboard():
    return jsonify(_json_dashboard_context())


@app.route("/api/themes", methods=["GET", "POST"])
@login_required
def api_themes():
    member = current_member()
    user_id = str(member.id)

    if request.method == "POST":
        payload = request.get_json(silent=True) or {}
        try:
            theme = create_theme(payload, user_id, member.display_name)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        return jsonify({"theme": theme}), 201

    return jsonify({
        "marketplace": list_public_themes(),
        "mine": list_user_themes(user_id),
    })


@app.route("/api/themes/<theme_id>/install", methods=["POST", "DELETE"])
@login_required
def api_theme_install(theme_id):
    user_id = str(current_member().id)

    if request.method == "DELETE":
        result = uninstall_theme(user_id, theme_id)
        return jsonify({"removed": bool(result), "deleted": result == "deleted", "mine": list_user_themes(user_id)})

    theme = install_theme(user_id, theme_id)
    if theme is None:
        return jsonify({"error": "Theme not found."}), 404
    return jsonify({"theme": theme, "mine": list_user_themes(user_id)})


@app.route("/actions/<action>", methods=["POST"])
@login_required
def dashboard_action(action):
    member = current_member()
    bot = get_bot()
    actor_id = member.id

    handlers = {
        "warn": ("moderation", lambda: run_async(perform_warn(bot, actor_id, int(request.form["target_id"]), request.form["reason"]))),
        "kick": ("moderation", lambda: run_async(perform_kick(bot, actor_id, int(request.form["target_id"]), request.form["reason"]))),
        "ban": ("moderation", lambda: run_async(perform_ban(bot, actor_id, int(request.form["target_id"]), request.form["reason"]))),
        "unban": ("moderation", lambda: run_async(perform_unban(bot, actor_id, int(request.form["target_id"]), request.form["reason"]))),
        "mute": ("moderation", lambda: run_async(perform_mute(bot, actor_id, int(request.form["target_id"]), request.form["duration"], request.form["reason"]))),
        "unmute": ("moderation", lambda: run_async(perform_unmute(bot, actor_id, int(request.form["target_id"]), request.form["reason"]))),
        "infract": ("infractions", lambda: run_async(perform_infract(bot, actor_id, int(request.form["target_id"]), request.form["punishment"], request.form["reason"]))),
        "retire": ("staff_management", lambda: run_async(perform_retire(bot, actor_id, int(request.form["target_id"])))),
        "reinstate": ("staff_management", lambda: run_async(perform_reinstate(bot, actor_id, int(request.form["target_id"])))),
        "erlc_command": ("erlc", lambda: run_async(send_erlc_command(request.form["command"]))),
        "partnership": ("partnerships", lambda: run_async(send_partnership(bot, actor_id, int(request.form["channel_id"]), request.form["body"]))),
        "modlogs_clear_user": ("modlogs", lambda: run_async(clear_modlogs_for_user(int(request.form["target_id"])))),
        "modlogs_clear_all": ("modlogs", lambda: run_async(clear_all_modlogs())),
        "embed_send": ("embed_wizard", lambda: run_async(send_custom_embed(bot, actor_id, dict(request.form)))),
        "blacklist_add": ("command_blacklist", lambda: run_async(blacklist_command_user(int(request.form["target_id"])))),
        "blacklist_remove": ("command_blacklist", lambda: run_async(unblacklist_command_user(int(request.form["target_id"])))),
        "docker_exec": ("docker_commands", lambda: run_async(run_docker_exec(request.form["database"], request.form["command"]))),
        "bot_status": ("bot_updates", lambda: run_async(update_bot_status(bot, request.form["status_text"]))),
        "bot_message": ("bot_updates", lambda: run_async(send_bot_message(bot, int(request.form["channel_id"]), request.form["content"]))),
        "settings_save": ("bot_settings", lambda: run_async(update_dashboard_settings(run_async(get_target_guild(bot)).id, request.form))),
        "access_save": ("access_manager", _save_access_assignments),
    }

    if action not in handlers:
        flash("Unknown dashboard action.", "error")
        return redirect(url_for("dashboard"))

    feature_key, handler = handlers[action]
    if not member_has_access([role.id for role in member.roles], feature_key):
        flash("You do not have access to that dashboard feature.", "error")
        return redirect(url_for("dashboard"))

    try:
        result = handler()
        if action == "docker_exec":
            flash(result[:500], "success")
        else:
            flash(result, "success")
    except Exception as exc:
        flash(str(exc), "error")
    return redirect(url_for("dashboard", modlog_user_id=request.args.get("modlog_user_id", "")))


def _save_access_assignments():
    update_permission("full_access", request.form.getlist("full_access_roles"))
    for feature_key, _ in FEATURES:
        update_permission(feature_key, request.form.getlist(f"feature::{feature_key}"))
    return "Updated dashboard access rules."


@app.route("/v1/generateAPI", methods=["GET"])
def generate_key():
    if not internal_authenticate():
        return jsonify({"error": "Unauthorized"}), 401
    api_key = generate_api_key()
    return jsonify({"api_key": api_key}), 200


@app.route("/v1/logs", methods=["POST", "GET"])
def handle_logs():
    if not authenticate():
        return jsonify({"error": "Unauthorized"}), 401

    if request.method == "POST":
        log_message = request.form.get("log")
        if log_message:
            with open(LOG_FILE, "a") as file:
                file.write(log_message + "\n")
            return jsonify({"message": "Log received"}), 200
        return jsonify({"error": "No log data"}), 400

    try:
        with open(LOG_FILE, "r") as file:
            logs = file.readlines()
        return jsonify({"logs": logs}), 200
    except FileNotFoundError:
        return jsonify({"error": "Log file not found"}), 404


@app.route("/v1/uptime", methods=["GET"])
def get_uptime():
    if not authenticate():
        return jsonify({"error": "Unauthorized"}), 401
    return jsonify({"uptime": check_server_status()}), 200


@app.route("/v1/latency", methods=["GET"])
def get_server_latency():
    if not authenticate():
        return jsonify({"error": "Unauthorized"}), 401
    return jsonify({"latency": get_latency()}), 200


def start_web_app(bot, host="0.0.0.0", port=4000, start_next=True):
    global _web_thread
    attach_bot(bot)

    if start_next:
        start_next_dashboard()

    if _web_thread and _web_thread.is_alive():
        return _web_thread

    def _run():
        app.run(host=host, port=port, debug=False, use_reloader=False)

    _web_thread = threading.Thread(target=_run, name="dashboard-web", daemon=True)
    _web_thread.start()
    return _web_thread
