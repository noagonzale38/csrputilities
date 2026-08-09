import discord
from discord.ext import commands
from discord import app_commands
import json
import copy
from pathlib import Path

from cogs.helpers import (
    BLANK_COLOR, CSRP_ICON, CHECK, CROSS,
    brand_footer, success_embed, error_embed,
)

SETTINGS_FILE = Path(__file__).resolve().parent.parent / "guild_settings.json"
SETTINGS_ALLOWED_MENTIONS = discord.AllowedMentions.none()


def _display_role(guild: discord.Guild, role_id: int | None) -> str:
    if not role_id:
        return "`Not set`"
    role = guild.get_role(int(role_id))
    return role.mention if role else f"`Deleted role ({role_id})`"


def _display_role_list(guild: discord.Guild, role_ids: list[int]) -> str:
    if not role_ids:
        return "`Not set`"
    return ", ".join(_display_role(guild, role_id) for role_id in role_ids)

DEFAULT_PERMISSION_ROLE_SETTINGS = {
    "moderation": [
        1137117556348567614,
        1131166127964291172,
        1157648329619021844,
        985228543191548004,
        968847690286903318,
        1331830954972549153,
        1320942467880583259,
        1337512102977605663,
        1337511934769234051,
    ],
    "noah_or_directive": [1408307735329767585, 985228543191548004],
    "sales_authorized": [
        1137117556348567614,
        1137129271769436340,
        1157648329619021844,
        1131166127964291172,
        985228543191548004,
    ],
    "bot_dev": [1340433106217205903, 968847690286903318, 985228543191548004, 1374173264330625155],
    "training_instructor": [1131912432957263994, 1137129271769436340],
    "role_authorized": [
        1137117556348567614,
        1131166127964291172,
        1157648329619021844,
        985228543191548004,
        968847690286903318,
        1331830954972549153,
    ],
    "session_permitted": [1131166127964291172, 1157648329619021844, 985228543191548004, 968847690286903318, 1321363819519283220],
    "support": [1341282970966954024, 1323534294240727131, 1331830954972549153, 1323534294257500161, 1374173264330625155, 1362304603445657611, 1432238694626230283, 946398082462011403, 1220440120658890792, 1458893408151277844],
    "bot_staff": [1340433106217205903, 1321363819519283220, 1323534294257500162, 1374173264330625155],
}

DEFAULT_PERMISSION_USER_SETTINGS = {
    "moderation": [],
    "noah_or_directive": [],
    "sales_authorized": [],
    "bot_dev": [],
    "training_instructor": [],
    "role_authorized": [],
    "session_permitted": [],
    "authorized": [
        1213915425369227334,
        1218053009834246156,
        736978544869113927,
        826930759016120331,
        1109142957866619013,
        793162371702194207,
        778630075071332372,
        708643165514498068,
    ],
    "support": [
        1213915425369227334,
        1218053009834246156,
        736978544869113927,
        826930759016120331,
        1220440120658890792,
        1109142957866619013,
        614895781832556585,
        946398082462011403,
        1224798895129890957,
        654110914311618561,
    ],
    "bot_staff": [],
}

PERMISSION_ROLE_LABELS = {
    "moderation": "Moderation",
    "noah_or_directive": "Noah / Directive",
    "sales_authorized": "Sales",
    "bot_dev": "Bot Developers",
    "training_instructor": "Training Instructors",
    "role_authorized": "Authorized Roles",
    "session_permitted": "Session Permitted",
    "support": "Support Roles",
    "bot_staff": "Bot Staff",
}

PERMISSION_USER_LABELS = {
    "moderation": "Moderation Users",
    "noah_or_directive": "Noah / Directive Users",
    "sales_authorized": "Sales Users",
    "bot_dev": "Bot Developer Users",
    "training_instructor": "Training Instructor Users",
    "role_authorized": "Authorized Role Bypass Users",
    "session_permitted": "Session Permitted Users",
    "authorized": "Authorized Users",
    "support": "Support Users",
    "bot_staff": "Bot Staff Users",
}

DEFAULT_SETTINGS = {
    "staff_roles": [],
    "retirement_log_channel": None,
    "hostage_review_channel": None,
    "hostage_sticky_message_id": None,
    "partnership_sticky_message_id": None,
    "discord_checks_enabled": True,
    "feedback_enabled": False,
    "feedback_questions": ["Why did you decide to leave?"],
    "staff_feedback_channel": None,
    "staff_feedback_sticky_message_id": None,
    "partnership_log_channel": None,
    "partnership_allowed_roles": [],
    "embed_allowed_roles": [],
    "retire_allowed_roles": [],
    "rank_roles": {
        "Senior Management": None,
        "Management": None,
        "Internal Affairs Supervisor": None,
        "Internal Affairs": None,
        "Trial Internal Affairs": None,
        "Senior Admin": None,
        "Admin": None,
        "Junior Admin": None,
        "Senior Moderator": None,
        "Moderator": None,
    },
    "permission_roles": copy.deepcopy(DEFAULT_PERMISSION_ROLE_SETTINGS),
    "permission_users": copy.deepcopy(DEFAULT_PERMISSION_USER_SETTINGS),
}

