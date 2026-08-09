import discord
from discord.ext import commands
from discord import app_commands, ui
import asyncio
import json
import contextlib
from typing import Optional

from config import active_hits, BLACKLIST_ROLE_ID, CSRPUTILS_DEVS, DEV_ROLE_IDS
from cogs.settings import get_guild_settings, update_guild_setting
from cogs.helpers import (
    Colors, BLANK_COLOR, CHECK, CROSS, CSRP_ICON,
    success_embed, error_embed, info_embed, brand_footer, embed_description,
    PaginatorView,
)


MANAGEMENT_RANKS = ("Senior Management", "Management")
MANAGEMENT_PLUS_ROLE_IDS = {1131166127964291172, 1157648329619021844}


def can_clear_hits(member: discord.Member) -> bool:
    if not getattr(member, "guild", None):
        return False
    if member.id in CSRPUTILS_DEVS:
        return True

    member_role_ids = {role.id for role in member.roles}
    allowed_role_ids = set(DEV_ROLE_IDS) | MANAGEMENT_PLUS_ROLE_IDS

    settings = get_guild_settings(member.guild.id)
    rank_roles = settings.get("rank_roles", {})
    for rank in MANAGEMENT_RANKS:
        role_id = rank_roles.get(rank)
        if role_id:
            allowed_role_ids.add(int(role_id))

    return bool(member_role_ids & allowed_role_ids)


def can_review_hostage_request(member: discord.Member) -> bool:
    if not getattr(member, "guild", None):
        return False
    if member.id in CSRPUTILS_DEVS:
        return True

    settings = get_guild_settings(member.guild.id)
    staff_role_ids = {int(role_id) for role_id in settings.get("staff_roles", [])}
    if not staff_role_ids:
        return False

    member_role_ids = {role.id for role in member.roles}
    return bool(member_role_ids & staff_role_ids)


def _build_hostage_sticky_embed(guild: discord.Guild) -> discord.Embed:
    embed = discord.Embed(
        title="Hostage Requests",
        description=(
            "Staff can approve hostage requests sent by members here. In the case that a member asks you for hostage "
            "permissions, and you want to manually approve it here, click the button below to fill out the hostage request form."
        ),
        color=BLANK_COLOR,
    )
    embed.set_author(name=guild.name, icon_url=guild.icon.url if guild.icon else "")
    brand_footer(embed)
    return embed


def _build_hostage_request_embed(
    guild: discord.Guild,
    requester: discord.abc.User,
    members: int,
    hostage: str | None,
    duration: str,
    *,
    hostage_taker: str | None = None,
) -> discord.Embed:
    hostage_display = hostage or "No user provided"
    description = (
        f"> **Requested By:** {requester.mention}\n"
        f"> **Members Involved:** `{members}`\n"
        f"> **Hostage:** `{hostage_display}`\n"
    )
    if hostage_taker:
        description += f"> **Hostage Taker:** `{hostage_taker}`\n"
    description += f"> **Duration:** `{duration}`"

    embed = discord.Embed(title="Hostage Scene Request", description=description, color=BLANK_COLOR)
    embed.set_author(name=guild.name, icon_url=guild.icon.url if guild.icon else "")
    if requester.display_avatar:
        embed.set_thumbnail(url=requester.display_avatar.url)
    brand_footer(embed)
    return embed


def _build_hostage_accepted_embed(
    requester: discord.abc.User,
    members: int,
    hostage: str | None,
    duration: str,
    accepted_by: discord.abc.User,
    *,
    hostage_taker: str | None = None,
) -> discord.Embed:
    hostage_display = hostage or "No user provided"
    description = (
        f"> **Requested By:** {requester.mention}\n"
        f"> **Members Involved:** `{members}`\n"
        f"> **Hostage:** `{hostage_display}`\n"
    )
    if hostage_taker:
        description += f"> **Hostage Taker:** `{hostage_taker}`\n"
    description += (
        f"> **Duration:** `{duration}`\n"
        f"> **Accepted By:** {accepted_by.mention}"
    )

    embed = discord.Embed(
        title="Hostage Scene Accepted",
        description=description,
        color=BLANK_COLOR,
    )
    embed.set_author(name="CSRP Utilities", icon_url=CSRP_ICON)
    if requester.display_avatar:
        embed.set_thumbnail(url=requester.display_avatar.url)
    brand_footer(embed)
    return embed


