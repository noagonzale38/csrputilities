import os
import json
from pathlib import Path
from dotenv import load_dotenv
from discord.ext import commands

from cogs.settings import get_permission_role_ids, get_permission_user_ids

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(dotenv_path=BASE_DIR / ".env")

TOKEN = os.getenv("BOT_TOKEN")
SERVER_KEY = os.getenv("SERVER_KEY")
TEST_SERVER_KEY = os.getenv("TEST_SERVER_KEY")
SENTRY_API_TOKEN = os.getenv("SENTRY_API_TOKEN")
SENTRY_DSN = os.getenv("SENTRY_DSN")
SENTRY_API_KEY = os.getenv("SENTRY_API_KEY")
LOG_SERVER_AUTH = os.getenv("LOG_SERVER_AUTH")
API_GENERATE_AUTH = os.getenv("API_GENERATE_AUTH")
COOKIE_API_AUTH = os.getenv("COOKIE_API_AUTH")
ERM_API_AUTH = os.getenv("ERM_API_AUTH")
IS_TESTING = os.getenv("IS_TESTING", "false").lower() == "true"
BOT_OWNER_ID = 1213915425369227334
RESTRICTION_BYPASS_USER_IDS = {BOT_OWNER_ID, 856914957764526111}

AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID")
AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY")
S3_BUCKET_NAME = os.getenv("S3_BUCKET_NAME")
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")

SENTRY_ORG = "csrp-utilities"
SENTRY_PROJECT = "csrp-utilities"

IA_ROLE_ID = 1137117556348567614
BOT_ADMINISTRATION = 1340433106217205903, 968847690286903318, 985228543191548004, 1374173264330625155
MODERATION_ROLE_IDS = [
    1137117556348567614, 1131166127964291172, 1157648329619021844, 985228543191548004,
    968847690286903318, 1331830954972549153, 1320942467880583259, 1337512102977605663,
    1337511934769234051
]

CHANNEL_ID = "1317982841602183269"
BAN_CHANNEL = "1317889537363410984"

AUTHORIZED_USERS = {
    1213915425369227334, 1218053009834246156, 736978544869113927, 826930759016120331,
    1109142957866619013, 793162371702194207, 778630075071332372, 708643165514498068
}

SUPPORT_USERS = {
    1213915425369227334, 1218053009834246156, 736978544869113927, 826930759016120331,
    1220440120658890792, 1109142957866619013, 614895781832556585, 946398082462011403,
    1224798895129890957, 654110914311618561, 946398082462011403, 1220440120658890792
}

AUTHORIZED_ROLE_IDS = [
    1137117556348567614, 1131166127964291172, 1157648329619021844,
    985228543191548004, 968847690286903318, 1331830954972549153
]

ADMIN_PRIVILEGE_ROLE_IDS = [
    1400593708965040280, 1131166127964291172, 1137759608061050992, 1157648329619021844,
    985228543191548004, 968847690286903318, 1137759510623174778
]

PERMITTED_SESSION_ROLE_IDS = [
    1131166127964291172, 1157648329619021844, 985228543191548004, 968847690286903318,
    1321363819519283220
]

NOAH_DIR = [1408307735329767585, 985228543191548004]

SALES_ROLE_IDS = [
    1137117556348567614, 1137129271769436340, 1157648329619021844,
    1131166127964291172, 985228543191548004
]

SUPPORT_IDS = (
    1341282970966954024, 1323534294240727131, 1331830954972549153, 1323534294257500161,
    1374173264330625155, 1362304603445657611, 1432238694626230283, 946398082462011403,
    1220440120658890792, 1458893408151277844
)

DEV_ROLE_IDS = 1340433106217205903, 1321363819519283220, 1323534294257500162, 1374173264330625155

ALLOWED_TI_IDS = [1131912432957263994, 1137129271769436340]

ROLE_TRAINING_INSTRUCTOR = 1131912432957263994
ROLE_TRIAL_MODERATOR = 1142431349622452334
ROLE_PHASE_3 = 1359548328747991255
ROLE_JUNIOR_MODERATOR = 1307101011126648902
ROLE_MODERATOR = 981595679505940490
ROLE_STAFF_TEAM = 968852438922715176

LOGGING_CHANNEL_ID = 1323536942784188429
SESSION_CHANNEL = 1159839282635227286
ERRORS_CHANNEL = 1323534295108812817
STAFF_FEEDBACK_CHANNEL = 1168268985918300250
INFRACTION_CHANNEL = 1160348145989988535
APPEALS_CHANNEL_ID = 1328489653539438756
MOD_CHANNEL_ID = 1216491894390001674
MOD_ROLE_ID = 1340104462680719431
REPORT_GUILD_ID = 965829463512330260

LOG_FILE = "log.txt"
BAN_LOG_FILE = "BanLogs.txt"
modlogs_file = "modlogs.json"
blacklisted_command = "blacklisted_users.txt"
casefile = r"casefile.txt"
report_blacklists = "report_blacklists.txt"
feedback_blacklists = "feedback_blacklists.txt"
afk_file = "afk.json"
active_hits = "hits.json"
testing_users_file = "testing_users.json"