RANK_ORDER = list(DEFAULT_SETTINGS["rank_roles"].keys())


def _merge_defaults(target: dict, defaults: dict) -> bool:
    changed = False
    for key, value in defaults.items():
        if key not in target:
            target[key] = copy.deepcopy(value)
            changed = True
            continue
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            changed = _merge_defaults(target[key], value) or changed
    return changed


def load_settings() -> dict:
    try:
        with open(SETTINGS_FILE, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_settings(data: dict):
    with open(SETTINGS_FILE, "w") as f:
        json.dump(data, f, indent=4)


def get_guild_settings(guild_id: int) -> dict:
    data = load_settings()
    key = str(guild_id)
    if key not in data:
        data[key] = copy.deepcopy(DEFAULT_SETTINGS)
        save_settings(data)
    settings = data[key]
    if _merge_defaults(settings, DEFAULT_SETTINGS):
        save_settings(data)
    return settings


def update_guild_setting(guild_id: int, key: str, value):
    data = load_settings()
    gkey = str(guild_id)
    if gkey not in data:
        data[gkey] = copy.deepcopy(DEFAULT_SETTINGS)
    data[gkey][key] = value
    save_settings(data)


def update_rank_role(guild_id: int, rank_name: str, role_id):
    data = load_settings()
    gkey = str(guild_id)
    if gkey not in data:
        data[gkey] = copy.deepcopy(DEFAULT_SETTINGS)
    if "rank_roles" not in data[gkey]:
        data[gkey]["rank_roles"] = copy.deepcopy(DEFAULT_SETTINGS["rank_roles"])
    data[gkey]["rank_roles"][rank_name] = role_id
    save_settings(data)


def has_setting_permission(guild_id: int, setting_key: str, member: discord.Member) -> bool:
    settings = get_guild_settings(guild_id)
    allowed = settings.get(setting_key, [])
    if not allowed:
        return False
    member_role_ids = {r.id for r in member.roles}
    return bool(member_role_ids & set(allowed))


def get_permission_role_ids(guild_id: int, permission_key: str) -> list[int]:
    settings = get_guild_settings(guild_id)
    role_ids = settings.get("permission_roles", {}).get(permission_key, [])
    return [int(role_id) for role_id in role_ids if str(role_id).strip()]


def get_permission_user_ids(guild_id: int, permission_key: str) -> list[int]:
    settings = get_guild_settings(guild_id)
    user_ids = settings.get("permission_users", {}).get(permission_key, [])
    return [int(user_id) for user_id in user_ids if str(user_id).strip()]


def update_permission_role_setting(guild_id: int, permission_key: str, role_ids: list[int]):
    data = load_settings()
    gkey = str(guild_id)
    if gkey not in data:
        data[gkey] = copy.deepcopy(DEFAULT_SETTINGS)
    if "permission_roles" not in data[gkey]:
        data[gkey]["permission_roles"] = copy.deepcopy(DEFAULT_PERMISSION_ROLE_SETTINGS)
    data[gkey]["permission_roles"][permission_key] = sorted({int(role_id) for role_id in role_ids})
    save_settings(data)


def update_permission_user_setting(guild_id: int, permission_key: str, user_ids: list[int]):
    data = load_settings()
    gkey = str(guild_id)
    if gkey not in data:
        data[gkey] = copy.deepcopy(DEFAULT_SETTINGS)
    if "permission_users" not in data[gkey]:
        data[gkey]["permission_users"] = copy.deepcopy(DEFAULT_PERMISSION_USER_SETTINGS)
    data[gkey]["permission_users"][permission_key] = sorted({int(user_id) for user_id in user_ids})
    save_settings(data)


def member_has_permission(member: discord.Member, *, role_keys: list[str] | None = None, user_keys: list[str] | None = None) -> bool:
    settings = get_guild_settings(member.guild.id)
    if user_keys:
        configured_users = settings.get("permission_users", {})
        if any(member.id in {int(user_id) for user_id in configured_users.get(user_key, [])} for user_key in user_keys):
            return True
    if role_keys:
        member_role_ids = {role.id for role in member.roles}
        configured_roles = settings.get("permission_roles", {})
        if any(member_role_ids & {int(role_id) for role_id in configured_roles.get(role_key, [])} for role_key in role_keys):
            return True
    return False


def get_member_highest_rank(member: discord.Member) -> str | None:
    settings = get_guild_settings(member.guild.id)
    role_to_rank = {
        int(role_id): rank
        for rank, role_id in settings.get("rank_roles", {}).items()
        if role_id is not None
    }

    highest_rank = None
    highest_rank_index = len(RANK_ORDER)
    for role in member.roles:
        rank = role_to_rank.get(role.id)
        if rank is None:
            continue
        idx = RANK_ORDER.index(rank)
        if idx < highest_rank_index:
            highest_rank = rank
            highest_rank_index = idx

    return highest_rank


def member_has_rank_or_higher(member: discord.Member, minimum_rank: str) -> bool:
    if minimum_rank not in RANK_ORDER:
        return False

    highest_rank = get_member_highest_rank(member)
    if highest_rank not in RANK_ORDER:
        return False

    return RANK_ORDER.index(highest_rank) <= RANK_ORDER.index(minimum_rank)


def dashboard_embed(guild: discord.Guild) -> discord.Embed:
    settings = get_guild_settings(guild.id)

    staff = _display_role_list(guild, settings.get("staff_roles", []))
    log_ch = f"<#{settings['retirement_log_channel']}>" if settings.get("retirement_log_channel") else "`Not set`"
    hostage_review_ch = f"<#{settings['hostage_review_channel']}>" if settings.get("hostage_review_channel") else "`Not set`"
    fb_ch = f"<#{settings['staff_feedback_channel']}>" if settings.get("staff_feedback_channel") else "`Not set`"
    partner_log_ch = f"<#{settings['partnership_log_channel']}>" if settings.get("partnership_log_channel") else "`Not set`"
    discord_checks_on = f"{CHECK} Enabled" if settings.get("discord_checks_enabled", True) else f"{CROSS} Disabled"
    fb_on = f"{CHECK} Enabled" if settings.get("feedback_enabled") else f"{CROSS} Disabled"
    questions = settings.get("feedback_questions", [])
    q_text = "\n".join(f"> `{i + 1}.` {q}" for i, q in enumerate(questions)) or "> None"
    partner = _display_role_list(guild, settings.get("partnership_allowed_roles", []))
    embed_roles = _display_role_list(guild, settings.get("embed_allowed_roles", []))
    retire = _display_role_list(guild, settings.get("retire_allowed_roles", []))

    rank_roles = settings.get("rank_roles", {})
    rank_lines = []
    for rank in RANK_ORDER:
        rid = rank_roles.get(rank)
        rank_lines.append(f"> **{rank}:** {_display_role(guild, rid)}")
    rank_text = "\n".join(rank_lines)

    desc = (
        f"**Staff Roles:** {staff}\n"
        f"**Retirement Log Channel:** {log_ch}\n"
        f"**Hostage Review Channel:** {hostage_review_ch}\n"
        f"**Staff Feedback Channel:** {fb_ch}\n"
        f"**Partnership Log Channel:** {partner_log_ch}\n\n"
        f"**Discord Checks:** {discord_checks_on}\n"
        f"**Leave Feedback:** {fb_on}\n"
        f"**Questions:**\n{q_text}\n\n"
        f"**Partnership Permissions:** {partner}\n"
        f"**Embed Creation Permissions:** {embed_roles}\n"
        f"**Retire/Reinstate/Demote Permissions:** {retire}\n\n"
        f"**Rank Roles:**\n{rank_text}\n\n"
        f"**Command Permission Checks:** Configure these from the Permission Checks menu."
    )

    embed = discord.Embed(title="Server Settings", description=desc, color=BLANK_COLOR)
    embed.set_author(name="CSRP Utilities", icon_url=CSRP_ICON)
    brand_footer(embed)
    return embed


async def send_settings_dashboard(destination, guild: discord.Guild, view: discord.ui.View):
    await destination.send(
        embed=dashboard_embed(guild),
        view=view,
        allowed_mentions=SETTINGS_ALLOWED_MENTIONS,
    )


async def edit_settings_dashboard(response, guild: discord.Guild, view: discord.ui.View):
    await response.edit_message(
        embed=dashboard_embed(guild),
        view=view,
        allowed_mentions=SETTINGS_ALLOWED_MENTIONS,
    )


async def refresh_settings_dashboard(message: discord.Message, guild: discord.Guild, view: discord.ui.View):
    await message.edit(
        embed=dashboard_embed(guild),
        view=view,
        allowed_mentions=SETTINGS_ALLOWED_MENTIONS,
    )


class DashboardView(discord.ui.View):
    def __init__(self, guild: discord.Guild, author: discord.Member):
        super().__init__(timeout=300)
        self.guild = guild
        self.author = author

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author.id:
            await interaction.response.send_message("You cannot use this.", ephemeral=True)
            return False
        return True

    @discord.ui.select(
        placeholder="Choose a setting to configure...",
        options=[
            discord.SelectOption(label="Staff Roles", value="staff_roles", description="Roles removed on retirement"),
            discord.SelectOption(label="Retirement Log Channel", value="retirement_log_channel", description="Where retirement/reinstatement logs go"),
            discord.SelectOption(label="Hostage Review Channel", value="hostage_review_channel", description="Where hostage requests are reviewed"),
            discord.SelectOption(label="Staff Feedback Channel", value="staff_feedback_channel", description="Where staff feedback is posted"),
            discord.SelectOption(label="Partnership Log Channel", value="partnership_log_channel", description="Where partnership activity is logged"),
            discord.SelectOption(label="Discord Checks Toggle", value="discord_checks_enabled", description="Toggle the automated Discord check loop"),
            discord.SelectOption(label="Leave Feedback Toggle", value="feedback_enabled", description="Toggle leave feedback DMs"),
            discord.SelectOption(label="Leave Feedback Questions", value="feedback_questions", description="Edit the leave feedback questions"),
            discord.SelectOption(label="Partnership Permissions", value="partnership_allowed_roles", description="Who can use /partnership"),
            discord.SelectOption(label="Embed Creation Permissions", value="embed_allowed_roles", description="Who can use /embed create"),
            discord.SelectOption(label="Retire/Reinstate/Demote Permissions", value="retire_allowed_roles", description="Who can use /retire, /reinstate, and /demote"),
            discord.SelectOption(label="Rank Role Mapping", value="rank_roles", description="Map ranks to Discord roles"),
            discord.SelectOption(label="Permission Checks", value="permission_checks", description="Configure role/user-based command permissions"),
        ],
    )
    async def select_setting(self, interaction: discord.Interaction, select: discord.ui.Select):
        choice = select.values[0]

        if choice in ("staff_roles", "partnership_allowed_roles", "embed_allowed_roles", "retire_allowed_roles"):
            labels = {
                "staff_roles": "Staff Roles",
                "partnership_allowed_roles": "Partnership Permissions",
                "embed_allowed_roles": "Embed Creation Permissions",
                "retire_allowed_roles": "Retire/Reinstate/Demote Permissions",
            }
            descs = {
                "staff_roles": "Select all roles considered **staff**. These are removed when a user is retired.",
                "partnership_allowed_roles": "Select the roles allowed to use the **/partnership** command.",
                "embed_allowed_roles": "Select the roles allowed to use the **/embed create** command.",
                "retire_allowed_roles": "Select the roles allowed to use **/retire**, **/reinstate**, and **/demote**.",
            }
            view = RoleConfigView(self.guild, self.author, choice, labels[choice])
            embed = discord.Embed(title=f"Configure: {labels[choice]}", description=descs[choice], color=BLANK_COLOR)
            brand_footer(embed)
            await interaction.response.edit_message(embed=embed, view=view)

        elif choice in ("retirement_log_channel", "hostage_review_channel", "staff_feedback_channel", "partnership_log_channel"):
            labels = {
                "retirement_log_channel": "Retirement Log Channel",
                "hostage_review_channel": "Hostage Review Channel",
                "staff_feedback_channel": "Staff Feedback Channel",
                "partnership_log_channel": "Partnership Log Channel",
            }
            view = ChannelConfigView(self.guild, self.author, choice, labels[choice])
            embed = discord.Embed(title=f"Configure: {labels[choice]}", description="Select the channel below.", color=BLANK_COLOR)
            brand_footer(embed)
            await interaction.response.edit_message(embed=embed, view=view)

        elif choice in ("feedback_enabled", "discord_checks_enabled"):
            settings = get_guild_settings(self.guild.id)
            toggle_key = choice
            current = settings.get(toggle_key, False if toggle_key == "feedback_enabled" else True)
            view = ToggleView(self.guild, self.author, toggle_key)
            status = f"{CHECK} Enabled" if current else f"{CROSS} Disabled"
            title = "Configure: Leave Feedback" if toggle_key == "feedback_enabled" else "Configure: Discord Checks"
            description = (
                f"Currently: **{status}**\n\nWhen enabled, users who leave the server will be DMed feedback questions."
                if toggle_key == "feedback_enabled"
                else f"Currently: **{status}**\n\nWhen enabled, the automated Discord check loop will continue running for this server."
            )
            embed = discord.Embed(
                title=title,
                description=description,
                color=BLANK_COLOR,
            )
            brand_footer(embed)
            await interaction.response.edit_message(embed=embed, view=view)

        elif choice == "feedback_questions":
            settings = get_guild_settings(self.guild.id)
            questions = settings.get("feedback_questions", [])
            q_text = "\n".join(f"`{i + 1}.` {q}" for i, q in enumerate(questions)) or "None"
            view = QuestionsView(self.guild, self.author)
            embed = discord.Embed(
                title="Configure: Leave Feedback Questions",
                description=f"Current questions:\n{q_text}\n\nClick **Edit** to modify (one question per line).",
                color=BLANK_COLOR,
            )
            brand_footer(embed)
            await interaction.response.edit_message(embed=embed, view=view)

        elif choice == "rank_roles":
            view = RankRolesMenuView(self.guild, self.author)
            await interaction.response.edit_message(embed=view.get_embed(), view=view)
        elif choice == "permission_checks":
            view = PermissionConfigMenuView(self.guild, self.author)
            await interaction.response.edit_message(embed=view.get_embed(), view=view)


class PermissionConfigMenuView(discord.ui.View):
    def __init__(self, guild, author):
        super().__init__(timeout=300)
        self.guild = guild
        self.author = author

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author.id:
            await interaction.response.send_message("You cannot use this.", ephemeral=True)
            return False
        return True

    def get_embed(self):
        settings = get_guild_settings(self.guild.id)
        role_lines = []
        for key, label in PERMISSION_ROLE_LABELS.items():
            role_count = len(settings.get("permission_roles", {}).get(key, []))
            role_lines.append(f"> **{label}:** `{role_count}` role(s)")
        user_lines = []
        for key, label in PERMISSION_USER_LABELS.items():
            user_count = len(settings.get("permission_users", {}).get(key, []))
            user_lines.append(f"> **{label}:** `{user_count}` user(s)")
        embed = discord.Embed(
            title="Configure: Permission Checks",
            description=(
                "Select a permission rule below to edit who can pass that check.\n\n"
                "**Role-based checks**\n"
                + "\n".join(role_lines)
                + "\n\n**User-based checks**\n"
                + "\n".join(user_lines)
            ),
            color=BLANK_COLOR,
        )
        brand_footer(embed)
        return embed

    @discord.ui.select(
        placeholder="Select a permission rule...",
        options=[
            *[discord.SelectOption(label=label, value=f"role::{key}", description=f"Configure roles for {label.lower()} checks") for key, label in PERMISSION_ROLE_LABELS.items()],
            *[discord.SelectOption(label=label, value=f"user::{key}", description=f"Configure users for {label.lower()} checks") for key, label in PERMISSION_USER_LABELS.items()],
        ],
    )
    async def permission_select(self, interaction: discord.Interaction, select: discord.ui.Select):
        choice = select.values[0]
        kind, key = choice.split("::", 1)
        if kind == "role":
            view = PermissionRoleConfigView(self.guild, self.author, key, PERMISSION_ROLE_LABELS[key])
            embed = discord.Embed(
                title=f"Configure Roles: {PERMISSION_ROLE_LABELS[key]}",
                description="Select the roles that should satisfy this permission check.",
                color=BLANK_COLOR,
            )
        else:
            view = PermissionUsersView(self.guild, self.author, key, PERMISSION_USER_LABELS[key])
            embed = view.get_embed()
        brand_footer(embed)
        await interaction.response.edit_message(embed=embed, view=view)

    @discord.ui.button(label="Back to Settings", style=discord.ButtonStyle.secondary, row=2)
    async def back_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = DashboardView(self.guild, self.author)
        await edit_settings_dashboard(interaction.response, self.guild, view)


class PermissionRoleConfigView(discord.ui.View):
    def __init__(self, guild, author, permission_key, label):
        super().__init__(timeout=120)
        self.guild = guild
        self.author = author
        self.permission_key = permission_key
        self.label = label
        self.selected_roles = list(get_permission_role_ids(guild.id, permission_key))

        current_roles = [guild.get_role(role_id) for role_id in self.selected_roles]
        current_roles = [role for role in current_roles if role is not None][:25]
        for child in self.children:
            if isinstance(child, discord.ui.RoleSelect):
                child.default_values = current_roles
                break

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author.id:
            await interaction.response.send_message("You cannot use this.", ephemeral=True)
            return False
        return True

    @discord.ui.select(cls=discord.ui.RoleSelect, placeholder="Select roles...", min_values=0, max_values=25)
    async def role_select(self, interaction: discord.Interaction, select: discord.ui.RoleSelect):
        self.selected_roles = [role.id for role in select.values]
        await interaction.response.defer()

    @discord.ui.button(label="Save", style=discord.ButtonStyle.green, row=2)
    async def save_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        update_permission_role_setting(self.guild.id, self.permission_key, self.selected_roles)
        view = PermissionConfigMenuView(self.guild, self.author)
        await interaction.response.edit_message(embed=view.get_embed(), view=view)

    @discord.ui.button(label="Back", style=discord.ButtonStyle.secondary, row=2)
    async def back_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = PermissionConfigMenuView(self.guild, self.author)
        await interaction.response.edit_message(embed=view.get_embed(), view=view)


class PermissionUsersModal(discord.ui.Modal):
    user_ids = discord.ui.TextInput(
        label="Discord user IDs",
        style=discord.TextStyle.paragraph,
        placeholder="One user ID per line or comma-separated",
        required=False,
        max_length=1000,
    )

    def __init__(self, guild, author, permission_key, label, original_message):
        super().__init__(title=f"Edit Users: {label}")
        self.guild = guild
        self.author = author
        self.permission_key = permission_key
        self.label = label
        self.original_message = original_message
        current_users = get_permission_user_ids(guild.id, permission_key)
        self.user_ids.default = "\n".join(str(user_id) for user_id in current_users)

    async def on_submit(self, interaction: discord.Interaction):
        raw = self.user_ids.value.replace(",", "\n")
        parsed_user_ids = []
        for value in raw.splitlines():
            value = value.strip()
            if not value:
                continue
            if not value.isdigit():
                await interaction.response.send_message(f"`{value}` is not a valid Discord user ID.", ephemeral=True)
                return
            parsed_user_ids.append(int(value))
        update_permission_user_setting(self.guild.id, self.permission_key, parsed_user_ids)
        await interaction.response.defer()
        view = PermissionConfigMenuView(self.guild, self.author)
        await self.original_message.edit(embed=view.get_embed(), view=view)


class PermissionUsersView(discord.ui.View):
    def __init__(self, guild, author, permission_key, label):
        super().__init__(timeout=120)
        self.guild = guild
        self.author = author
        self.permission_key = permission_key
        self.label = label

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author.id:
            await interaction.response.send_message("You cannot use this.", ephemeral=True)
            return False
        return True

    def get_embed(self):
        current_users = get_permission_user_ids(self.guild.id, self.permission_key)
        description = "\n".join(f"> `{user_id}`" for user_id in current_users) or "> None"
        embed = discord.Embed(
            title=f"Configure Users: {self.label}",
            description=f"Current allowed users:\n{description}\n\nClick **Edit Users** to update the list.",
            color=BLANK_COLOR,
        )
        brand_footer(embed)
        return embed

    @discord.ui.button(label="Edit Users", style=discord.ButtonStyle.primary)
    async def edit_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        modal = PermissionUsersModal(self.guild, self.author, self.permission_key, self.label, interaction.message)
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="Back", style=discord.ButtonStyle.secondary)
    async def back_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = PermissionConfigMenuView(self.guild, self.author)
        await interaction.response.edit_message(embed=view.get_embed(), view=view)