class HostageStickyView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if can_review_hostage_request(interaction.user):
            return True
        await interaction.response.send_message(
            embed=error_embed("Not Permitted", "Only configured staff members can create manual hostage approvals."),
            ephemeral=True,
        )
        return False

    @discord.ui.button(
        label="Create Hostage Request",
        style=discord.ButtonStyle.primary,
        custom_id="hostage_manual_create",
    )
    async def create_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(StaffHostageRequestModal())


class StaffHostageRequestModal(discord.ui.Modal, title="Manual Hostage Request"):
    hostage_taker = ui.TextInput(
        label="Hostage Taker Username",
        placeholder="Enter ROBLOX username",
        required=True,
        max_length=32,
    )
    members = ui.TextInput(
        label="Members Involved",
        placeholder="1",
        required=True,
        max_length=1,
    )
    hostage = ui.TextInput(
        label="Hostage Username",
        placeholder="Enter ROBLOX username (OPTIONAL)",
        required=False,
        max_length=32,
    )
    duration = ui.TextInput(
        label="Duration",
        placeholder="30 mins",
        required=True,
        max_length=100,
    )

    async def on_submit(self, interaction: discord.Interaction):
        if not interaction.guild:
            await interaction.response.send_message(
                embed=error_embed("Unavailable", "This form can only be used in a server."),
                ephemeral=True,
            )
            return

        if not can_review_hostage_request(interaction.user):
            await interaction.response.send_message(
                embed=error_embed("Not Permitted", "Only configured staff members can create manual hostage approvals."),
                ephemeral=True,
            )
            return

        members_value = self.members.value.strip()
        if not members_value.isdigit() or int(members_value) <= 0:
            await interaction.response.send_message(
                embed=error_embed("Invalid Member Count", "Members must be a positive number."),
                ephemeral=True,
            )
            return

        hostage_value = self.hostage.value.strip() or None
        hostage_taker_value = self.hostage_taker.value.strip()
        duration_value = self.duration.value.strip()

        for label, value in (("Hostage", hostage_value), ("Hostage Taker", hostage_taker_value)):
            if not value:
                continue
            try:
                float(value)
                await interaction.response.send_message(
                    embed=error_embed(f"Invalid {label}", f"{label}s must not be a number."),
                    ephemeral=True,
                )
                return
            except ValueError:
                pass

        settings = get_guild_settings(interaction.guild.id)
        review_channel_id = settings.get("hostage_review_channel")
        if not review_channel_id:
            await interaction.response.send_message(
                embed=error_embed("Not Configured", "Hostage review channel has not been configured in `/settings`."),
                ephemeral=True,
            )
            return

        channel = interaction.client.get_channel(int(review_channel_id))
        if channel is None:
            await interaction.response.send_message(
                embed=error_embed("Invalid Channel", "The configured hostage review channel could not be found."),
                ephemeral=True,
            )
            return

        embed = _build_hostage_accepted_embed(
            interaction.user,
            int(members_value),
            hostage_value,
            duration_value,
            interaction.user,
            hostage_taker=hostage_taker_value,
        )
        await channel.send(embed=embed)
        await refresh_hostage_sticky_message(channel)
        await interaction.response.send_message(
            embed=success_embed("Hostage Scene Accepted", "The manual hostage request has been created and auto-approved."),
            ephemeral=True,
        )


_hostage_sticky_lock = asyncio.Lock()


async def ensure_hostage_sticky_message(channel: discord.TextChannel) -> None:
    guild = getattr(channel, "guild", None)
    if guild is None:
        return

    async with _hostage_sticky_lock:
        settings = get_guild_settings(guild.id)
        sticky_message_id = settings.get("hostage_sticky_message_id")
        if sticky_message_id:
            with contextlib.suppress(discord.NotFound, discord.Forbidden, discord.HTTPException):
                await channel.fetch_message(int(sticky_message_id))
                return

        message = await channel.send(embed=_build_hostage_sticky_embed(guild), view=HostageStickyView())
        update_guild_setting(guild.id, "hostage_sticky_message_id", message.id)


async def refresh_hostage_sticky_message(channel: discord.TextChannel) -> None:
    guild = getattr(channel, "guild", None)
    if guild is None:
        return

    async with _hostage_sticky_lock:
        settings = get_guild_settings(guild.id)
        sticky_message_id = settings.get("hostage_sticky_message_id")
        if sticky_message_id:
            # A refresh queued behind the lock may find the sticky already reposted.
            if channel.last_message_id == int(sticky_message_id):
                return
            with contextlib.suppress(discord.NotFound, discord.Forbidden, discord.HTTPException):
                old_message = await channel.fetch_message(int(sticky_message_id))
                await old_message.delete()

        message = await channel.send(embed=_build_hostage_sticky_embed(guild), view=HostageStickyView())
        update_guild_setting(guild.id, "hostage_sticky_message_id", message.id)


