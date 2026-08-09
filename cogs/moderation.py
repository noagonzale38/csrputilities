import asyncio
import contextlib
import discord
from discord.ext import commands
from discord import app_commands
import re
import time
import random
from datetime import timedelta

from config import (
    INFRACTION_CHANNEL, APPEALS_CHANNEL_ID, is_moderation, is_role_authorized, is_bot_dev,
    RESTRICTION_BYPASS_USER_IDS,
)
from cogs.helpers import (
    Colors, BLANK_COLOR, CSRP_ICON, CSRP_BANNER, CHECK, CROSS, PENDING,
    success_embed, error_embed, info_embed, warning_embed, brand_footer, embed_description,
    ConfirmView, PaginatorView, generalised_interaction_check_failure, user_tag,
)
from cogs.settings import get_permission_role_ids
from modlog_store import (
    clear_all_modlogs as clear_all_modlogs_db,
    clear_user_modlogs as clear_user_modlogs_db,
    delete_modlog_by_case as delete_modlog_by_case_db,
    get_modlog_by_case as get_modlog_by_case_db,
    get_modlogs_for_user as get_modlogs_for_user_db,
    get_next_case as get_next_case_db,
    save_modlog as save_modlog_db,
)


INFRACTION_THUMBNAIL_URL = "https://media.discordapp.net/attachments/1155943381013368853/1170036267141054494/cachedImage.png?"
USER_ID_PATTERN = re.compile(r"^(?:<@!?)?(\d{15,20})>?$")
IMPORT_CASE_PATTERN = re.compile(r"case\s*#?\s*(\d+)", re.IGNORECASE)
IMPORT_USER_ID_PATTERN = re.compile(r"`?(\d{15,20})`?")
LEGACY_MODERATION_BOT_ID = 632774404165599262
LEGACY_MODERATION_CHANNEL_ID = 1317814337532072027
ACTION_NORMALIZATION = {
    "warn": "Warning",
    "warning": "Warning",
    "kick": "Kick",
    "ban": "Ban",
    "softban": "Softban",
    "unban": "Unban",
    "mute": "Mute",
    "unmute": "Unmute",
    "timeout": "Mute",
    "untimeout": "Unmute",
}


def save_modlog(user_id, action, reason, moderator_id, case_id):
    save_modlog_db(user_id, action, reason, moderator_id, case_id)


def clear_user_modlogs(user_id):
    clear_user_modlogs_db(user_id)


def clear_all_modlogs_data():
    clear_all_modlogs_db()


def parse_time(time_str):
    match = re.compile(r'(\d+)([mhdw])').fullmatch(time_str.strip().lower())
    if not match:
        return None
    value, unit = match.groups()
    value = int(value)
    return {'m': value * 60, 'h': value * 3600, 'd': value * 86400, 'w': value * 604800}.get(unit)


def get_next_case():
    return get_next_case_db()


def _extract_import_user_id(value: str) -> int | None:
    match = IMPORT_USER_ID_PATTERN.search(str(value or ""))
    if match:
        return int(match.group(1))
    return None


def _extract_import_case_id(*values: str) -> int | None:
    for value in values:
        match = IMPORT_CASE_PATTERN.search(str(value or ""))
        if match:
            return int(match.group(1))
    return None


def _normalize_import_action(title: str) -> str | None:
    raw_title = str(title or "").strip()
    if not raw_title:
        return None
    action_text = raw_title.split("|", 1)[0].split("<-", 1)[0].strip(" -:")
    normalized_key = action_text.lower().replace(" ", "")
    return ACTION_NORMALIZATION.get(normalized_key) or action_text


def _parse_imported_modlog(message: discord.Message, embed: discord.Embed) -> dict | None:
    field_map = {
        str(field.name).strip().lower().rstrip(":"): str(field.value).strip()
        for field in embed.fields
    }
    action = _normalize_import_action(embed.title or "")
    case_id = _extract_import_case_id(embed.title or "", embed.description or "")
    user_id = _extract_import_user_id(field_map.get("member", ""))
    moderator_id = _extract_import_user_id(field_map.get("moderator", ""))
    reason = field_map.get("reason", "").strip()

    if case_id is None:
        case_id = _extract_import_case_id(*(field_map.values()))

    if not action or case_id is None or user_id is None or moderator_id is None or not reason:
        return None

    return {
        "user_id": user_id,
        "action": action,
        "reason": reason,
        "moderator_id": moderator_id,
        "case_id": case_id,
        "timestamp": int(message.created_at.timestamp()),
    }


def _format_sync_elapsed(started_at: float) -> str:
    elapsed = max(0, int(time.monotonic() - started_at))
    minutes, seconds = divmod(elapsed, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}h {minutes}m {seconds}s"
    if minutes:
        return f"{minutes}m {seconds}s"
    return f"{seconds}s"


def _build_moderation_sync_embed(
    guild: discord.Guild,
    *,
    title: str,
    status: str,
    color: int,
    percent: int,
    scanned_channels: int,
    total_channels: int,
    scanned_messages: int,
    candidate_embeds: int,
    imported_logs: int,
    duplicate_logs: int,
    invalid_logs: int,
    unreadable_channels: int,
    started_at: float,
    failure_reason: str | None = None,
) -> discord.Embed:
    details = (
        f"> **Status:** {status}\n"
        f"> **Progress:** `{percent}%`\n"
        f"> **Channels Scanned:** `{scanned_channels}/{total_channels}`\n"
        f"> **Messages Scanned:** `{scanned_messages}`\n"
        f"> **Candidate Embeds:** `{candidate_embeds}`\n"
        f"> **Imported Logs:** `{imported_logs}`\n"
        f"> **Skipped Duplicates:** `{duplicate_logs}`\n"
        f"> **Skipped Invalid:** `{invalid_logs}`\n"
        f"> **Unreadable Channels:** `{unreadable_channels}`\n"
        f"> **Elapsed:** `{_format_sync_elapsed(started_at)}`"
    )
    if failure_reason:
        details += f"\n> **Failure:** {failure_reason}"

    embed = discord.Embed(
        title=title,
        description=details,
        color=color,
        timestamp=discord.utils.utcnow(),
    )
    embed.set_author(name=guild.name, icon_url=guild.icon.url if guild.icon else CSRP_ICON)
    brand_footer(embed)
    return embed