class RoleConfigView(discord.ui.View):
    def __init__(self, guild, author, setting_key, label):
        super().__init__(timeout=120)
        self.guild = guild
        self.author = author
        self.setting_key = setting_key
        self.label = label
        settings = get_guild_settings(guild.id)
        self.selected_roles = list(settings.get(setting_key, []))

        current_roles = [guild.get_role(role_id) for role_id in self.selected_roles]
        current_roles = [role for role in current_roles if role is not None][:25]
        for child in self.children:
            if isinstance(child, discord.ui.RoleSelect):
                child.default_values = current_roles
                break

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author.id:
            await interaction.response.send_message("You cannot use this.", ephemeral=True)
            return False
        return True

    @discord.ui.select(cls=discord.ui.RoleSelect, placeholder="Select roles...", min_values=1, max_values=25)
    async def role_select(self, interaction: discord.Interaction, select: discord.ui.RoleSelect):
        self.selected_roles = [r.id for r in select.values]
        await interaction.response.defer()

    @discord.ui.button(label="Save", style=discord.ButtonStyle.green, row=2)
    async def save_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.selected_roles:
            await interaction.response.send_message("Select at least one role first.", ephemeral=True)
            return
        update_guild_setting(self.guild.id, self.setting_key, self.selected_roles)
        view = DashboardView(self.guild, self.author)
        await edit_settings_dashboard(interaction.response, self.guild, view)

    @discord.ui.button(label="Back", style=discord.ButtonStyle.secondary, row=2)
    async def back_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = DashboardView(self.guild, self.author)
        await edit_settings_dashboard(interaction.response, self.guild, view)