PARTNERSHIP_CHANNEL_ID = 1438594753640927323


def _build_partnership_sticky_embed(guild: discord.Guild) -> discord.Embed:
    embed = discord.Embed(
        title="⚠️ Partnership Proof Requirements",
        description=(
            "## ❗ Important — Read Before Submitting\n\n"
            "**Your image must be proof of you making the ticket in a __different server__ "
            "and asking for a partnership.**\n\n"
            ">>> \U0001f4cb **What your proof needs to show:**\n"
            "- A screenshot of the **ticket you created** in the other server\n"
            "- The ticket must clearly show you **requesting a partnership**\n"
            "- The server must be **different from this one**\n\n"
            "❌ **The following will NOT be accepted:**\n"
            "- Screenshots of DMs\n"
            "- Screenshots from this server\n"
            "- Images that do not show a ticket or partnership request"
        ),
        color=0xFFA500,
    )
    embed.set_author(name=guild.name, icon_url=guild.icon.url if guild.icon else "")
    brand_footer(embed)
    return embed


_partnership_sticky_lock = asyncio.Lock()


async def ensure_partnership_sticky_message(bot) -> None:
    channel = bot.get_channel(PARTNERSHIP_CHANNEL_ID)
    if channel is None:
        return

    guild = channel.guild
    async with _partnership_sticky_lock:
        settings = get_guild_settings(guild.id)
        sticky_message_id = settings.get("partnership_sticky_message_id")
        if sticky_message_id:
            with contextlib.suppress(discord.NotFound, discord.Forbidden, discord.HTTPException):
                await channel.fetch_message(int(sticky_message_id))
                return

        message = await channel.send(embed=_build_partnership_sticky_embed(guild))
        update_guild_setting(guild.id, "partnership_sticky_message_id", message.id)


async def refresh_partnership_sticky_message(bot) -> None:
    channel = bot.get_channel(PARTNERSHIP_CHANNEL_ID)
    if channel is None:
        return

    guild = channel.guild
    async with _partnership_sticky_lock:
        settings = get_guild_settings(guild.id)
        sticky_message_id = settings.get("partnership_sticky_message_id")
        if sticky_message_id:
            # A refresh queued behind the lock may find the sticky already reposted.
            if channel.last_message_id == int(sticky_message_id):
                return
            with contextlib.suppress(discord.NotFound, discord.Forbidden, discord.HTTPException):
                old_message = await channel.fetch_message(int(sticky_message_id))
                await old_message.delete()

        message = await channel.send(embed=_build_partnership_sticky_embed(guild))
        update_guild_setting(guild.id, "partnership_sticky_message_id", message.id)


def _build_active_hit_pages(guild, entries, query=None):
    title = f'Active Hits — "{query}"' if query else "Active Hits"

    def finish(embed):
        embed.set_author(name=guild.name, icon_url=guild.icon.url if guild.icon else "")
        brand_footer(embed)
        return embed

    if not entries:
        return [
            finish(
                discord.Embed(
                    title=title,
                    description=f"No active hits matching `{query}`." if query else "No active hits at the moment.",
                    color=BLANK_COLOR,
                )
            )
        ]

    per_page = 5
    pages = []
    for i in range(0, len(entries), per_page):
        chunk = entries[i:i + per_page]
        pages.append(
            finish(
                discord.Embed(
                    title=title,
                    description="\n\n".join(
                        (
                            f"**Hit #{number}**\n"
                            f"> **Target:** `{hit_data['target']}`\n"
                            f"> **Bounty:** `{hit_data['bounty']}`\n"
                            f"> **Reason:** {hit_data['reason']}\n"
                            f"> **Placed By:** <@{hit_data['placed_by']}>"
                        )
                        for number, hit_data in chunk
                    ),
                    color=BLANK_COLOR,
                )
            )
        )
    return pages


class HitSearchModal(discord.ui.Modal, title="Search Active Hits"):
    query = ui.TextInput(
        label="Username",
        placeholder="Full or partial in-game name",
        required=True,
        max_length=100,
    )

    def __init__(self, parent_view):
        super().__init__()
        self.parent_view = parent_view

    async def on_submit(self, interaction: discord.Interaction):
        await self.parent_view.set_query(interaction, self.query.value.strip() or None)


