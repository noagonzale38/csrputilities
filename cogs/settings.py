import discord
from discord.ext import commands
from discord import app_commands
import json
import copy

from cogs.helpers import (
    BLANK_COLOR, CSRP_ICON, CHECK, CROSS,
    brand_footer, success_embed, error_embed,
)

SETTINGS_FILE = "guild_settings.json"

DEFAULT_SETTINGS = {
    "staff_roles": [],
    "retirement_log_channel": None,
    "feedback_enabled": False,
    "feedback_questions": ["Why did you decide to leave?"],
    "staff_feedback_channel": None,
    "partnership_allowed_roles": [],
    "embed_allowed_roles": [],
    "retire_allowed_roles": [],
    "rank_roles": {
        "Senior Management": None,
        "Management": None,
        "Internal Affairs Supervisor": None,
        "Internal Affairs": None,
        "Senior Admin": None,
        "Admin": None,
        "Junior Admin": None,
        "Senior Moderator": None,
        "Moderator": None,
    },
}

RANK_ORDER = list(DEFAULT_SETTINGS["rank_roles"].keys())


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
    for k, v in DEFAULT_SETTINGS.items():
        if k not in settings:
            settings[k] = copy.deepcopy(v)
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


def dashboard_embed(guild: discord.Guild) -> discord.Embed:
    settings = get_guild_settings(guild.id)

    staff = ", ".join(f"<@&{r}>" for r in settings.get("staff_roles", [])) or "`Not set`"
    log_ch = f"<#{settings['retirement_log_channel']}>" if settings.get("retirement_log_channel") else "`Not set`"
    fb_ch = f"<#{settings['staff_feedback_channel']}>" if settings.get("staff_feedback_channel") else "`Not set`"
    fb_on = f"{CHECK} Enabled" if settings.get("feedback_enabled") else f"{CROSS} Disabled"
    questions = settings.get("feedback_questions", [])
    q_text = "\n".join(f"> `{i + 1}.` {q}" for i, q in enumerate(questions)) or "> None"
    partner = ", ".join(f"<@&{r}>" for r in settings.get("partnership_allowed_roles", [])) or "`Not set`"
    embed_roles = ", ".join(f"<@&{r}>" for r in settings.get("embed_allowed_roles", [])) or "`Not set`"
    retire = ", ".join(f"<@&{r}>" for r in settings.get("retire_allowed_roles", [])) or "`Not set`"

    rank_roles = settings.get("rank_roles", {})
    rank_lines = []
    for rank in RANK_ORDER:
        rid = rank_roles.get(rank)
        rank_lines.append(f"> **{rank}:** " + (f"<@&{rid}>" if rid else "`Not set`"))
    rank_text = "\n".join(rank_lines)

    desc = (
        f"**Staff Roles:** {staff}\n"
        f"**Retirement Log Channel:** {log_ch}\n"
        f"**Staff Feedback Channel:** {fb_ch}\n\n"
        f"**Leave Feedback:** {fb_on}\n"
        f"**Questions:**\n{q_text}\n\n"
        f"**Partnership Permissions:** {partner}\n"
        f"**Embed Creation Permissions:** {embed_roles}\n"
        f"**Retire/Reinstate Permissions:** {retire}\n\n"
        f"**Rank Roles:**\n{rank_text}"
    )

    embed = discord.Embed(title="Server Settings", description=desc, color=BLANK_COLOR)
    embed.set_author(name="CSRP Utilities", icon_url=CSRP_ICON)
    brand_footer(embed)
    return embed


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
            discord.SelectOption(label="Staff Feedback Channel", value="staff_feedback_channel", description="Where staff feedback is posted"),
            discord.SelectOption(label="Leave Feedback Toggle", value="feedback_enabled", description="Toggle leave feedback DMs"),
            discord.SelectOption(label="Leave Feedback Questions", value="feedback_questions", description="Edit the leave feedback questions"),
            discord.SelectOption(label="Partnership Permissions", value="partnership_allowed_roles", description="Who can use /partnership"),
            discord.SelectOption(label="Embed Creation Permissions", value="embed_allowed_roles", description="Who can use /embed create"),
            discord.SelectOption(label="Retire/Reinstate Permissions", value="retire_allowed_roles", description="Who can use /retire & /reinstate"),
            discord.SelectOption(label="Rank Role Mapping", value="rank_roles", description="Map ranks to Discord roles"),
        ],
    )
    async def select_setting(self, interaction: discord.Interaction, select: discord.ui.Select):
        choice = select.values[0]

        if choice in ("staff_roles", "partnership_allowed_roles", "embed_allowed_roles", "retire_allowed_roles"):
            labels = {
                "staff_roles": "Staff Roles",
                "partnership_allowed_roles": "Partnership Permissions",
                "embed_allowed_roles": "Embed Creation Permissions",
                "retire_allowed_roles": "Retire/Reinstate Permissions",
            }
            descs = {
                "staff_roles": "Select all roles considered **staff**. These are removed when a user is retired.",
                "partnership_allowed_roles": "Select the roles allowed to use the **/partnership** command.",
                "embed_allowed_roles": "Select the roles allowed to use the **/embed create** command.",
                "retire_allowed_roles": "Select the roles allowed to use **/retire** and **/reinstate**.",
            }
            view = RoleConfigView(self.guild, self.author, choice, labels[choice])
            embed = discord.Embed(title=f"Configure: {labels[choice]}", description=descs[choice], color=BLANK_COLOR)
            brand_footer(embed)
            await interaction.response.edit_message(embed=embed, view=view)

        elif choice in ("retirement_log_channel", "staff_feedback_channel"):
            labels = {
                "retirement_log_channel": "Retirement Log Channel",
                "staff_feedback_channel": "Staff Feedback Channel",
            }
            view = ChannelConfigView(self.guild, self.author, choice, labels[choice])
            embed = discord.Embed(title=f"Configure: {labels[choice]}", description="Select the channel below.", color=BLANK_COLOR)
            brand_footer(embed)
            await interaction.response.edit_message(embed=embed, view=view)

        elif choice == "feedback_enabled":
            settings = get_guild_settings(self.guild.id)
            current = settings.get("feedback_enabled", False)
            view = ToggleView(self.guild, self.author)
            status = f"{CHECK} Enabled" if current else f"{CROSS} Disabled"
            embed = discord.Embed(
                title="Configure: Leave Feedback",
                description=f"Currently: **{status}**\n\nWhen enabled, users who leave the server will be DMed feedback questions.",
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
        await interaction.response.edit_message(embed=dashboard_embed(self.guild), view=view)

    @discord.ui.button(label="Back", style=discord.ButtonStyle.secondary, row=2)
    async def back_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = DashboardView(self.guild, self.author)
        await interaction.response.edit_message(embed=dashboard_embed(self.guild), view=view)


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
        view = DashboardView(self.guild, self.author)
        await interaction.response.edit_message(embed=dashboard_embed(self.guild), view=view)

    @discord.ui.button(label="Back", style=discord.ButtonStyle.secondary, row=2)
    async def back_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = DashboardView(self.guild, self.author)
        await interaction.response.edit_message(embed=dashboard_embed(self.guild), view=view)


class ToggleView(discord.ui.View):
    def __init__(self, guild, author):
        super().__init__(timeout=120)
        self.guild = guild
        self.author = author

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author.id:
            await interaction.response.send_message("You cannot use this.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Enable", style=discord.ButtonStyle.green)
    async def enable_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        update_guild_setting(self.guild.id, "feedback_enabled", True)
        view = DashboardView(self.guild, self.author)
        await interaction.response.edit_message(embed=dashboard_embed(self.guild), view=view)

    @discord.ui.button(label="Disable", style=discord.ButtonStyle.danger)
    async def disable_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        update_guild_setting(self.guild.id, "feedback_enabled", False)
        view = DashboardView(self.guild, self.author)
        await interaction.response.edit_message(embed=dashboard_embed(self.guild), view=view)

    @discord.ui.button(label="Back", style=discord.ButtonStyle.secondary)
    async def back_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = DashboardView(self.guild, self.author)
        await interaction.response.edit_message(embed=dashboard_embed(self.guild), view=view)


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
        await self.original_message.edit(embed=dashboard_embed(self.guild), view=view)


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
        await interaction.response.edit_message(embed=dashboard_embed(self.guild), view=view)


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
            lines.append(f"> **{rank}:** " + (f"<@&{rid}>" if rid else "`Not set`"))
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
        await interaction.response.edit_message(embed=dashboard_embed(self.guild), view=view)


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
                "> `4.` **Leave Feedback** — toggle & questions for leave DMs\n"
                "> `5.` **Partnership Permissions** — who can use /partnership\n"
                "> `6.` **Embed Creation Permissions** — who can use /embed create\n"
                "> `7.` **Retire/Reinstate Permissions** — who can use /retire & /reinstate\n"
                "> `8.` **Rank Roles** — map rank names to Discord roles\n"
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
        await ctx.send(embed=dashboard_embed(ctx.guild), view=view)


async def setup(bot):
    await bot.add_cog(Settings(bot))