class ChannelConfigView(discord.ui.View):
    def __init__(self, guild, author, setting_key, label):
        super().__init__(timeout=120)
        self.guild = guild
        self.author = author
        self.setting_key = setting_key
        self.label = label
        self.selected_channel = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author.id:
            await interaction.response.send_message("You cannot use this.", ephemeral=True)
            return False
        return True

    @discord.ui.select(cls=discord.ui.ChannelSelect, placeholder="Select a channel...", channel_types=[discord.ChannelType.text])
    async def channel_select(self, interaction: discord.Interaction, select: discord.ui.ChannelSelect):
        self.selected_channel = select.values[0].id
        await interaction.response.defer()

    @discord.ui.button(label="Save", style=discord.ButtonStyle.green, row=2)
    async def save_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.selected_channel is None:
            await interaction.response.send_message("Select a channel first.", ephemeral=True)
            return
        update_guild_setting(self.guild.id, self.setting_key, self.selected_channel)
        sticky_sync_error = None
        if self.setting_key == "hostage_review_channel":
            channel = interaction.client.get_channel(int(self.selected_channel))
            if channel is not None:
                try:
                    from cogs.hits import ensure_hostage_sticky_message

                    await ensure_hostage_sticky_message(channel)
                except (discord.Forbidden, discord.HTTPException) as exc:
                    sticky_sync_error = str(exc)
        view = DashboardView(self.guild, self.author)
        await edit_settings_dashboard(interaction.response, self.guild, view)
        if sticky_sync_error:
            await interaction.followup.send(
                embed=error_embed(
                    "Sticky Message Not Sent",
                    "The hostage review channel was saved, but I could not send the initial sticky embed there."
                    f"\n```{sticky_sync_error[:1500]}```",
                ),
                ephemeral=True,
            )

    @discord.ui.button(label="Back", style=discord.ButtonStyle.secondary, row=2)
    async def back_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = DashboardView(self.guild, self.author)
        await edit_settings_dashboard(interaction.response, self.guild, view)