class ActiveHitsView(PaginatorView):
    def __init__(self, guild, entries, author, *, timeout: float = 120):
        self.guild = guild
        self.entries = entries
        self.query = None
        super().__init__(_build_active_hit_pages(guild, entries), author, timeout=timeout)

    def _update_buttons(self):
        super()._update_buttons()
        self.clear_btn.disabled = self.query is None

    async def set_query(self, interaction: discord.Interaction, query: Optional[str]):
        self.query = query
        if query:
            entries = [(number, hit_data) for number, hit_data in self.entries if query.lower() in hit_data["target"].lower()]
        else:
            entries = self.entries
        self.pages = _build_active_hit_pages(self.guild, entries, query)
        self.current = 0
        self._update_buttons()
        await interaction.response.edit_message(embed=self.pages[0], view=self)

    @discord.ui.button(label="Search", style=discord.ButtonStyle.primary, row=1)
    async def search_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(HitSearchModal(self))

    @discord.ui.button(label="Clear Search", style=discord.ButtonStyle.secondary, row=1)
    async def clear_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.set_query(interaction, None)


class DenyHitModal(discord.ui.Modal, title="Deny Hit"):
    reason = ui.TextInput(label="Reason", placeholder="Reason for denying the hit", required=True)

    def __init__(self, parent_view, orig_interaction):
        super().__init__()
        self.parent_view = parent_view
        self.orig_interaction = orig_interaction

    async def on_submit(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="Hit Denied",
            description=embed_description(
                (
                    f"> **Placed By:** {self.parent_view.ctx.author.mention}\n"
                    f"> **Target:** `{self.parent_view.username}`\n"
                    f"> **Bounty:** `{self.parent_view.bounty}` in-game money\n"
                    f"> **Reason:** {self.parent_view.reason}"
                ),
                (
                    f"> **Denied By:** {interaction.user.mention}\n"
                    f"> **Denial Reason:** {self.reason.value}"
                ),
            ),
            color=BLANK_COLOR,
        )
        embed.set_author(name="CSRP Utilities", icon_url=CSRP_ICON)
        if self.parent_view.ctx.author.display_avatar:
            embed.set_thumbnail(url=self.parent_view.ctx.author.display_avatar.url)
        brand_footer(embed)
        await self.orig_interaction.message.edit(embed=embed, view=None)

        try:
            dm = await self.parent_view.ctx.author.create_dm()
            dm_embed = discord.Embed(
                title="Hit Denied",
                description=(
                    f"> **Target:** `{self.parent_view.username}`\n"
                    f"> **Bounty:** `{self.parent_view.bounty}` in-game money\n"
                    f"> **Denial Reason:** {self.reason.value}"
                ),
                color=BLANK_COLOR,
            )
            dm_embed.set_author(name="California State Roleplay", icon_url=CSRP_ICON)
            brand_footer(dm_embed)
            await dm.send(embed=dm_embed)
        except discord.Forbidden:
            pass

        log_channel = interaction.client.get_channel(1361900183016706200)
        if log_channel:
            embed_value = (
                f"> **Denied By:** {interaction.user.mention}\n"
                f"> **Denial Reason:** {self.reason.value}"
            )
            if self.parent_view.proofURL:
                embed_value += f"\n> **Proof:** [Attachment]({self.parent_view.proofURL})"
            log_embed = discord.Embed(
                title="Hit Denied",
                description=embed_description(
                    (
                        f"> **Placed By:** {self.parent_view.ctx.author.mention}\n"
                        f"> **Target:** `{self.parent_view.username}`\n"
                        f"> **Bounty:** `{self.parent_view.bounty}` in-game money\n"
                        f"> **Reason:** {self.parent_view.reason}"
                    ),
                    embed_value,
                ),
                color=BLANK_COLOR,
            )
            log_embed.set_author(name="CSRP Utilities", icon_url=CSRP_ICON)
            if self.parent_view.ctx.author.display_avatar:
                log_embed.set_thumbnail(url=self.parent_view.ctx.author.display_avatar.url)
            if self.parent_view.proofURL:
                log_embed.set_image(url=self.parent_view.proofURL)
            brand_footer(log_embed)
            await log_channel.send(embed=log_embed)

        await interaction.response.send_message(embed=success_embed("Hit Denied", "The hit has been denied."), ephemeral=True)