API_URL = "https://api.erlc.gg/v1"
LOG_SERVER_URL = "https://internal-logs-utilities.officialcaliforniastateroleplay.com/v1/logs"
LATENCY_API_URL = "https://internal-logs-utilities.officialcaliforniastateroleplay.com/v1/latency"

HEADERS = {
    "Content-Type": "application/json",
    "Server-Key": SERVER_KEY,
}

KEY_HEADERS = {"Server-Key": SERVER_KEY}


# --- PRC API key switching (dev only) ---
# HEADERS / KEY_HEADERS are shared dicts; set_api_mode swaps the key in place
# so every module that imported them picks up the change immediately.

_api_mode = "prod"

def get_api_mode():
    return _api_mode

def get_server_key():
    return TEST_SERVER_KEY if _api_mode == "test" else SERVER_KEY

def set_api_mode(mode):
    global _api_mode
    if mode not in ("prod", "test"):
        raise ValueError("API mode must be 'prod' or 'test'.")
    if mode == "test" and not TEST_SERVER_KEY:
        raise ValueError("TEST_SERVER_KEY is not set in .env.")
    _api_mode = mode
    key = TEST_SERVER_KEY if mode == "test" else SERVER_KEY
    HEADERS["Server-Key"] = key
    KEY_HEADERS["Server-Key"] = key

WARNING_1_ROLE_ID = 1191743191163080715
WARNING_2_ROLE_ID = 1191743212990251098
WARNING_3_ROLE_ID = 1191743229624856666
STRIKE_1_ROLE_ID = 983189423413952512
STRIKE_2_ROLE_ID = 983189418129113188
STRIKE_3_ROLE_ID = 983189765706899517
SUSPENDED_ROLE_ID = 968852121510375494

BLACKLIST_ROLE_ID = 1357804674303918312
ALLOWED_ROLE_ID = 1318929689896554558
SECRET_USER_ID = 1213915425369227334
CSRPUTILS_DEVS = 1213915425369227334, 614895781832556585

DEV_ROLE_ID_ADMIN = 1340433106217205903


# --- Permission check decorators ---

def _role_check(role_ids):
    async def predicate(ctx):
        if not ctx.guild:
            raise commands.NoPrivateMessage()
        user_role_ids = {role.id for role in ctx.author.roles}
        if user_role_ids & set(role_ids):
            return True
        raise commands.CheckFailure("You are not permitted to use this command")
    return commands.check(predicate)


def _configured_permission_check(permission_key, *, allow_roles=True, allow_users=True):
    async def predicate(ctx):
        if not ctx.guild:
            raise commands.NoPrivateMessage()

        if allow_users:
            configured_user_ids = set(get_permission_user_ids(ctx.guild.id, permission_key))
            if ctx.author.id in configured_user_ids:
                return True

        if allow_roles:
            configured_role_ids = set(get_permission_role_ids(ctx.guild.id, permission_key))
            user_role_ids = {role.id for role in ctx.author.roles}
            if user_role_ids & configured_role_ids:
                return True

        raise commands.CheckFailure("You are not permitted to use this command")
    return commands.check(predicate)


def _configured_role_check(permission_key):
    return _configured_permission_check(permission_key, allow_roles=True, allow_users=True)


def _configured_user_check(permission_key):
    return _configured_permission_check(permission_key, allow_roles=False, allow_users=True)


def is_moderation():
    return _configured_role_check("moderation")

def is_noah_or_directive():
    return _configured_role_check("noah_or_directive")

def is_sales_authorized():
    return _configured_role_check("sales_authorized")

def is_bot_dev():
    return _configured_role_check("bot_dev")

def is_training_instructor():
    return _configured_role_check("training_instructor")

def is_role_authorized():
    return _configured_role_check("role_authorized")

def is_session_permitted():
    return _configured_role_check("session_permitted")

def is_support():
    return _configured_role_check("support")

def is_bot_staff():
    return _configured_role_check("bot_staff")

def is_authorized():
    return _configured_user_check("authorized")

def is_authorized_user_or_role(ctx):
    if ctx.author.id in set(get_permission_user_ids(ctx.guild.id, "support")):
        return True
    if ctx.author.id in set(get_permission_user_ids(ctx.guild.id, "role_authorized")):
        return True
    authorized_role_ids = set(get_permission_role_ids(ctx.guild.id, "role_authorized"))
    for role in ctx.author.roles:
        if role.id in authorized_role_ids:
            return True
    raise commands.CheckFailure("You don't have permission to use this command.")


# --- Testing mode helpers ---

def load_testing_users():
    try:
        with open(testing_users_file, "r") as f:
            return set(json.load(f))
    except (FileNotFoundError, json.JSONDecodeError):
        return set()

def save_testing_users(user_ids):
    with open(testing_users_file, "w") as f:
        json.dump(list(user_ids), f)

def is_testing_allowed(user_id):
    if not IS_TESTING:
        return True
    if user_id == BOT_OWNER_ID:
        return True
    return user_id in load_testing_users()