class ToggleView(discord.ui.View):
    def __init__(self, guild, author, setting_key):
        super().__init__(timeout=120)
        self.guild = guild
        self.author = author
        self.setting_key = setting_key

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author.id:
            await interaction.response.send_message("You cannot use this.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Enable", style=discord.ButtonStyle.green)
    async def enable_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        update_guild_setting(self.guild.id, self.setting_key, True)
        view = DashboardView(self.guild, self.author)
        await edit_settings_dashboard(interaction.response, self.guild, view)

    @discord.ui.button(label="Disable", style=discord.ButtonStyle.danger)
    async def disable_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        update_guild_setting(self.guild.id, self.setting_key, False)
        view = DashboardView(self.guild, self.author)
        await edit_settings_dashboard(interaction.response, self.guild, view)

    @discord.ui.button(label="Back", style=discord.ButtonStyle.secondary)
    async def back_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = DashboardView(self.guild, self.author)
        await edit_settings_dashboard(interaction.response, self.guild, view)


class QuestionsModal(discord.ui.Modal, title="Edit Feedback Questions"):
    questions_input = discord.ui.TextInput(
        label="Questions (one per line)",
        style=discord.TextStyle.paragraph,
        placeholder="Why did you decide to leave?\nWhat could we improve?\nWould you consider returning?",
        required=True,
        max_length=1000,
    )

    def __init__(self, guild, author, current_questions, original_message):
        super().__init__()
        self.guild = guild
        self.author = author
        self.original_message = original_message
        if current_questions:
            self.questions_input.default = "\n".join(current_questions)

    async def on_submit(self, interaction: discord.Interaction):
        questions = [q.strip() for q in self.questions_input.value.split("\n") if q.strip()]
        update_guild_setting(self.guild.id, "feedback_questions", questions)
        await interaction.response.defer()
        view = DashboardView(self.guild, self.author)
        await refresh_settings_dashboard(self.original_message, self.guild, view)