class HitRequestView(discord.ui.View):
    def __init__(self, ctx, username, bounty, reason, proof):
        super().__init__(timeout=None)
        self.ctx = ctx
        self.username = username
        self.bounty = bounty
        self.reason = reason
        self.proofURL = proof

    @discord.ui.button(label="Accept", style=discord.ButtonStyle.green, custom_id="hit_accept")
    async def accept_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            with open(active_hits, "r") as file:
                hits = json.load(file)
        except (FileNotFoundError, json.JSONDecodeError):
            hits = []

        hit_entry = {
            "placed_by": self.ctx.author.id,
            "target": self.username,
            "bounty": self.bounty,
            "reason": self.reason,
            "accepted_by": interaction.user.id,
        }
        hits.append(hit_entry)
        with open(active_hits, "w") as file:
            json.dump(hits, file, indent=4)

        log_channel = interaction.client.get_channel(1361900183016706200)
        if log_channel:
            log_description = (
                f"> **Placed By:** {self.ctx.author.mention}\n"
                f"> **Target:** `{self.username}`\n"
                f"> **Bounty:** `{self.bounty}` in-game money\n"
                f"> **Accepted By:** {interaction.user.mention}\n"
                f"> **Reason:** {self.reason}"
            )
            if self.proofURL:
                log_description += f"\n\n> **Proof:** [Attachment]({self.proofURL})"
            log_embed = discord.Embed(
                title="Hit Accepted",
                description=log_description,
                color=BLANK_COLOR,
            )
            log_embed.set_author(name="CSRP Utilities", icon_url=CSRP_ICON)
            if self.ctx.author.display_avatar:
                log_embed.set_thumbnail(url=self.ctx.author.display_avatar.url)
            if self.proofURL:
                log_embed.set_image(url=self.proofURL)
            brand_footer(log_embed)
            await log_channel.send(embed=log_embed)

        embed = discord.Embed(
            title="Hit Accepted",
            description=(
                f"> **Placed By:** {self.ctx.author.mention}\n"
                f"> **Target:** `{self.username}`\n"
                f"> **Bounty:** `{self.bounty}` in-game money\n"
                f"> **Accepted By:** {interaction.user.mention}\n"
                f"> **Reason:** {self.reason}"
            ),
            color=BLANK_COLOR,
        )
        embed.set_author(name="CSRP Utilities", icon_url=CSRP_ICON)
        brand_footer(embed)
        await interaction.message.edit(embed=embed, view=None)
        await interaction.response.send_message(embed=success_embed("Hit Accepted", "The hit has been accepted."), ephemeral=True)

        try:
            dm = await self.ctx.author.create_dm()
            dm_embed = discord.Embed(
                title="Hit Accepted",
                description=(
                    f"> **Target:** `{self.username}`\n"
                    f"> **Bounty:** `{self.bounty}` in-game money\n"
                    f"> **Reason:** {self.reason}"
                ),
                color=BLANK_COLOR,
            )
            dm_embed.set_author(name="California State Roleplay", icon_url=CSRP_ICON)
            brand_footer(dm_embed)
            await dm.send(embed=dm_embed)
        except discord.Forbidden:
            pass

    @discord.ui.button(label="Deny", style=discord.ButtonStyle.danger, custom_id="hit_deny")
    async def deny_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(DenyHitModal(self, interaction))


class DenyHostageModal(discord.ui.Modal, title="Deny Hostage Scene"):
    reason = ui.TextInput(label="Reason", placeholder="Reason for denying the hostage scene", required=True)

    def __init__(self, parent_view, review_message: discord.Message):
        super().__init__()
        self.parent_view = parent_view
        self.review_message = review_message

    async def on_submit(self, interaction: discord.Interaction):
        hostage_display = self.parent_view.hostage or "No user provided"
        embed = discord.Embed(
            title="Hostage Scene Denied",
            description=(
                f"> **Requested By:** {self.parent_view.ctx.author.mention}\n"
                f"> **Members Involved:** `{self.parent_view.members}`\n"
                f"> **Hostage:** `{hostage_display}`\n"
                f"> **Duration:** `{self.parent_view.duration}`\n"
                f"> **Denied By:** {interaction.user.mention}\n"
                f"> **Denial Reason:** {self.reason.value}"
            ),
            color=BLANK_COLOR,
        )
        embed.set_author(name="CSRP Utilities", icon_url=CSRP_ICON)
        if self.parent_view.ctx.author.display_avatar:
            embed.set_thumbnail(url=self.parent_view.ctx.author.display_avatar.url)
        brand_footer(embed)
        await self.review_message.edit(embed=embed, view=None)

        try:
            dm = await self.parent_view.ctx.author.create_dm()
            dm_embed = discord.Embed(
                title="Hostage Scene Denied",
                description=(
                    f"> **Members Involved:** `{self.parent_view.members}`\n"
                    f"> **Hostage:** `{hostage_display}`\n"
                    f"> **Duration:** `{self.parent_view.duration}`\n"
                    f"> **Denial Reason:** {self.reason.value}"
                ),
                color=BLANK_COLOR,
            )
            dm_embed.set_author(name="California State Roleplay", icon_url=CSRP_ICON)
            brand_footer(dm_embed)
            await dm.send(embed=dm_embed)
        except discord.Forbidden:
            pass

        await interaction.response.send_message(
            embed=success_embed("Hostage Scene Denied", "The hostage request has been denied."),
            ephemeral=True,
        )