def build_infraction_embed(user: discord.abc.User, action: str, reason: str, signed_by: discord.Member) -> discord.Embed:
    infraction_embed = discord.Embed(
        color=discord.Color.blue(),
        title="__CSRP Infraction__",
        description=(
            f"**━━━━━━━━━━━━━━━━━━━━━**\n\n"
            f"**User:** {user.mention}\n\n"
            f"**━━━━━━━━━━━━━━━━━━━━━**\n\n"
            f"**Action:** {action}\n\n"
            f"**━━━━━━━━━━━━━━━━━━━━━**\n \n"
            f"**Reason:** {reason}\n\n"
            f"**━━━━━━━━━━━━━━━━━━━━━**"
        ),
    )
    infraction_embed.set_footer(text=f"Signed By: {signed_by}", icon_url=signed_by.display_avatar.url)
    infraction_embed.set_thumbnail(url=INFRACTION_THUMBNAIL_URL)
    return infraction_embed


class Moderation(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.infractions = {}
        self._moderation_sync_jobs: dict[int, asyncio.Lock] = {}

    def _get_moderation_sync_lock(self, guild_id: int) -> asyncio.Lock:
        lock = self._moderation_sync_jobs.get(guild_id)
        if lock is None:
            lock = asyncio.Lock()
            self._moderation_sync_jobs[guild_id] = lock
        return lock

    @staticmethod
    def _is_protected_moderator(member: discord.Member) -> bool:
        moderation_role_ids = set(get_permission_role_ids(member.guild.id, "moderation"))
        return bool({role.id for role in member.roles} & moderation_role_ids)

    @staticmethod
    def _bypasses_restrictions(ctx) -> bool:
        return ctx.author.id in RESTRICTION_BYPASS_USER_IDS

    async def _resolve_infraction_target(self, guild: discord.Guild, value: str) -> discord.abc.User:
        raw_value = str(value or "").strip()
        match = USER_ID_PATTERN.fullmatch(raw_value)
        if match:
            user_id = int(match.group(1))
            member = guild.get_member(user_id)
            if member is not None:
                return member
            try:
                return await self.bot.fetch_user(user_id)
            except discord.NotFound as exc:
                raise commands.BadArgument(f"No Discord user found with ID `{user_id}`.") from exc
            except discord.HTTPException as exc:
                raise commands.BadArgument(f"Failed to fetch Discord user with ID `{user_id}`.") from exc

        member = guild.get_member_named(raw_value)
        if member is not None:
            return member

        lowered = raw_value.lower().lstrip("@")
        for member in guild.members:
            if member.name.lower() == lowered or member.display_name.lower() == lowered:
                return member

        raise commands.BadArgument(
            f"Could not find a server member or Discord user matching `{raw_value}`. Use a user ID or mention."
        )

    @commands.hybrid_command(name="void", description="Void a specific case and remove it from the user's modlogs.")
    @is_moderation()
    @app_commands.describe(case_number="The case number to void")
    async def void(self, ctx, case_number: int):
        log = get_modlog_by_case_db(case_number)
        if log is None:
            await ctx.send(embed=error_embed("Case Not Found", f"No case found with number `#{case_number}`."))
            return

        if not delete_modlog_by_case_db(case_number):
            await ctx.send(embed=error_embed("Void Failed", f"Failed to void case `#{case_number}`. Please try again."))
            return

        embed = discord.Embed(
            title="Case Voided",
            description=(
                f"Case `#{case_number}` has been voided and removed from <@{log['user_id']}>'s modlogs.\n\n"
                f"> **Action:** {log['action'].capitalize()}\n"
                f"> **Reason:** {log['reason']}\n"
                f"> **Moderator:** <@{log['moderator_id']}>\n"
                f"> **Date:** <t:{log['timestamp']}:f>\n"
                f"> **Voided By:** {ctx.author.mention}"
            ),
            color=BLANK_COLOR,
        )
        embed.set_author(name=ctx.guild.name, icon_url=ctx.guild.icon.url if ctx.guild.icon else "")
        brand_footer(embed)
        await ctx.send(embed=embed)

    @commands.hybrid_command(name="clear_modlogs", description="Clear modlogs for a specific user.")
    @is_moderation()
    @app_commands.describe(user="The user whose modlogs you want to clear")
    async def clear_modlogs(self, ctx, user: discord.Member):
        clear_user_modlogs(user.id)
        await ctx.send(embed=success_embed("Modlogs Cleared", f"Modlogs for **{user.name}** have been cleared."))

    @commands.hybrid_command(name="clear_all_modlogs", description="Clear all modlogs in the system.")
    @is_bot_dev()
    async def clear_all_modlogs(self, ctx):
        view = ConfirmView(ctx.author, timeout=15)
        embed = discord.Embed(
            title="Confirm Clear All Modlogs",
            description=(
                f"This will permanently delete **all** moderation logs.\n\n"
                f"> **Requested By:** {ctx.author.mention}\n"
                f"> **Action:** Clear all modlogs"
            ),
            color=BLANK_COLOR,
        )
        embed.set_author(name=ctx.guild.name, icon_url=ctx.guild.icon.url if ctx.guild.icon else "")
        brand_footer(embed)
        msg = await ctx.send(embed=embed, view=view)
        view.message = msg
        await view.wait()
        if view.value:
            clear_all_modlogs_data()
            await msg.edit(embed=success_embed("Modlogs Cleared", "All modlogs have been cleared."), view=None)
        else:
            await msg.edit(embed=error_embed("Action Cancelled", "The action has been cancelled."), view=None)

    @commands.hybrid_command(name="modlogs", description="View modlogs of a user.")
    @is_moderation()
    @app_commands.describe(user="The user whose modlogs you want to view")
    async def modlogs(self, ctx, user: discord.Member):
        if isinstance(user, int):
            try:
                user = await self.bot.fetch_user(user)
            except discord.NotFound:
                await ctx.send(embed=error_embed("User Not Found", f"No user found with ID `{user}`."))
                return
            except discord.HTTPException:
                await ctx.send(embed=error_embed("Fetch Failed", f"Failed to fetch user with ID `{user}`."))
                return

        user_logs = get_modlogs_for_user_db(user.id)
        if not user_logs:
            await ctx.send(embed=error_embed("No Modlogs Found", f"No modlogs found for **{user.name}**."))
            return

        per_page = 5
        pages = []
        for i in range(0, len(user_logs), per_page):
            chunk = user_logs[i:i + per_page]
            embed = discord.Embed(
                title=f"Modlogs — {user.name}",
                description="\n\n".join(
                    (
                        f"**Case #{log['case_id']} — {log['action'].capitalize()}**\n"
                        f"> **Moderator:** <@{log['moderator_id']}>\n"
                        f"> **Reason:** {log['reason']}\n"
                        f"> **Date:** <t:{log['timestamp']}:f>"
                    )
                    for log in chunk
                ),
                color=BLANK_COLOR,
            )
            embed.set_author(name=ctx.guild.name, icon_url=ctx.guild.icon.url if ctx.guild.icon else "")
            embed.set_thumbnail(url=user.display_avatar.url)
            brand_footer(embed)
            pages.append(embed)

        if len(pages) == 1:
            await ctx.send(embed=pages[0])
        else:
            view = PaginatorView(pages, ctx.author)
            msg = await ctx.send(embed=pages[0], view=view)
            view.message = msg

    async def _run_moderation_sync(
        self,
        guild: discord.Guild,
        source_channel: discord.abc.Messageable,
        progress_message: discord.Message,
    ) -> dict[str, int]:
        progress_state = {
            "scanned_channels": 0,
            "scanned_messages": 0,
            "candidate_embeds": 0,
            "imported_logs": 0,
            "duplicate_logs": 0,
            "invalid_logs": 0,
            "unreadable_channels": 0,
            "status": "Scanning legacy channel history...",
            "failure_reason": None,
            "done": False,
        }
        started_at = time.monotonic()

        async def update_progress_loop():
            while not progress_state["done"]:
                await asyncio.sleep(15)
                if progress_state["done"]:
                    break
                embed = _build_moderation_sync_embed(
                    guild,
                    title="Moderation Sync In Progress",
                    status=progress_state["status"],
                    color=BLANK_COLOR,
                    percent=99 if progress_state["scanned_messages"] > 0 else 0,
                    scanned_channels=progress_state["scanned_channels"],
                    total_channels=1,
                    scanned_messages=progress_state["scanned_messages"],
                    candidate_embeds=progress_state["candidate_embeds"],
                    imported_logs=progress_state["imported_logs"],
                    duplicate_logs=progress_state["duplicate_logs"],
                    invalid_logs=progress_state["invalid_logs"],
                    unreadable_channels=progress_state["unreadable_channels"],
                    started_at=started_at,
                    failure_reason=progress_state["failure_reason"],
                )
                with contextlib.suppress(discord.HTTPException):
                    await progress_message.edit(embed=embed)

        progress_task = asyncio.create_task(update_progress_loop())
        try:
            progress_state["status"] = f"Scanning <#{LEGACY_MODERATION_CHANNEL_ID}> for messages from <@{LEGACY_MODERATION_BOT_ID}>..."
            try:
                async for message in source_channel.history(limit=None, oldest_first=True):
                    progress_state["scanned_messages"] += 1
                    if message.author.id != LEGACY_MODERATION_BOT_ID or not message.embeds:
                        continue

                    for embed_index, embed in enumerate(message.embeds):
                        progress_state["candidate_embeds"] += 1
                        parsed_log = _parse_imported_modlog(message, embed)
                        if parsed_log is None:
                            progress_state["invalid_logs"] += 1
                            continue

                        inserted = save_modlog_db(
                            parsed_log["user_id"],
                            parsed_log["action"],
                            parsed_log["reason"],
                            parsed_log["moderator_id"],
                            parsed_log["case_id"],
                            timestamp=parsed_log["timestamp"],
                            source="legacy-bot-import",
                            source_guild_id=guild.id,
                            source_channel_id=LEGACY_MODERATION_CHANNEL_ID,
                            source_message_id=message.id if embed_index == 0 else None,
                            skip_duplicates=True,
                        )
                        if inserted:
                            progress_state["imported_logs"] += 1
                        else:
                            progress_state["duplicate_logs"] += 1
            except (discord.Forbidden, discord.HTTPException) as exc:
                progress_state["unreadable_channels"] += 1
                progress_state["failure_reason"] = str(exc)
            finally:
                progress_state["scanned_channels"] = 1
        finally:
            progress_state["done"] = True
            progress_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await progress_task

        return progress_state

    @commands.hybrid_command(
        name="moderationsync",
        description="Import moderation embeds from the legacy moderation bot into the modlog database.",
    )
    @is_bot_dev()
    async def moderationsync(self, ctx: commands.Context):
        if ctx.guild is None:
            await ctx.send(embed=error_embed("Server Only", "This command can only be used in a server."))
            return

        if ctx.interaction and not ctx.interaction.response.is_done():
            await ctx.defer()

        lock = self._get_moderation_sync_lock(ctx.guild.id)
        if lock.locked():
            await ctx.send(
                embed=warning_embed("Sync Already Running", "A moderation sync is already in progress for this server."),
            )
            return

        source_channel = ctx.guild.get_channel(LEGACY_MODERATION_CHANNEL_ID)
        if source_channel is None:
            try:
                source_channel = await self.bot.fetch_channel(LEGACY_MODERATION_CHANNEL_ID)
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                source_channel = None

        if source_channel is None or getattr(source_channel, "guild", None) != ctx.guild:
            await ctx.send(embed=error_embed("Channel Not Found", f"I could not access <#{LEGACY_MODERATION_CHANNEL_ID}> in this server."))
            return

        me = ctx.guild.me or ctx.guild.get_member(self.bot.user.id if self.bot.user else 0)
        permissions = source_channel.permissions_for(me) if me and hasattr(source_channel, "permissions_for") else None
        if not permissions or not permissions.view_channel or not permissions.read_message_history:
            await ctx.send(embed=error_embed("Missing Permissions", f"I need `View Channel` and `Read Message History` in <#{LEGACY_MODERATION_CHANNEL_ID}>."))
            return

        started_at = time.monotonic()
        initial_embed = _build_moderation_sync_embed(
            ctx.guild,
            title="Moderation Sync Starting",
            status=f"Preparing to scan <#{LEGACY_MODERATION_CHANNEL_ID}> for embeds from <@{LEGACY_MODERATION_BOT_ID}>.",
            color=BLANK_COLOR,
            percent=0,
            scanned_channels=0,
            total_channels=1,
            scanned_messages=0,
            candidate_embeds=0,
            imported_logs=0,
            duplicate_logs=0,
            invalid_logs=0,
            unreadable_channels=0,
            started_at=started_at,
            failure_reason=None,
        )
        progress_message = await ctx.channel.send(
            content=f"{ctx.author.mention} moderation sync started.",
            embed=initial_embed,
        )

        if ctx.interaction:
            with contextlib.suppress(discord.HTTPException):
                await ctx.send(
                    embed=info_embed(
                        "Moderation Sync Started",
                        f"I started the import in {ctx.channel.mention}. I will keep updating {progress_message.jump_url}.",
                    ),
                )

        async with lock:
            results = await self._run_moderation_sync(ctx.guild, source_channel, progress_message)

        completed_embed = _build_moderation_sync_embed(
            ctx.guild,
            title="Moderation Sync Complete",
            status=f"Finished scanning <#{LEGACY_MODERATION_CHANNEL_ID}> for embeds from <@{LEGACY_MODERATION_BOT_ID}>.",
            color=BLANK_COLOR,
            percent=100,
            scanned_channels=results["scanned_channels"],
            total_channels=1,
            scanned_messages=results["scanned_messages"],
            candidate_embeds=results["candidate_embeds"],
            imported_logs=results["imported_logs"],
            duplicate_logs=results["duplicate_logs"],
            invalid_logs=results["invalid_logs"],
            unreadable_channels=results["unreadable_channels"],
            started_at=started_at,
            failure_reason=results["failure_reason"],
        )
        await progress_message.edit(content=f"{ctx.author.mention} moderation sync finished.", embed=completed_embed)

    @commands.hybrid_command(name="kick", description="Kicks a member from the server.")
    @is_moderation()
    @app_commands.describe(user="The user to kick", reason="The reason for kicking the user")
    async def kick(self, ctx, user: discord.Member, *, reason: str | None = None):
        if self._is_protected_moderator(user):
            await ctx.send(embed=error_embed("Cannot Kick User", "I cannot kick other moderators or administrators."))
            return

        if not reason:
            await ctx.send(embed=error_embed("Missing Argument", "Missing required argument: `reason`"))
            return

        case = get_next_case()

        try:
            dm = await user.create_dm()
            await dm.send(f"**Case #{case}** — You have been kicked from California State Roleplay for: {reason}.")
        except discord.Forbidden:
            pass

        await user.kick(reason=reason)
        save_modlog(user.id, "Kick", reason, ctx.author.id, case)

        if ctx.message:
            try:
                await ctx.message.delete()
            except (discord.NotFound, discord.Forbidden):
                pass

        embed = discord.Embed(
            title="User Kicked",
            description=embed_description(
                (
                    f"> **Staff Member:** {user_tag(ctx.author)}\n"
                    f"> **User:** {user_tag(user)}\n"
                    f"> **Case:** `#{case}`"
                ),
                (
                    f"> **Reason:** {reason}\n"
                    f"> **Date:** <t:{int(time.time())}:f>"
                ),
            ),
            color=BLANK_COLOR,
        )
        embed.set_author(name=ctx.guild.name, icon_url=ctx.guild.icon.url if ctx.guild.icon else "")
        embed.set_thumbnail(url=user.display_avatar.url)
        brand_footer(embed)
        await ctx.send(embed=embed)

    @commands.hybrid_command(name="ban", description="Bans a user from the server.")
    @is_role_authorized()
    @app_commands.describe(user="The user to ban", reason="The reason for banning the user")
    async def ban(self, ctx, user, *, reason: str | None = None):
        ignore_restrictions = self._bypasses_restrictions(ctx)

        user_id = None

        if isinstance(user, discord.Member):
            if not ignore_restrictions and self._is_protected_moderator(user):
                await ctx.send(embed=error_embed("Cannot Ban User", "I cannot ban other moderators or administrators."))
                return
            member_to_ban = user
            user_id = user.id
        else:
            try:
                cleaned = str(user).strip("<@!>")
                user_id = int(cleaned)
            except ValueError:
                await ctx.send(embed=error_embed("Invalid User ID", "The provided user ID is not valid."))
                return

            try:
                member_to_ban = await ctx.guild.fetch_member(user_id)
                if not ignore_restrictions and self._is_protected_moderator(member_to_ban):
                    await ctx.send(embed=error_embed("Cannot Ban User", "I cannot ban other moderators or administrators."))
                    return
            except discord.NotFound:
                member_to_ban = None

        if not reason:
            await ctx.send(embed=error_embed("Missing Argument", "Missing required argument: `reason`"))
            return

        case = get_next_case()
        ban_message = f"**Case #{case}** — You have been banned from California State Roleplay for: {reason}."

        dm_failed = False
        if member_to_ban:
            try:
                dm = await member_to_ban.create_dm()
                await dm.send(ban_message)
            except (discord.Forbidden, discord.HTTPException):
                dm_failed = True
            await member_to_ban.ban(reason=reason)
        else:
            try:
                await ctx.guild.ban(discord.Object(id=user_id), reason=reason)
            except discord.Forbidden:
                await ctx.send(embed=error_embed("Missing Permissions", "I don't have permission to ban this user."))
                return

        save_modlog(user_id, "Ban", reason, ctx.author.id, case)

        if ctx.message:
            try:
                await ctx.message.delete()
            except (discord.NotFound, discord.Forbidden):
                pass

        other_info = (
            f"> **Reason:** {reason}\n"
            f"> **Date:** <t:{int(time.time())}:f>"
        )
        if dm_failed:
            other_info += "\n> **Note:** Could not DM the user"
        banned_user_tag = user_tag(member_to_ban, fallback_name="unknown-user") if member_to_ban else f"`@unknown-user | {user_id}`"
        embed = discord.Embed(
            title="User Banned",
            description=embed_description(
                (
                    f"> **Staff Member:** {user_tag(ctx.author)}\n"
                    f"> **User:** {banned_user_tag}\n"
                    f"> **Case:** `#{case}`"
                ),
                other_info,
            ),
            color=BLANK_COLOR,
        )
        embed.set_author(name=ctx.guild.name, icon_url=ctx.guild.icon.url if ctx.guild.icon else "")
        if member_to_ban and hasattr(member_to_ban, 'display_avatar'):
            embed.set_thumbnail(url=member_to_ban.display_avatar.url)
        brand_footer(embed)
        await ctx.send(embed=embed)

    @commands.hybrid_command(name="softban", description="Softbans a user (bans and immediately unbans to delete messages).")
    @is_role_authorized()
    @app_commands.describe(user="The user to softban", reason="The reason for softbanning the user")
    async def softban(self, ctx, user, *, reason: str | None = None):
        ignore_restrictions = self._bypasses_restrictions(ctx)

        user_id = None

        if isinstance(user, discord.Member):
            if not ignore_restrictions and self._is_protected_moderator(user):
                await ctx.send(embed=error_embed("Cannot Softban User", "I cannot softban other moderators or administrators."))
                return
            member_to_ban = user
            user_id = user.id
        else:
            try:
                cleaned = str(user).strip("<@!>")
                user_id = int(cleaned)
            except ValueError:
                await ctx.send(embed=error_embed("Invalid User ID", "The provided user ID is not valid."))
                return

            try:
                member_to_ban = await ctx.guild.fetch_member(user_id)
                if not ignore_restrictions and self._is_protected_moderator(member_to_ban):
                    await ctx.send(embed=error_embed("Cannot Softban User", "I cannot softban other moderators or administrators."))
                    return
            except discord.NotFound:
                member_to_ban = None

        if not reason:
            await ctx.send(embed=error_embed("Missing Argument", "Missing required argument: `reason`"))
            return

        case = get_next_case()
        softban_message = f"**Case #{case}** — You have been softbanned from California State Roleplay for: {reason}."

        dm_failed = False
        if member_to_ban:
            try:
                dm = await member_to_ban.create_dm()
                await dm.send(softban_message)
            except (discord.Forbidden, discord.HTTPException):
                dm_failed = True
            await member_to_ban.ban(reason=f"Softban: {reason}", delete_message_days=7)
        else:
            try:
                await ctx.guild.ban(discord.Object(id=user_id), reason=f"Softban: {reason}", delete_message_days=7)
            except discord.Forbidden:
                await ctx.send(embed=error_embed("Missing Permissions", "I don't have permission to ban this user."))
                return

        try:
            await ctx.guild.unban(discord.Object(id=user_id), reason=f"Softban unban: {reason}")
        except discord.HTTPException:
            pass

        save_modlog(user_id, "Softban", reason, ctx.author.id, case)

        if ctx.message:
            try:
                await ctx.message.delete()
            except (discord.NotFound, discord.Forbidden):
                pass

        other_info = (
            f"> **Reason:** {reason}\n"
            f"> **Date:** <t:{int(time.time())}:f>"
        )
        if dm_failed:
            other_info += "\n> **Note:** Could not DM the user"
        banned_user_tag = user_tag(member_to_ban, fallback_name="unknown-user") if member_to_ban else f"`@unknown-user | {user_id}`"
        embed = discord.Embed(
            title="User Softbanned",
            description=embed_description(
                (
                    f"> **Staff Member:** {user_tag(ctx.author)}\n"
                    f"> **User:** {banned_user_tag}\n"
                    f"> **Case:** `#{case}`"
                ),
                other_info,
            ),
            color=BLANK_COLOR,
        )
        embed.set_author(name=ctx.guild.name, icon_url=ctx.guild.icon.url if ctx.guild.icon else "")
        if member_to_ban and hasattr(member_to_ban, 'display_avatar'):
            embed.set_thumbnail(url=member_to_ban.display_avatar.url)
        brand_footer(embed)
        await ctx.send(embed=embed)

    @commands.hybrid_command(name="unban", description="Unban a user from the server.")
    @is_role_authorized()
    @app_commands.describe(user_id="The user to unban", reason="The reason for unbanning the user")
    async def unban(self, ctx, user_id: int, reason: str):
        banned_users = [ban_entry.user.id async for ban_entry in ctx.guild.bans()]
        if user_id not in banned_users:
            await ctx.send(embed=error_embed("User Not Banned", "That user is not banned from the server."))
            return

        case = get_next_case()

        try:
            user = await self.bot.fetch_user(user_id)
        except discord.NotFound:
            await ctx.send(embed=error_embed("User Not Found", "The specified user could not be found."))
            return

        await ctx.guild.unban(user)
        save_modlog(user.id, "Unban", reason, ctx.author.id, case)

        if ctx.message:
            try:
                await ctx.message.delete()
            except (discord.NotFound, discord.Forbidden):
                pass

        embed = discord.Embed(
            title="User Unbanned",
            description=embed_description(
                (
                    f"> **Staff Member:** {user_tag(ctx.author)}\n"
                    f"> **User:** {user_tag(user)}\n"
                    f"> **Case:** `#{case}`"
                ),
                (
                    f"> **Reason:** {reason}\n"
                    f"> **Date:** <t:{int(time.time())}:f>"
                ),
            ),
            color=BLANK_COLOR,
        )
        embed.set_author(name=ctx.guild.name, icon_url=ctx.guild.icon.url if ctx.guild.icon else "")
        brand_footer(embed)
        await ctx.send(embed=embed)

    @commands.hybrid_command(name="mute", description="Mutes a user.")
    @is_moderation()
    @app_commands.describe(user="The user to mute", time="Duration (e.g. 10m, 2h, 1d, 1w)", reason="The reason for mute")
    async def mute(self, ctx, user: discord.Member, time: str | None = None, *, reason: str | None = None):
        if not self._bypasses_restrictions(ctx) and self._is_protected_moderator(user):
            await ctx.send(embed=error_embed("Cannot Mute User", "I cannot mute other moderators or administrators."))
            return

        if not time:
            await ctx.send(embed=error_embed("Missing Argument", "Missing required argument: `time`"))
            return

        if not reason:
            await ctx.send(embed=error_embed("Missing Argument", "Missing required argument: `reason`"))
            return

        mute_duration = parse_time(time)
        if mute_duration is None:
            await ctx.send(embed=error_embed("Invalid Time Format", "Use `m`, `h`, `d`, or `w` (e.g. `10m`, `2h`, `1d`)."))
            return

        case = get_next_case()
        await user.timeout(timedelta(seconds=mute_duration), reason=reason)
        save_modlog(user.id, "Mute", reason, ctx.author.id, case)

        if ctx.message:
            try:
                await ctx.message.delete()
            except (discord.NotFound, discord.Forbidden):
                pass

        import time as time_mod
        current_ts = int(time_mod.time())
        embed = discord.Embed(
            title="User Muted",
            description=embed_description(
                (
                    f"> **Staff Member:** {user_tag(ctx.author)}\n"
                    f"> **User:** {user_tag(user)}\n"
                    f"> **Case:** `#{case}`"
                ),
                (
                    f"> **Reason:** {reason}\n"
                    f"> **Duration:** `{time}`\n"
                    f"> **Date:** <t:{current_ts}:f>"
                ),
            ),
            color=BLANK_COLOR,
        )
        embed.set_author(name=ctx.guild.name, icon_url=ctx.guild.icon.url if ctx.guild.icon else "")
        embed.set_thumbnail(url=user.display_avatar.url)
        brand_footer(embed)
        await ctx.send(embed=embed)

    @commands.hybrid_command(name="unmute", description="Unmutes a user.")
    @is_moderation()
    @app_commands.describe(user="The user to unmute", reason="The reason for unmute")
    async def unmute(self, ctx, user: discord.Member, reason: str):
        case = get_next_case()
        await user.timeout(None, reason=reason)
        save_modlog(user.id, "Unmute", reason, ctx.author.id, case)

        if ctx.message:
            try:
                await ctx.message.delete()
            except (discord.NotFound, discord.Forbidden):
                pass

        embed = discord.Embed(
            title="User Unmuted",
            description=embed_description(
                (
                    f"> **Staff Member:** {user_tag(ctx.author)}\n"
                    f"> **User:** {user_tag(user)}\n"
                    f"> **Case:** `#{case}`"
                ),
                (
                    f"> **Reason:** {reason}\n"
                    f"> **Date:** <t:{int(time.time())}:f>"
                ),
            ),
            color=BLANK_COLOR,
        )
        embed.set_author(name=ctx.guild.name, icon_url=ctx.guild.icon.url if ctx.guild.icon else "")
        embed.set_thumbnail(url=user.display_avatar.url)
        brand_footer(embed)
        await ctx.send(embed=embed)

    @commands.hybrid_command(name="warn", description="Warns a user.")
    @is_moderation()
    @app_commands.describe(user="The user to warn", reason="The reason for the warning")
    async def warn(self, ctx, user: discord.Member, *, reason: str | None = None):
        if not self._bypasses_restrictions(ctx) and self._is_protected_moderator(user):
            await ctx.send(embed=error_embed("Cannot Warn User", "I cannot warn other moderators or administrators."))
            return

        if not reason:
            await ctx.send(embed=error_embed("Missing Argument", "Missing required argument: `reason`"))
            return

        case = get_next_case()
        save_modlog(user.id, "Warning", reason, ctx.author.id, case)

        try:
            dm_embed = discord.Embed(
                title="Warning Received",
                description=embed_description(
                    "You have received a warning in **California State Roleplay**.",
                    (
                        f"> **Case:** `#{case}`\n"
                        f"> **Reason:** {reason}"
                    ),
                ),
                color=BLANK_COLOR,
            )
            dm_embed.set_author(name="California State Roleplay", icon_url=CSRP_ICON)
            brand_footer(dm_embed)
            await user.send(embed=dm_embed)
        except discord.Forbidden:
            pass

        if ctx.message:
            try:
                await ctx.message.delete()
            except (discord.NotFound, discord.Forbidden):
                pass

        embed = discord.Embed(
            title="Warning Issued",
            description=embed_description(
                (
                    f"> **Staff Member:** {user_tag(ctx.author)}\n"
                    f"> **User:** {user_tag(user)}\n"
                    f"> **Case:** `#{case}`"
                ),
                (
                    f"> **Reason:** {reason}\n"
                    f"> **Date:** <t:{int(time.time())}:f>"
                ),
            ),
            color=BLANK_COLOR,
        )
        embed.set_author(name=ctx.guild.name, icon_url=ctx.guild.icon.url if ctx.guild.icon else "")
        embed.set_thumbnail(url=user.display_avatar.url)
        brand_footer(embed)
        await ctx.send(embed=embed)

    @commands.hybrid_command(name="infract", description="Infracts a user.")
    @is_role_authorized()
    @app_commands.describe(member="The user to infract. Supports a member, user ID, or mention.")
    async def infract(self, ctx, member: str, punishment: str, *, reason: str):
        infract_channel = self.bot.get_channel(INFRACTION_CHANNEL)
        if infract_channel is None:
            await ctx.send(embed=error_embed("Channel Not Found", "The infraction channel could not be found."))
            return

        try:
            target = await self._resolve_infraction_target(ctx.guild, member)
        except commands.BadArgument as exc:
            await ctx.send(embed=error_embed("User Not Found", str(exc)))
            return

        ref_id = random.randint(100000, 999999)

        self.infractions[ref_id] = {
            "user": target,
            "action": punishment,
            "reason": reason,
            "infracted_by": ctx.author,
            "appeal": None,
            "reviewer": None,
            "status": None,
        }

        infraction_embed = build_infraction_embed(target, punishment, reason, ctx.author)
        await infract_channel.send(f"<@{target.id}>", embed=infraction_embed, legacy_embeds=True)

        if ctx.message:
            try:
                await ctx.message.delete()
            except (discord.NotFound, discord.Forbidden):
                pass

        dm_embed = discord.Embed(
            title="Infraction Notice",
            description=embed_description(
                "You have been infracted in **California State Roleplay**.",
                (
                    f"> **Punishment:** {punishment}\n"
                    f"> **Reason:** {reason}\n"
                    f"> **Reference ID:** `{ref_id}`"
                ),
                # "Click the button below to appeal this infraction.",
            ),
            color=BLANK_COLOR,
        )
        dm_embed.set_author(name="California State Roleplay", icon_url=CSRP_ICON)
        dm_embed.set_thumbnail(url=CSRP_ICON)
        brand_footer(dm_embed)

        # bot_ref = self.bot
        # infractions_ref = self.infractions
        # infracted_by = ctx.author

        # class AppealModal(discord.ui.Modal):
            # def __init__(self_modal):
                # super().__init__(title="Appeal Infraction", timeout=None)
                # self_modal.punishment_input = discord.ui.TextInput(label="Punishment", placeholder="Enter the punishment", required=True)
                # self_modal.reason_input = discord.ui.TextInput(label="Why should we accept your appeal?", style=discord.TextStyle.paragraph, required=True)
                # self_modal.proof_input = discord.ui.TextInput(label="Related proof (optional)", placeholder="Paste a link here", required=False)
                # self_modal.add_item(self_modal.punishment_input)
                # self_modal.add_item(self_modal.reason_input)
                # self_modal.add_item(self_modal.proof_input)

            # async def on_submit(self_modal, modal_interaction):
                # appeals_channel = bot_ref.get_channel(APPEALS_CHANNEL_ID)
                # if appeals_channel is None:
                    # await modal_interaction.response.send_message(embed=error_embed("Channel Not Found", "The appeals channel could not be found."), ephemeral=True)
                    # return

                # infraction = infractions_ref.get(ref_id)
                # if infraction:
                    # infraction["appeal"] = {
                        # "reason": self_modal.reason_input.value,
                        # "proof": self_modal.proof_input.value or "No proof provided",
                    # }

                # appeal_embed = discord.Embed(
                    # title="New Appeal Submission",
                    # description=embed_description(
                        # (
                            # f"> **Appellant:** {target.mention}\n"
                            # f"> **Reference ID:** `{ref_id}`\n"
                            # f"> **Punishment:** {self_modal.punishment_input.value}"
                        # ),
                        # (
                            # f"> **Reason:** {self_modal.reason_input.value}\n"
                            # f"> **Proof:** {self_modal.proof_input.value or 'No proof provided'}"
                        # ),
                    # ),
                    # color=BLANK_COLOR,
                # )
                # appeal_embed.set_author(name="California State Roleplay", icon_url=CSRP_ICON)
                # appeal_embed.set_thumbnail(url=target.display_avatar.url)
                # brand_footer(appeal_embed)

                # accept_btn = discord.ui.Button(label="Accept", style=discord.ButtonStyle.green)
                # deny_btn = discord.ui.Button(label="Deny", style=discord.ButtonStyle.danger)

                # async def accept_callback(button_interaction):
                    # if infraction:
                        # infraction["status"] = "Accepted"
                        # infraction["reviewer"] = button_interaction.user
                    # accepted_embed = discord.Embed(
                        # title="Appeal Accepted",
                        # description=embed_description(
                            # f"Congratulations, {target.mention}! Your infraction appeal has been accepted.",
                            # (
                                # f"> **Reference ID:** `{ref_id}`\n"
                                # f"> **Reviewed By:** {button_interaction.user.mention}"
                            # ),
                        # ),
                        # color=BLANK_COLOR,
                    # )
                    # accepted_embed.set_author(name="California State Roleplay", icon_url=CSRP_ICON)
                    # brand_footer(accepted_embed)
                    # try:
                        # await target.send(embed=accepted_embed)
                    # except discord.Forbidden:
                        # pass
                    # appeal_embed.title = "Accepted Appeal"
                    # appeal_embed.color = BLANK_COLOR
                    # appeal_embed.description = embed_description(
                        # appeal_embed.description or "",
                        # f"> **Reviewed By:** {button_interaction.user.mention}",
                    # )
                    # await button_interaction.response.edit_message(embed=appeal_embed, view=None)

                # async def deny_callback(button_interaction):
                    # if infraction:
                        # infraction["status"] = "Denied"
                        # infraction["reviewer"] = button_interaction.user
                    # denied_embed = discord.Embed(
                        # title="Appeal Denied",
                        # description=f"Your infraction appeal has been denied. Please open a ticket with ref id `{ref_id}`.",
                        # color=BLANK_COLOR,
                    # )
                    # denied_embed.set_author(name="California State Roleplay", icon_url=CSRP_ICON)
                    # brand_footer(denied_embed)
                    # try:
                        # await target.send(embed=denied_embed)
                    # except discord.Forbidden:
                        # pass
                    # appeal_embed.title = "Denied Appeal"
                    # appeal_embed.color = BLANK_COLOR
                    # appeal_embed.description = embed_description(
                        # appeal_embed.description or "",
                        # f"> **Reviewed By:** {button_interaction.user.mention}",
                    # )
                    # await button_interaction.response.edit_message(embed=appeal_embed, view=None)

                # accept_btn.callback = accept_callback
                # deny_btn.callback = deny_callback

                # review_view = discord.ui.View(timeout=None)
                # review_view.add_item(accept_btn)
                # review_view.add_item(deny_btn)

                # await appeals_channel.send(f"{infracted_by.mention}", embed=appeal_embed, view=review_view)
                # await modal_interaction.response.send_message(
                    # embed=success_embed("Appeal Submitted", f"Your appeal has been submitted. Reference ID: `{ref_id}`"),
                    # ephemeral=True,
                # )

        # appeal_button = discord.ui.Button(label="Appeal Infraction", style=discord.ButtonStyle.primary)

        # async def appeal_button_callback(interaction):
            # await interaction.response.send_modal(AppealModal())

        # appeal_button.callback = appeal_button_callback
        # appeal_view = discord.ui.View(timeout=None)
        # appeal_view.add_item(appeal_button)

        if isinstance(target, discord.Member):
            try:
                # await target.send(embed=dm_embed, view=appeal_view)
                await target.send(embed=dm_embed)
                await ctx.send(embed=success_embed("User Infracted", "The user has been successfully infracted."), delete_after=5)
            except discord.Forbidden:
                await ctx.send(
                    embed=warning_embed("DM Failed", "Unable to DM the user. The infraction embed has still been posted."),
                    ephemeral=True,
                )
            return

        await ctx.send(
            embed=success_embed("User Infracted", "The user has been infracted. No DM was sent because they are not in the server."),
            delete_after=5,
        )

    @commands.hybrid_command(name="lookup", description="Look up an infraction by Ref ID.")
    @is_role_authorized()
    async def lookup(self, ctx, ref_id: int):
        infraction = self.infractions.get(ref_id)
        if not infraction:
            await ctx.send(embed=error_embed("Infraction Not Found", f"No infraction found with Ref ID `{ref_id}`."))
            return

        description_parts = [
            (
                f"> **User:** {infraction['user'].mention}\n"
                f"> **Action:** {infraction['action']}\n"
                f"> **Infracted By:** {infraction['infracted_by'].mention}\n"
                f"> **Reason:** {infraction['reason']}"
            )
        ]
        if infraction["appeal"]:
            description_parts.append(
                (
                    f"> **Appeal Reason:** {infraction['appeal'].get('reason')}\n"
                    f"> **Proof:** {infraction['appeal'].get('proof', 'No proof provided')}"
                )
            )
            if infraction["status"]:
                description_parts.append(
                    (
                        f"> **Status:** {infraction['status']}\n"
                        f"> **Reviewed By:** {infraction['reviewer'].mention}"
                    )
                )
        else:
            description_parts.append("> No appeal has been submitted")
        embed = discord.Embed(
            title=f"Infraction — Ref ID: {ref_id}",
            description=embed_description(*description_parts),
            color=BLANK_COLOR,
        )
        embed.set_author(name=ctx.guild.name, icon_url=ctx.guild.icon.url if ctx.guild.icon else "")
        if hasattr(infraction["user"], 'display_avatar'):
            embed.set_thumbnail(url=infraction["user"].display_avatar.url)

        brand_footer(embed)

        view = discord.ui.View()
        if infraction["appeal"] and infraction["status"] is None:
            accept_button = discord.ui.Button(label="Accept", style=discord.ButtonStyle.green)
            deny_button = discord.ui.Button(label="Deny", style=discord.ButtonStyle.danger)

            async def accept_callback(interaction):
                infraction["status"] = "Accepted"
                infraction["reviewer"] = interaction.user
                accepted_embed = discord.Embed(
                    title="Appeal Accepted",
                    description=embed_description(
                        f"Congratulations, {infraction['user'].mention}! Your infraction appeal has been accepted.",
                        f"> **Reference ID:** `{ref_id}`",
                    ),
                    color=BLANK_COLOR,
                )
                accepted_embed.set_author(name="California State Roleplay", icon_url=CSRP_ICON)
                brand_footer(accepted_embed)
                try:
                    await infraction["user"].send(embed=accepted_embed)
                except discord.Forbidden:
                    pass
                embed.description = embed_description(
                    embed.description or "",
                    (
                        f"> **Status:** Accepted\n"
                        f"> **Reviewed By:** {interaction.user.mention}"
                    ),
                )
                await interaction.response.edit_message(embed=embed, view=None)

            async def deny_callback(interaction):
                infraction["status"] = "Denied"
                infraction["reviewer"] = interaction.user
                denied_embed = discord.Embed(
                    title="Appeal Denied",
                    description=f"Your infraction appeal has been denied. Please open a ticket with ref id `{ref_id}`.",
                    color=BLANK_COLOR,
                )
                denied_embed.set_author(name="California State Roleplay", icon_url=CSRP_ICON)
                brand_footer(denied_embed)
                try:
                    await infraction["user"].send(embed=denied_embed)
                except discord.Forbidden:
                    pass
                embed.description = embed_description(
                    embed.description or "",
                    (
                        f"> **Status:** Denied\n"
                        f"> **Reviewed By:** {interaction.user.mention}"
                    ),
                )
                await interaction.response.edit_message(embed=embed, view=None)

            accept_button.callback = accept_callback
            deny_button.callback = deny_callback
            view.add_item(accept_button)
            view.add_item(deny_button)

        await ctx.send(embed=embed, view=view)


async def setup(bot):
    await bot.add_cog(Moderation(bot))