class QuestionsView(discord.ui.View):
    def __init__(self, guild, author):
        super().__init__(timeout=120)
        self.guild = guild
        self.author = author

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author.id:
            await interaction.response.send_message("You cannot use this.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Edit Questions", style=discord.ButtonStyle.primary)
    async def edit_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        settings = get_guild_settings(self.guild.id)
        questions = settings.get("feedback_questions", [])
        modal = QuestionsModal(self.guild, self.author, questions, interaction.message)
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="Back", style=discord.ButtonStyle.secondary)
    async def back_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = DashboardView(self.guild, self.author)
        await edit_settings_dashboard(interaction.response, self.guild, view)


class RankRolesMenuView(discord.ui.View):
    def __init__(self, guild, author):
        super().__init__(timeout=300)
        self.guild = guild
        self.author = author

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author.id:
            await interaction.response.send_message("You cannot use this.", ephemeral=True)
            return False
        return True

    def get_embed(self):
        settings = get_guild_settings(self.guild.id)
        rank_roles = settings.get("rank_roles", {})
        lines = []
        for rank in RANK_ORDER:
            rid = rank_roles.get(rank)
            lines.append(f"> **{rank}:** {_display_role(self.guild, rid)}")
        embed = discord.Embed(
            title="Configure: Rank Roles",
            description="Select a rank below to assign its Discord role.\n\n" + "\n".join(lines),
            color=BLANK_COLOR,
        )
        brand_footer(embed)
        return embed

    @discord.ui.select(
        placeholder="Select a rank to configure...",
        options=[discord.SelectOption(label=rank, value=rank) for rank in RANK_ORDER],
    )
    async def rank_select(self, interaction: discord.Interaction, select: discord.ui.Select):
        rank = select.values[0]
        view = SingleRankRoleView(self.guild, self.author, rank)
        embed = discord.Embed(
            title=f"Set Role for: {rank}",
            description="Select the Discord role that corresponds to this rank.",
            color=BLANK_COLOR,
        )
        brand_footer(embed)
        await interaction.response.edit_message(embed=embed, view=view)

    @discord.ui.button(label="Back to Settings", style=discord.ButtonStyle.secondary, row=2)
    async def back_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = DashboardView(self.guild, self.author)
        await edit_settings_dashboard(interaction.response, self.guild, view)