class HostageRequestView(discord.ui.View):
    def __init__(self, ctx, members: int, hostage: str | None, duration: str, hostage_taker: str | None = None):
        super().__init__(timeout=None)
        self.ctx = ctx
        self.members = members
        self.hostage = hostage
        self.duration = duration
        self.hostage_taker = hostage_taker

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if can_review_hostage_request(interaction.user):
            return True
        await interaction.response.send_message(
            embed=error_embed("Not Permitted", "Only configured staff members can review hostage requests."),
            ephemeral=True,
        )
        return False

    @discord.ui.button(label="Accept", style=discord.ButtonStyle.green, custom_id="hostage_accept")
    async def accept_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = _build_hostage_accepted_embed(
            self.ctx.author,
            self.members,
            self.hostage,
            self.duration,
            interaction.user,
            hostage_taker=self.hostage_taker,
        )
        await interaction.message.edit(embed=embed, view=None)
        await interaction.response.send_message(
            embed=success_embed("Hostage Scene Accepted", "The hostage request has been accepted."),
            ephemeral=True,
        )

        try:
            dm = await self.ctx.author.create_dm()
            hostage_display = self.hostage or "No user provided"
            dm_embed = discord.Embed(
                title="Hostage Scene Accepted",
                description=(
                    f"> **Members Involved:** `{self.members}`\n"
                    f"> **Hostage:** `{hostage_display}`\n"
                    + (f"> **Hostage Taker:** `{self.hostage_taker}`\n" if self.hostage_taker else "")
                    + f"> **Duration:** `{self.duration}`"
                ),
                color=BLANK_COLOR,
            )
            dm_embed.set_author(name="California State Roleplay", icon_url=CSRP_ICON)
            brand_footer(dm_embed)
            await dm.send(embed=dm_embed)
        except discord.Forbidden:
            pass

    @discord.ui.button(label="Deny", style=discord.ButtonStyle.danger, custom_id="hostage_deny")
    async def deny_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(DenyHostageModal(self, interaction.message))