class SingleRankRoleView(discord.ui.View):
    def __init__(self, guild, author, rank_name):
        super().__init__(timeout=120)
        self.guild = guild
        self.author = author
        self.rank_name = rank_name
        settings = get_guild_settings(guild.id)
        rank_roles = settings.get("rank_roles", {})
        self.selected_role = rank_roles.get(rank_name)

        current_role = guild.get_role(self.selected_role) if self.selected_role else None
        for child in self.children:
            if isinstance(child, discord.ui.RoleSelect):
                child.default_values = [current_role] if current_role is not None else []
                break

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author.id:
            await interaction.response.send_message("You cannot use this.", ephemeral=True)
            return False
        return True

    @discord.ui.select(cls=discord.ui.RoleSelect, placeholder="Select the role for this rank...", min_values=1, max_values=1)
    async def role_select(self, interaction: discord.Interaction, select: discord.ui.RoleSelect):
        self.selected_role = select.values[0].id
        await interaction.response.defer()

    @discord.ui.button(label="Save", style=discord.ButtonStyle.green, row=2)
    async def save_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.selected_role is None:
            await interaction.response.send_message("Select a role first.", ephemeral=True)
            return
        update_rank_role(self.guild.id, self.rank_name, self.selected_role)
        view = RankRolesMenuView(self.guild, self.author)
        await interaction.response.edit_message(embed=view.get_embed(), view=view)

    @discord.ui.button(label="Clear", style=discord.ButtonStyle.danger, row=2)
    async def clear_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        update_rank_role(self.guild.id, self.rank_name, None)
        view = RankRolesMenuView(self.guild, self.author)
        await interaction.response.edit_message(embed=view.get_embed(), view=view)

    @discord.ui.button(label="Back", style=discord.ButtonStyle.secondary, row=2)
    async def back_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = RankRolesMenuView(self.guild, self.author)
        await interaction.response.edit_message(embed=view.get_embed(), view=view)