class Hits(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self._hostage_sticky_registered = False

    async def cog_load(self):
        if self._hostage_sticky_registered:
            return
        self.bot.add_view(HostageStickyView())
        self._hostage_sticky_registered = True

    @commands.Cog.listener()
    async def on_ready(self):
        for guild in self.bot.guilds:
            settings = get_guild_settings(guild.id)
            review_channel_id = settings.get("hostage_review_channel")
            if not review_channel_id:
                continue
            channel = self.bot.get_channel(int(review_channel_id))
            if channel is not None:
                await ensure_hostage_sticky_message(channel)

        await ensure_partnership_sticky_message(self.bot)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return

        # Partnership channel sticky
        if message.channel.id == PARTNERSHIP_CHANNEL_ID:
            settings = get_guild_settings(message.guild.id)
            if settings.get("partnership_sticky_message_id") != message.id:
                await refresh_partnership_sticky_message(self.bot)
            return

        # Hostage review channel sticky
        settings = get_guild_settings(message.guild.id)
        review_channel_id = settings.get("hostage_review_channel")
        if not review_channel_id or message.channel.id != int(review_channel_id):
            return

        if settings.get("hostage_sticky_message_id") == message.id:
            return

        await refresh_hostage_sticky_message(message.channel)

    @commands.hybrid_group(name="hit", description="Hit related commands.")
    async def hit(self, ctx: commands.Context):
        if ctx.invoked_subcommand is None:
            embed = discord.Embed(
                title="Hit Commands",
                description=(
                    "> `/hit place` — Place a bounty on someone\n"
                    "> `/hit active` — View all active hits\n"
                    "> `/hit complete` — Mark a hit as completed\n"
                    "> `/hit clear` — Clear all active hits"
                ),
                color=BLANK_COLOR,
            )
            embed.set_author(name=ctx.guild.name, icon_url=ctx.guild.icon.url if ctx.guild.icon else "")
            embed.set_thumbnail(url=CSRP_ICON)
            brand_footer(embed)
            await ctx.send(embed=embed)

    @commands.hybrid_group(name="hostage", description="Hostage roleplay request commands.")
    async def hostage(self, ctx: commands.Context):
        if ctx.invoked_subcommand is None:
            embed = discord.Embed(
                title="Hostage Commands",
                description="> `/hostage place` — Request approval for an in-game hostage scene",
                color=BLANK_COLOR,
            )
            embed.set_author(name=ctx.guild.name, icon_url=ctx.guild.icon.url if ctx.guild.icon else "")
            embed.set_thumbnail(url=CSRP_ICON)
            brand_footer(embed)
            await ctx.send(embed=embed)

    @hit.command(name="place", description="Place a hit on someone in-game.")
    @app_commands.describe(username="The target's ROBLOX username", bounty="The bounty amount", proof="Optional proof attachment", reason="Reason for the hit")
    async def place(self, ctx, username: str, bounty: str, proof: Optional[discord.Attachment] = None, *, reason: str):
        if BLACKLIST_ROLE_ID in [role.id for role in ctx.author.roles]:
            await ctx.send(embed=error_embed("Blacklisted", "You are blacklisted from placing hits."))
            return

        bounty = bounty.lstrip("$")
        if not bounty.isdigit() or int(bounty) <= 0:
            await ctx.send(embed=error_embed("Invalid Bounty", "Bounty must be a positive number."))
            return

        bounty = int(bounty)
        if username.startswith("<@"):
            await ctx.send(embed=error_embed("Invalid Username", "You must enter the user's ROBLOX username, not a Discord mention."))
            return

        channel = self.bot.get_channel(1361904750051856645)
        description = (
            f"> **Placed By:** {ctx.author.mention}\n"
            f"> **Target:** `{username}`\n"
            f"> **Bounty:** `{bounty}` in-game money\n"
            f"> **Reason:** {reason}"
        )
        if proof:
            description += f"\n\n> **Proof:** [Attachment]({proof.url})"
        embed = discord.Embed(title="Hit Request", description=description, color=BLANK_COLOR)
        embed.set_author(name=ctx.guild.name, icon_url=ctx.guild.icon.url if ctx.guild.icon else "")
        if ctx.author.display_avatar:
            embed.set_thumbnail(url=ctx.author.display_avatar.url)
        if proof:
            embed.set_image(url=proof.url)
        brand_footer(embed)

        view = HitRequestView(ctx, username, bounty, reason, proof.url if proof else None)
        await channel.send(embed=embed, view=view)
        await ctx.send(embed=success_embed("Hit Submitted", "Hit request sent. You will be notified when it's reviewed."))

    @hostage.command(name="place", description="Request approval for an in-game hostage scene.")
    @app_commands.describe(
        members="How many members will be involved? (eg 1, 2, 3). No more than 3 are permitted.",
        hostage="Optional hostage ROBLOX username. Leave blank if none is being provided.",
        duration="How long the scene will go on for (approx). Example: 30mins, 15 mins.",
    )
    async def hostage_place(self, ctx, members: int, hostage: Optional[str] = None, *, duration: str):
        if members <= 0:
            await ctx.send(embed=error_embed("Invalid Member Count", "Members must be a positive number."))
            return
        hostage = hostage.strip() if hostage else None
        if hostage:
            try:
                float(hostage)
                await ctx.send(embed=error_embed("Invalid Hostage", "Hostages must not be a number."))
                return
            except ValueError:
                pass

        settings = get_guild_settings(ctx.guild.id)
        review_channel_id = settings.get("hostage_review_channel")
        if not review_channel_id:
            await ctx.send(embed=error_embed("Not Configured", "Hostage review channel has not been configured in `/settings`."))
            return

        channel = self.bot.get_channel(int(review_channel_id))
        if channel is None:
            await ctx.send(embed=error_embed("Invalid Channel", "The configured hostage review channel could not be found."))
            return

        view = HostageRequestView(ctx, members, hostage, duration)
        embed = _build_hostage_request_embed(ctx.guild, ctx.author, members, hostage, duration)
        await channel.send(embed=embed, view=view)
        await refresh_hostage_sticky_message(channel)
        await ctx.send(
            embed=success_embed(
                "Hostage Scene Submitted",
                "Your hostage scene request has been sent for staff review. You will be DMed once it is accepted or denied.",
            )
        )

    @hit.command(name="active", description="Shows all active hits.")
    async def active(self, ctx):
        try:
            with open(active_hits, "r") as file:
                hits = json.load(file)
        except (FileNotFoundError, json.JSONDecodeError):
            hits = []

        if not hits:
            embed = _build_active_hit_pages(ctx.guild, [])[0]
            await ctx.send(embed=embed)
            return

        entries = list(enumerate(hits, start=1))
        view = ActiveHitsView(ctx.guild, entries, ctx.author)
        msg = await ctx.send(embed=view.pages[0], view=view)
        view.message = msg

    @hit.command(name="complete", description="Mark a hit as completed.")
    @app_commands.describe(target="The target's in-game name")
    async def complete(self, ctx, target: str):
        try:
            with open(active_hits, "r") as file:
                hits = json.load(file)
        except (FileNotFoundError, json.JSONDecodeError):
            hits = []

        hit_data = next((hit for hit in hits if hit["target"].lower() == target.lower()), None)

        if not hit_data:
            await ctx.send(embed=error_embed("Hit Not Found", f"No active hit found for **{target}**."))
            return

        updated_hits = [hit for hit in hits if hit != hit_data]
        with open(active_hits, "w") as file:
            json.dump(updated_hits, file, indent=4)

        await ctx.send(embed=success_embed("Hit Completed", f"Hit on **{target}** has been completed."))

        log_channel = self.bot.get_channel(1361900183016706200)
        if log_channel:
            log_embed = discord.Embed(
                title="Hit Completed",
                description=(
                    f"> **Placed By:** <@{hit_data['placed_by']}>\n"
                    f"> **Target:** `{hit_data['target']}`\n"
                    f"> **Bounty:** `{hit_data['bounty']}` in-game money\n"
                    f"> **Reason:** {hit_data['reason']}\n"
                    f"> **Completed By:** {ctx.author.mention}"
                ),
                color=BLANK_COLOR,
            )
            log_embed.set_author(name="CSRP Utilities", icon_url=CSRP_ICON)
            if ctx.author.display_avatar:
                log_embed.set_thumbnail(url=ctx.author.display_avatar.url)
            brand_footer(log_embed)
            await log_channel.send(embed=log_embed)

        try:
            user = await self.bot.fetch_user(hit_data['placed_by'])
            dm_embed = discord.Embed(
                title="Hit Completed",
                description=(
                    f"> **Target:** `{hit_data['target']}`\n"
                    f"> **Bounty:** `{hit_data['bounty']}` in-game money\n"
                    f"> **Completed By:** {ctx.author.mention}\n"
                    f"> **Reason:** {hit_data['reason']}"
                ),
                color=BLANK_COLOR,
            )
            dm_embed.set_author(name="California State Roleplay", icon_url=CSRP_ICON)
            brand_footer(dm_embed)
            await user.send(embed=dm_embed)
        except Exception:
            pass

    @hit.command(name="clear", description="Clear all active hits.")
    async def clear(self, ctx):
        if not can_clear_hits(ctx.author):
            await ctx.send(embed=error_embed("Not Permitted", "Only MGMT+ and CSRP Developers can clear all hits."))
            return

        try:
            with open(active_hits, "r") as file:
                hits = json.load(file)
        except (FileNotFoundError, json.JSONDecodeError):
            hits = []

        cleared_count = len(hits)
        with open(active_hits, "w") as file:
            json.dump([], file, indent=4)

        await ctx.send(embed=success_embed("Hits Cleared", f"Cleared **{cleared_count}** active hit{'s' if cleared_count != 1 else ''}."))

        log_channel = self.bot.get_channel(1361900183016706200)
        if log_channel:
            log_embed = discord.Embed(
                title="Hits Cleared",
                description=(
                    f"> **Cleared By:** {ctx.author.mention}\n"
                    f"> **Hits Cleared:** `{cleared_count}`"
                ),
                color=BLANK_COLOR,
            )
            log_embed.set_author(name="CSRP Utilities", icon_url=CSRP_ICON)
            if ctx.author.display_avatar:
                log_embed.set_thumbnail(url=ctx.author.display_avatar.url)
            brand_footer(log_embed)
            await log_channel.send(embed=log_embed)


async def setup(bot):
    await bot.add_cog(Hits(bot))