class Settings(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.hybrid_command(name="setup", description="Run the initial server setup wizard.")
    @commands.has_permissions(manage_guild=True)
    @app_commands.default_permissions(manage_guild=True)
    async def setup_cmd(self, ctx: commands.Context):
        get_guild_settings(ctx.guild.id)

        view = DashboardView(ctx.guild, ctx.author)
        embed = discord.Embed(
            title="Server Setup",
            description=(
                "Welcome to the setup wizard! Use the dropdown below to configure each setting.\n\n"
                "You should configure the following for all features to work:\n"
                "> `1.` **Staff Roles** — roles removed on retirement\n"
                "> `2.` **Retirement Log Channel** — where retirement/reinstatement logs go\n"
                "> `3.` **Staff Feedback Channel** — where staff feedback is posted\n"
                "> `4.` **Partnership Log Channel** - where partnership activity is logged\n"
                "> `5.` **Discord Checks** — toggle the automated Discord check loop\n"
                "> `6.` **Leave Feedback** — toggle & questions for leave DMs\n"
                "> `7.` **Partnership Permissions** — who can use /partnership\n"
                "> `8.` **Embed Creation Permissions** — who can use /embed create\n"
                "> `9.` **Retire/Reinstate/Demote Permissions** — who can use /retire, /reinstate, and /demote\n"
                "> `10.` **Rank Roles** — map rank names to Discord roles\n"
                "> `11.` **Permission Checks** — replace hardcoded command access rules\n"
            ),
            color=BLANK_COLOR,
        )
        embed.set_author(name="CSRP Utilities", icon_url=CSRP_ICON)
        brand_footer(embed)
        await ctx.send(embed=embed, view=view)

    @commands.hybrid_command(name="settings", description="View and manage server settings.")
    @commands.has_permissions(manage_guild=True)
    @app_commands.default_permissions(manage_guild=True)
    async def settings_cmd(self, ctx: commands.Context):
        view = DashboardView(ctx.guild, ctx.author)
        await send_settings_dashboard(ctx, ctx.guild, view)


async def setup(bot):
    await bot.add_cog(Settings(bot))
