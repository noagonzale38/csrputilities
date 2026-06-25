import discord
from discord.ext import commands
from discord import app_commands
import asyncio
import json
import re
import time
from pathlib import Path
from typing import Optional

from config import INFRACTION_CHANNEL, feedback_blacklists, is_bot_dev
from cogs.helpers import (
    BLANK_COLOR, CSRP_ICON,
    brand_footer, success_embed, error_embed, warning_embed, embed_description, ConfirmView, user_tag,
)
from cogs.moderation import build_infraction_embed
from cogs.settings import get_guild_settings, has_setting_permission, RANK_ORDER, member_has_rank_or_higher

RETIREMENTS_FILE = "retirements.json"
STAFF_FEEDBACK_STATS_FILE = Path(__file__).resolve().parent.parent / "staff_feedback_stats.json"
BASE_ROLE_BY_RANK = {
    "Senior Management": 1131166127964291172,
    "Management": 1131166127964291172,
    "Internal Affairs Supervisor": 1137119576514105404,
    "Internal Affairs": 1137119576514105404,
    "Senior Admin": 968848542347173908,
    "Admin": 968848542347173908,
    "Junior Admin": 968848542347173908,
    "Senior Moderator": 968851098221813770,
    "Moderator": 968851098221813770,
}
EXTRA_ROLE_IDS_BY_RANK = {
    "Senior Management": [1157648329619021844],
    "Management": [1157648329619021844],
    "Internal Affairs Supervisor": [1137117556348567614],
    "Internal Affairs": [1137117556348567614],
}

DEMOTION_MAP = {}
for i in range(len(RANK_ORDER) - 1):
    DEMOTION_MAP[RANK_ORDER[i]] = RANK_ORDER[i + 1]

RATING_PATTERNS = (
    re.compile(r"\b(?:rating|score)\s*[:=-]?\s*`?(10|[1-9])(?:\s*/\s*10)?`?\b", re.IGNORECASE),
    re.compile(r"\b(10|[1-9])\s*/\s*10\b"),
)
MENTION_PATTERN = re.compile(r"<@!?(\d+)>")


def load_retirements() -> dict:
    try:
        with open(RETIREMENTS_FILE, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_retirements(data: dict):
    with open(RETIREMENTS_FILE, "w") as f:
        json.dump(data, f, indent=4)


def load_staff_feedback_stats() -> dict:
    try:
        with open(STAFF_FEEDBACK_STATS_FILE, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_staff_feedback_stats(data: dict):
    with open(STAFF_FEEDBACK_STATS_FILE, "w") as f:
        json.dump(data, f, indent=4)


def load_feedback_blacklist() -> set[int]:
    try:
        with open(feedback_blacklists, "r") as f:
            return {
                int(match.group(1))
                for line in f
                if (match := re.search(r"\{userid:\s*(\d+)\}", line.strip()))
            }
    except FileNotFoundError:
        return set()


def append_feedback_blacklist_user(user_id: int):
    with open(feedback_blacklists, "a") as f:
        f.write(f"{{userid: {user_id}}}\n")


def save_retirement(guild_id: int, user_id: int, entry: dict):
    data = load_retirements()
    gkey = str(guild_id)
    if gkey not in data:
        data[gkey] = {}
    data[gkey][str(user_id)] = entry
    save_retirements(data)


def get_retirement(guild_id: int, user_id: int):
    data = load_retirements()
    gkey = str(guild_id)
    if gkey in data:
        return data[gkey].get(str(user_id))
    return None


def remove_retirement(guild_id: int, user_id: int) -> bool:
    data = load_retirements()
    gkey = str(guild_id)
    if gkey in data and str(user_id) in data[gkey]:
        del data[gkey][str(user_id)]
        save_retirements(data)
        return True
    return False


def _extract_rating(text: str) -> Optional[int]:
    for pattern in RATING_PATTERNS:
        match = pattern.search(text or "")
        if match:
            return int(match.group(1))
    return None


def _build_feedback_message_text(message: discord.Message) -> str:
    parts = [message.content or ""]
    for embed in message.embeds:
        parts.extend([
            embed.title or "",
            embed.description or "",
            getattr(embed.author, "name", ""),
            getattr(embed.footer, "text", ""),
        ])
        parts.extend(field.name for field in embed.fields)
        parts.extend(field.value for field in embed.fields)
    return "\n".join(part for part in parts if part)


def _extract_feedback_target_user_id(message: discord.Message) -> Optional[int]:
    mentioned_user_ids = [member.id for member in message.mentions if member.id != message.author.id]
    if len(mentioned_user_ids) == 1:
        return mentioned_user_ids[0]
    if mentioned_user_ids:
        return mentioned_user_ids[0]

    combined = _build_feedback_message_text(message)
    for match in MENTION_PATTERN.finditer(combined):
        user_id = int(match.group(1))
        if user_id != message.author.id:
            return user_id
    return None


def _extract_feedback_rating_from_message(message: discord.Message) -> Optional[int]:
    for embed in message.embeds:
        rating = _extract_rating("\n".join([
            embed.title or "",
            embed.description or "",
            *(field.value for field in embed.fields),
        ]))
        if rating is not None:
            return rating
    return _extract_rating(message.content or "")


def _message_targets_staff(message: discord.Message, staff_member: discord.Member) -> bool:
    if staff_member in message.mentions:
        return True

    mention_tokens = {f"<@{staff_member.id}>", f"<@!{staff_member.id}>"}
    content = message.content or ""
    if any(token in content for token in mention_tokens):
        return True

    candidate_names = {
        staff_member.display_name,
        staff_member.name,
    }
    if staff_member.global_name:
        candidate_names.add(staff_member.global_name)

    lowered = content.lower()
    for name in candidate_names:
        if name and name.lower() in lowered:
            return True

    return False


def _embed_targets_staff(embed: discord.Embed, staff_member: discord.Member) -> bool:
    text_parts = [
        embed.title or "",
        embed.description or "",
        getattr(embed.author, "name", ""),
        getattr(embed.footer, "text", ""),
    ]
    text_parts.extend(field.name for field in embed.fields)
    text_parts.extend(field.value for field in embed.fields)
    combined = "\n".join(part for part in text_parts if part)

    mention_tokens = {f"<@{staff_member.id}>", f"<@!{staff_member.id}>"}
    if any(token in combined for token in mention_tokens):
        return True

    candidate_names = {
        staff_member.display_name,
        staff_member.name,
    }
    if staff_member.global_name:
        candidate_names.add(staff_member.global_name)

    lowered = combined.lower()
    return any(name and name.lower() in lowered for name in candidate_names)


async def _get_staff_feedback_stats(
    guild_id: int,
    channel_id: int,
    staff_member: discord.Member,
) -> tuple[Optional[float], int, str]:
    data = load_staff_feedback_stats()
    cache = data.get(str(guild_id), {})
    if not isinstance(cache, dict) or int(cache.get("channel_id", 0) or 0) != channel_id:
        return None, 0, "cached feedback"
    member_stats = cache.get("members", {}).get(str(staff_member.id))
    if not member_stats:
        return None, 0, "cached feedback"

    feedback_count = int(member_stats.get("feedback_count", 0))
    total_rating = float(member_stats.get("total_rating", 0))
    if feedback_count <= 0:
        return None, 0, "cached feedback"

    return total_rating / feedback_count, feedback_count, "cached feedback"


def _build_empty_feedback_cache(channel_id: int) -> dict:
    return {
        "channel_id": channel_id,
        "bootstrapped": False,
        "last_synced_at": None,
        "members": {},
        "entries": {},
    }


def _record_feedback_entry(cache: dict, message_id: int, staff_user_id: int, rating: int):
    _remove_feedback_entry(cache, message_id)

    entries = cache.setdefault("entries", {})
    members = cache.setdefault("members", {})
    member_key = str(staff_user_id)
    member_stats = members.setdefault(member_key, {"total_rating": 0, "feedback_count": 0})

    member_stats["total_rating"] = int(member_stats.get("total_rating", 0)) + rating
    member_stats["feedback_count"] = int(member_stats.get("feedback_count", 0)) + 1
    entries[str(message_id)] = {
        "staff_user_id": str(staff_user_id),
        "rating": int(rating),
    }


def _remove_feedback_entry(cache: dict, message_id: int) -> bool:
    entries = cache.setdefault("entries", {})
    entry = entries.pop(str(message_id), None)
    if not entry:
        return False

    members = cache.setdefault("members", {})
    member_key = str(entry.get("staff_user_id"))
    member_stats = members.get(member_key)
    if not member_stats:
        return True

    member_stats["total_rating"] = int(member_stats.get("total_rating", 0)) - int(entry.get("rating", 0))
    member_stats["feedback_count"] = int(member_stats.get("feedback_count", 0)) - 1

    if member_stats["feedback_count"] <= 0:
        members.pop(member_key, None)
    return True


def _finalize_feedback_cache(cache: dict):
    cache["bootstrapped"] = True
    cache["last_synced_at"] = int(time.time())


async def _ensure_staff_feedback_cache(feedback_channel) -> tuple[Optional[dict], str]:
    data = load_staff_feedback_stats()
    guild_key = str(feedback_channel.guild.id)
    cache = data.get(guild_key)
    if not isinstance(cache, dict) or int(cache.get("channel_id", 0) or 0) != feedback_channel.id:
        return None, "cache unavailable"
    return cache, "cached feedback"


def _save_feedback_entry(guild_id: int, channel_id: int, message_id: int, staff_user_id: int, rating: int):
    data = load_staff_feedback_stats()
    guild_key = str(guild_id)
    cache = data.get(guild_key)
    if not isinstance(cache, dict) or int(cache.get("channel_id", 0) or 0) != channel_id:
        cache = _build_empty_feedback_cache(channel_id)
        data[guild_key] = cache

    _record_feedback_entry(cache, message_id, staff_user_id, rating)
    save_staff_feedback_stats(data)


def _set_feedback_cache_for_guild(guild_id: int, cache: dict):
    data = load_staff_feedback_stats()
    data[str(guild_id)] = cache
    save_staff_feedback_stats(data)


def _format_feedback_sync_elapsed(started_at: float) -> str:
    elapsed = max(0, int(time.monotonic() - started_at))
    minutes, seconds = divmod(elapsed, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}h {minutes}m {seconds}s"
    if minutes:
        return f"{minutes}m {seconds}s"
    return f"{seconds}s"


def _build_feedback_sync_embed(
    guild: discord.Guild,
    *,
    title: str,
    status: str,
    color: int,
    percent: int,
    scanned_messages: int,
    recorded_entries: int,
    started_at: float,
    synced_at: Optional[int] = None,
) -> discord.Embed:
    embed = discord.Embed(
        title=title,
        description=(
            f"> **Status:** {status}\n"
            f"> **Progress:** `{percent}%`\n"
            f"> **Messages Scanned:** `{scanned_messages}`\n"
            f"> **Feedback Entries Recorded:** `{recorded_entries}`\n"
            f"> **Elapsed:** `{_format_feedback_sync_elapsed(started_at)}`"
        ),
        color=color,
        timestamp=discord.utils.utcnow(),
    )
    embed.set_author(name=guild.name, icon_url=guild.icon.url if guild.icon else CSRP_ICON)
    if synced_at is not None:
        embed.add_field(name="Completed", value=f"<t:{synced_at}:F>", inline=False)
    brand_footer(embed)
    return embed


def _remove_feedback_entry_for_guild(guild_id: int, channel_id: int, message_id: int) -> bool:
    data = load_staff_feedback_stats()
    cache = data.get(str(guild_id))
    if not isinstance(cache, dict) or int(cache.get("channel_id", 0) or 0) != channel_id:
        return False
    if not _remove_feedback_entry(cache, message_id):
        return False
    save_staff_feedback_stats(data)
    return True


def _get_target_role_ids(
    settings: dict,
    retirement: dict,
    highest_rank: str,
    demoted_rank: str,
) -> tuple[list[int], list[str]]:
    rank_roles = settings.get("rank_roles", {})
    target_role_ids: list[int] = []
    warnings: list[str] = []

    previous_roles = retirement.get("previous_roles", [])
    previous_highest_role_id = rank_roles.get(highest_rank)
    target_role_ids.extend(
        role_id for role_id in previous_roles
        if role_id and role_id != previous_highest_role_id
    )

    demoted_role_id = rank_roles.get(demoted_rank)
    if demoted_role_id:
        target_role_ids.append(demoted_role_id)
    else:
        warnings.append(f"The configured rank role for **{demoted_rank}** is missing.")

    base_role_id = BASE_ROLE_BY_RANK.get(demoted_rank)
    if base_role_id:
        target_role_ids.append(base_role_id)
    else:
        warnings.append(f"No base role mapping exists for **{demoted_rank}**.")

    target_role_ids.extend(EXTRA_ROLE_IDS_BY_RANK.get(demoted_rank, []))

    unique_role_ids: list[int] = []
    seen = set()
    for role_id in target_role_ids:
        if role_id and role_id not in seen:
            unique_role_ids.append(role_id)
            seen.add(role_id)

    return unique_role_ids, warnings


def _get_member_highest_rank(member: discord.Member, settings: dict) -> Optional[str]:
    rank_roles = settings.get("rank_roles", {})
    role_to_rank = {role_id: rank for rank, role_id in rank_roles.items() if role_id is not None}

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


def _can_manage_rank(actor_rank: Optional[str], target_rank: Optional[str]) -> bool:
    if target_rank is None or target_rank not in RANK_ORDER:
        return True
    if actor_rank is None or actor_rank not in RANK_ORDER:
        return False
    return RANK_ORDER.index(actor_rank) < RANK_ORDER.index(target_rank)


def _rank_related_role_ids(settings: dict, rank: str) -> set[int]:
    rank_roles = settings.get("rank_roles", {})
    role_ids = set()
    configured_role_id = rank_roles.get(rank)
    if configured_role_id:
        role_ids.add(int(configured_role_id))

    base_role_id = BASE_ROLE_BY_RANK.get(rank)
    if base_role_id:
        role_ids.add(base_role_id)

    role_ids.update(EXTRA_ROLE_IDS_BY_RANK.get(rank, []))
    return role_ids


class StaffManagement(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self._feedback_sync_jobs: dict[int, asyncio.Lock] = {}

    def _get_feedback_sync_lock(self, guild_id: int) -> asyncio.Lock:
        lock = self._feedback_sync_jobs.get(guild_id)
        if lock is None:
            lock = asyncio.Lock()
            self._feedback_sync_jobs[guild_id] = lock
        return lock

    async def _resolve_feedback_channel(self, guild: discord.Guild) -> Optional[discord.abc.GuildChannel]:
        settings = get_guild_settings(guild.id)
        feedback_channel_id = settings.get("staff_feedback_channel")
        if not feedback_channel_id:
            return None

        feedback_channel = self.bot.get_channel(feedback_channel_id)
        if feedback_channel:
            return feedback_channel

        try:
            return await self.bot.fetch_channel(feedback_channel_id)
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            return None

    async def _run_feedback_sync(
        self,
        feedback_channel,
        progress_message: discord.Message,
    ) -> tuple[dict, int, int]:
        oldest_messages = [message async for message in feedback_channel.history(limit=1, oldest_first=True)]
        if not oldest_messages:
            cache = _build_empty_feedback_cache(feedback_channel.id)
            _finalize_feedback_cache(cache)
            _set_feedback_cache_for_guild(feedback_channel.guild.id, cache)
            return cache, 0, 0

        newest_messages = [message async for message in feedback_channel.history(limit=1)]
        oldest_timestamp = oldest_messages[0].created_at.timestamp()
        newest_timestamp = newest_messages[0].created_at.timestamp() if newest_messages else oldest_timestamp
        total_span = max(newest_timestamp - oldest_timestamp, 0)

        cache = _build_empty_feedback_cache(feedback_channel.id)
        progress_state = {
            "processed": 0,
            "recorded": 0,
            "percent": 0,
            "status": "Scanning channel history...",
            "done": False,
        }
        started_at = time.monotonic()

        async def update_progress_loop():
            while not progress_state["done"]:
                await asyncio.sleep(15)
                if progress_state["done"]:
                    break
                embed = _build_feedback_sync_embed(
                    feedback_channel.guild,
                    title="Feedback Sync In Progress",
                    status=progress_state["status"],
                    color=BLANK_COLOR,
                    percent=int(progress_state["percent"]),
                    scanned_messages=int(progress_state["processed"]),
                    recorded_entries=int(progress_state["recorded"]),
                    started_at=started_at,
                )
                try:
                    await progress_message.edit(embed=embed)
                except discord.HTTPException:
                    pass

        progress_task = asyncio.create_task(update_progress_loop())

        try:
            async for message in feedback_channel.history(limit=None, oldest_first=True):
                progress_state["processed"] += 1

                target_user_id = _extract_feedback_target_user_id(message)
                rating = _extract_feedback_rating_from_message(message)
                if target_user_id is not None and rating is not None:
                    _record_feedback_entry(cache, message.id, target_user_id, rating)
                    progress_state["recorded"] += 1

                if total_span <= 0:
                    progress_state["percent"] = 100
                else:
                    traversed = max(message.created_at.timestamp() - oldest_timestamp, 0)
                    progress_state["percent"] = min(99, int((traversed / total_span) * 100))
        finally:
            progress_state["done"] = True
            progress_task.cancel()
            try:
                await progress_task
            except asyncio.CancelledError:
                pass

        _finalize_feedback_cache(cache)
        _set_feedback_cache_for_guild(feedback_channel.guild.id, cache)
        return cache, progress_state["processed"], progress_state["recorded"]

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.guild is None or message.author.bot:
            return

        settings = get_guild_settings(message.guild.id)
        feedback_channel_id = settings.get("staff_feedback_channel")
        if feedback_channel_id != message.channel.id:
            return

        target_user_id = _extract_feedback_target_user_id(message)
        rating = _extract_feedback_rating_from_message(message)
        if target_user_id is None or rating is None:
            return

        _save_feedback_entry(message.guild.id, message.channel.id, message.id, target_user_id, rating)

    @commands.Cog.listener()
    async def on_raw_message_delete(self, payload: discord.RawMessageDeleteEvent):
        if payload.guild_id is None:
            return
        _remove_feedback_entry_for_guild(payload.guild_id, payload.channel_id, payload.message_id)

    @commands.Cog.listener()
    async def on_raw_bulk_message_delete(self, payload: discord.RawBulkMessageDeleteEvent):
        if payload.guild_id is None:
            return

        for message_id in payload.message_ids:
            _remove_feedback_entry_for_guild(payload.guild_id, payload.channel_id, message_id)

    @commands.hybrid_command(name="retire", description="Retire a staff member, removing their staff roles.")
    @app_commands.describe(user="The staff member to retire")
    async def retire(self, ctx: commands.Context, user: discord.Member):
        settings = get_guild_settings(ctx.guild.id)

        if not has_setting_permission(ctx.guild.id, "retire_allowed_roles", ctx.author):
            await ctx.send(embed=error_embed("Not Permitted", "You do not have permission to use this command."))
            return

        staff_role_ids = set(settings.get("staff_roles", []))
        if not staff_role_ids:
            await ctx.send(embed=error_embed("Not Configured", "Staff roles have not been configured. Use `/settings` to set them up."))
            return

        user_staff_roles = [r for r in user.roles if r.id in staff_role_ids]
        if not user_staff_roles:
            await ctx.send(embed=error_embed("Not Staff", f"{user.mention} does not have any staff roles."))
            return

        actor_rank = _get_member_highest_rank(ctx.author, settings)
        highest_rank = _get_member_highest_rank(user, settings)

        if not _can_manage_rank(actor_rank, highest_rank):
            await ctx.send(embed=error_embed(
                "Insufficient Rank",
                f"You cannot retire {user.mention} because their rank (**{highest_rank}**) is higher than yours.",
            ))
            return

        entry = {
            "previous_roles": [r.id for r in user_staff_roles],
            "highest_rank": highest_rank,
            "retired_by": ctx.author.id,
            "retired_at": int(time.time()),
        }
        save_retirement(ctx.guild.id, user.id, entry)

        try:
            await user.remove_roles(*user_staff_roles, reason=f"Retired by {ctx.author.name}")
        except discord.Forbidden:
            await ctx.send(embed=error_embed("Missing Permissions", "I don't have permission to remove roles from this user."))
            return

        removed_text = ", ".join(r.mention for r in user_staff_roles)
        log_embed = discord.Embed(
            title="Staff Member Retired",
            description=embed_description(
                (
                    f"> **User:** {user_tag(user)}\n"
                    f"> **Retired By:** {user_tag(ctx.author)}\n"
                    f"> **Highest Rank:** `{highest_rank or 'Unknown'}`"
                ),
                f"> **Roles Removed:** {removed_text}",
                f"> **Date:** <t:{int(time.time())}:f>",
            ),
            color=BLANK_COLOR,
            timestamp=discord.utils.utcnow(),
        )
        log_embed.set_author(name=ctx.guild.name, icon_url=ctx.guild.icon.url if ctx.guild.icon else CSRP_ICON)
        log_embed.set_thumbnail(url=user.display_avatar.url)
        brand_footer(log_embed)

        log_channel_id = settings.get("retirement_log_channel")
        if log_channel_id:
            log_channel = self.bot.get_channel(log_channel_id)
            if log_channel:
                try:
                    await log_channel.send(embed=log_embed)
                except discord.HTTPException:
                    pass

        await ctx.send(embed=success_embed(
            "Retirement Processed",
            f"{user_tag(user)} has been retired. Their roles have been saved for potential reinstatement.",
        ))

    @commands.hybrid_command(name="reinstate", description="Reinstate a retired staff member with a one-rank demotion.")
    @app_commands.describe(user="The retired staff member to reinstate")
    async def reinstate(self, ctx: commands.Context, user: discord.Member):
        settings = get_guild_settings(ctx.guild.id)

        if not has_setting_permission(ctx.guild.id, "retire_allowed_roles", ctx.author):
            await ctx.send(embed=error_embed("Not Permitted", "You do not have permission to use this command."))
            return

        retirement = get_retirement(ctx.guild.id, user.id)
        if not retirement:
            await ctx.send(embed=error_embed("No Record", f"{user_tag(user)} does not have a retirement record."))
            return

        highest_rank = retirement.get("highest_rank")
        rank_roles = settings.get("rank_roles", {})
        actor_rank = _get_member_highest_rank(ctx.author, settings)

        if not _can_manage_rank(actor_rank, highest_rank):
            await ctx.send(embed=error_embed(
                "Insufficient Rank",
                f"You cannot reinstate {user_tag(user)} because their saved rank (**{highest_rank or 'Unknown'}**) is higher than yours.",
            ))
            return

        if not highest_rank or highest_rank not in RANK_ORDER:
            await ctx.send(embed=warning_embed(
                "Manual Handling Required",
                f"{user_tag(user)}'s previous rank (`{highest_rank or 'Unknown'}`) is not in the standard hierarchy. Reinstatement requires further handling.",
            ))
            return

        if highest_rank not in DEMOTION_MAP:
            await ctx.send(embed=warning_embed(
                "Manual Handling Required",
                f"{user_tag(user)}'s previous rank was **{highest_rank}** (lowest in hierarchy). Reinstatement requires further handling.",
            ))
            return

        demoted_rank = DEMOTION_MAP[highest_rank]
        target_role_ids, config_warnings = _get_target_role_ids(settings, retirement, highest_rank, demoted_rank)
        if config_warnings:
            await ctx.send(embed=error_embed("Role Not Configured", " ".join(config_warnings)))
            return

        roles_to_add = []
        missing_role_ids = []
        for role_id in target_role_ids:
            role = ctx.guild.get_role(role_id)
            if role is None:
                missing_role_ids.append(role_id)
                continue
            roles_to_add.append(role)

        if missing_role_ids:
            missing_text = ", ".join(f"`{role_id}`" for role_id in missing_role_ids)
            await ctx.send(embed=error_embed("Role Not Found", f"These reinstatement roles no longer exist in this server: {missing_text}"))
            return

        demoted_role_id = rank_roles.get(demoted_rank)
        demoted_role = ctx.guild.get_role(demoted_role_id) if demoted_role_id else None
        if not demoted_role:
            await ctx.send(embed=error_embed("Role Not Found", f"The role for **{demoted_rank}** no longer exists in this server."))
            return

        try:
            await user.add_roles(*roles_to_add, reason=f"Reinstated by {ctx.author.name} (demoted from {highest_rank})")
        except discord.Forbidden:
            await ctx.send(embed=error_embed("Missing Permissions", "I don't have permission to assign roles to this user."))
            return

        remove_retirement(ctx.guild.id, user.id)

        log_embed = discord.Embed(
            title="Staff Member Reinstated",
            description=embed_description(
                (
                    f"> **User:** {user_tag(user)}\n"
                    f"> **Reinstated By:** {user_tag(ctx.author)}"
                ),
                (
                    f"> **Previous Rank:** `{highest_rank}`\n"
                    f"> **Reinstated As:** {demoted_role.mention} (`{demoted_rank}`)"
                ),
                f"> **Date:** <t:{int(time.time())}:f>",
            ),
            color=BLANK_COLOR,
            timestamp=discord.utils.utcnow(),
        )
        log_embed.set_author(name=ctx.guild.name, icon_url=ctx.guild.icon.url if ctx.guild.icon else CSRP_ICON)
        log_embed.set_thumbnail(url=user.display_avatar.url)
        brand_footer(log_embed)

        log_channel_id = settings.get("retirement_log_channel")
        if log_channel_id:
            log_channel = self.bot.get_channel(log_channel_id)
            if log_channel:
                try:
                    await log_channel.send(embed=log_embed)
                except discord.HTTPException:
                    pass

        await ctx.send(embed=success_embed(
            "Reinstatement Processed",
            (
                f"{user.mention} has been reinstated as {demoted_role.mention} (**{demoted_rank}**), "
                f"demoted from **{highest_rank}**. Roles restored: {', '.join(role.mention for role in roles_to_add)}."
            ),
        ))

    @commands.hybrid_command(name="demote", description="Demote a staff member by one rank.")
    @app_commands.describe(user="The staff member to demote", reason="The reason for the demotion")
    async def demote(self, ctx: commands.Context, user: discord.Member, *, reason: str):
        settings = get_guild_settings(ctx.guild.id)

        if not has_setting_permission(ctx.guild.id, "retire_allowed_roles", ctx.author):
            await ctx.send(embed=error_embed("Not Permitted", "You do not have permission to use this command."))
            return

        infract_channel = self.bot.get_channel(INFRACTION_CHANNEL)
        if infract_channel is None:
            await ctx.send(embed=error_embed("Channel Not Found", "The infraction channel could not be found."))
            return

        actor_rank = _get_member_highest_rank(ctx.author, settings)
        highest_rank = _get_member_highest_rank(user, settings)

        if not highest_rank:
            await ctx.send(embed=error_embed("Rank Not Found", f"{user.mention} does not have a configured staff rank."))
            return

        if not _can_manage_rank(actor_rank, highest_rank):
            await ctx.send(embed=error_embed(
                "Insufficient Rank",
                f"You cannot demote {user.mention} because their rank (**{highest_rank}**) is higher than yours.",
            ))
            return

        if highest_rank not in DEMOTION_MAP:
            await ctx.send(embed=warning_embed(
                "Cannot Demote",
                f"{user.mention} is already at the lowest configured rank (**{highest_rank}**).",
            ))
            return

        demoted_rank = DEMOTION_MAP[highest_rank]
        current_role_ids = _rank_related_role_ids(settings, highest_rank)
        target_role_ids = _rank_related_role_ids(settings, demoted_rank)

        if not target_role_ids:
            await ctx.send(embed=error_embed("Role Not Configured", f"No role mapping exists for **{demoted_rank}**."))
            return

        missing_role_ids = []
        target_roles = []
        for role_id in target_role_ids:
            role = ctx.guild.get_role(role_id)
            if role is None:
                missing_role_ids.append(role_id)
                continue
            target_roles.append(role)

        removable_role_ids = current_role_ids - target_role_ids
        roles_to_remove = [role for role in user.roles if role.id in removable_role_ids]
        roles_to_add = [role for role in target_roles if role not in user.roles]

        if missing_role_ids:
            missing_text = ", ".join(f"`{role_id}`" for role_id in missing_role_ids)
            await ctx.send(embed=error_embed("Role Not Found", f"These demotion roles no longer exist in this server: {missing_text}"))
            return

        if not roles_to_remove and not roles_to_add:
            await ctx.send(embed=warning_embed(
                "No Role Changes",
                f"{user.mention} already has the expected roles for **{demoted_rank}**.",
            ))
            return

        try:
            if roles_to_add:
                await user.add_roles(*roles_to_add, reason=f"Demoted by {ctx.author.name}: {reason}")
            if roles_to_remove:
                await user.remove_roles(*roles_to_remove, reason=f"Demoted by {ctx.author.name}: {reason}")
        except discord.Forbidden:
            await ctx.send(embed=error_embed("Missing Permissions", "I don't have permission to update roles for this user."))
            return

        infraction_embed = build_infraction_embed(user, "Demote", reason, ctx.author)
        await infract_channel.send(f"<@{user.id}>", embed=infraction_embed, legacy_embeds=True)

        await ctx.send(embed=success_embed(
            "Demotion Processed",
            f"{user.mention} has been demoted from **{highest_rank}** to **{demoted_rank}**.",
        ))

    @commands.hybrid_command(name="staff_feedback", description="Leave feedback for a staff member.")
    @app_commands.describe(
        user="The staff member to leave feedback for",
        rating="Rating out of 10 (1-10)",
        reason="Your feedback / reason for the rating",
    )
    async def staff_feedback(self, ctx: commands.Context, user: discord.Member, rating: int, *, reason: str):
        if ctx.interaction and not ctx.interaction.response.is_done():
            await ctx.defer(ephemeral=True)

        if ctx.author.id in load_feedback_blacklist():
            await ctx.send(
                embed=error_embed(
                    "Blacklisted",
                    "You are blacklisted from sending staff feedback.",
                ),
                ephemeral=True,
            )
            return

        if ctx.author.id == user.id:
            await ctx.send(
                embed=error_embed(
                    "Invalid Target",
                    "You cannot leave staff feedback for yourself.",
                ),
                ephemeral=True,
            )
            return

        if rating < 1 or rating > 10:
            await ctx.send(embed=error_embed("Invalid Rating", "Rating must be between **1** and **10**."))
            return

        settings = get_guild_settings(ctx.guild.id)

        staff_role_ids = set(settings.get("staff_roles", []))
        if not staff_role_ids:
            await ctx.send(embed=error_embed("Not Configured", "Staff roles have not been configured. Use `/settings` to set them up."))
            return

        user_is_staff = any(r.id in staff_role_ids for r in user.roles)
        if not user_is_staff:
            await ctx.send(embed=error_embed("Not Staff", f"{user.mention} is not a staff member."))
            return

        feedback_channel_id = settings.get("staff_feedback_channel")
        if not feedback_channel_id:
            await ctx.send(embed=error_embed("Not Configured", "Staff feedback channel has not been configured. Use `/settings` to set it up."))
            return

        feedback_channel = await self._resolve_feedback_channel(ctx.guild)
        if not feedback_channel:
            await ctx.send(embed=error_embed("Channel Not Found", "The configured staff feedback channel could not be found."))
            return

        average_rating, feedback_count, _ = await _get_staff_feedback_stats(ctx.guild.id, feedback_channel.id, user)

        embed = discord.Embed(
            title="Staff Feedback",
            description=(
                f"> **User:** {user.display_name}\n"
                f"> **Rating:** `{rating}/10`\n"
                f"> **Reason:** {reason}"
            ),
            color=BLANK_COLOR,
            timestamp=discord.utils.utcnow(),
        )
        embed.set_author(name=ctx.guild.name, icon_url=ctx.guild.icon.url if ctx.guild.icon else CSRP_ICON)
        embed.set_thumbnail(url=user.display_avatar.url)
        cache_data = load_staff_feedback_stats().get(str(ctx.guild.id), {})
        has_full_history = isinstance(cache_data, dict) and bool(cache_data.get("bootstrapped")) and int(cache_data.get("channel_id", 0) or 0) == feedback_channel.id
        if average_rating is None:
            average_text = "No previous feedback found."
        else:
            average_text = f"`{average_rating:.2f}/10` across `{feedback_count}` previous entr{'y' if feedback_count == 1 else 'ies'}."
            if not has_full_history:
                average_text += " Historical sync has not been completed yet, so this only reflects cached entries."
        embed.add_field(name="Average Rating", value=average_text, inline=False)
        embed.set_footer(text=f"Feedback by {ctx.author.name}", icon_url=ctx.author.display_avatar.url)

        try:
            feedback_message = await feedback_channel.send(
                content=user.mention,
                embed=embed,
                allowed_mentions=discord.AllowedMentions(users=[user]),
            )
        except discord.Forbidden:
            await ctx.send(embed=error_embed("Missing Permissions", "I don't have permission to post in the configured staff feedback channel."))
            return
        except discord.HTTPException:
            await ctx.send(embed=error_embed("Send Failed", "I couldn't submit the feedback due to a Discord API error."))
            return

        _save_feedback_entry(ctx.guild.id, feedback_channel.id, feedback_message.id, user.id, rating)

        await ctx.send(embed=success_embed("Feedback Submitted", f"Your feedback for {user.mention} has been submitted."), ephemeral = True)

    @commands.hybrid_command(name="feedback_blacklist", description="Blacklists a user from sending staff feedback.")
    @app_commands.describe(user="The user to blacklist from staff feedback")
    async def feedback_blacklist(self, ctx: commands.Context, user: discord.Member):
        if ctx.guild is None:
            await ctx.send(embed=error_embed("Server Only", "This command can only be used in a server."))
            return

        if not member_has_rank_or_higher(ctx.author, "Internal Affairs"):
            await ctx.send(
                embed=error_embed("Insufficient Permissions", "You must be **Internal Affairs** or higher to use this command."),
                ephemeral=True,
            )
            return

        blacklisted_user_ids = load_feedback_blacklist()
        if user.id in blacklisted_user_ids:
            await ctx.send(
                embed=warning_embed("Already Blacklisted", f"{user.mention} is already blacklisted from sending staff feedback."),
                ephemeral=True,
            )
            return

        view = ConfirmView(ctx.author, timeout=15)
        embed = discord.Embed(
            title="Confirm Feedback Blacklist",
            description=(
                f"Are you sure you want to blacklist **{user.display_name}** from sending staff feedback?\n\n"
                f"> **Requested By:** {ctx.author.mention}\n"
                f"> **Target:** {user.mention}"
            ),
            color=BLANK_COLOR,
        )
        embed.set_author(name=ctx.guild.name, icon_url=ctx.guild.icon.url if ctx.guild.icon else "")
        brand_footer(embed)
        msg = await ctx.send(embed=embed, view=view)
        view.message = msg
        await view.wait()

        if view.value:
            append_feedback_blacklist_user(user.id)
            await msg.edit(
                embed=success_embed("User Blacklisted", f"**{user.name}** has been blacklisted from sending staff feedback."),
                view=None,
            )
        elif view.value is False:
            await msg.edit(
                embed=discord.Embed(title="Action Cancelled", description="The action has been cancelled.", color=BLANK_COLOR),
                view=None,
            )
        else:
            await msg.edit(
                embed=discord.Embed(title="Action Timed Out", description="The action has timed out.", color=BLANK_COLOR),
                view=None,
            )

    @commands.hybrid_command(name="remove_feedback_blacklist", description="Removes a user from the staff feedback blacklist.")
    @app_commands.describe(user="The user to remove from the feedback blacklist")
    async def remove_feedback_blacklist(self, ctx: commands.Context, user: discord.Member):
        if ctx.guild is None:
            await ctx.send(embed=error_embed("Server Only", "This command can only be used in a server."))
            return

        if not member_has_rank_or_higher(ctx.author, "Internal Affairs"):
            await ctx.send(
                embed=error_embed("Insufficient Permissions", "You must be **Internal Affairs** or higher to use this command."),
                ephemeral=True,
            )
            return

        blacklisted_user_ids = load_feedback_blacklist()
        if user.id not in blacklisted_user_ids:
            await ctx.send(
                embed=warning_embed("Not Blacklisted", f"{user.mention} is not currently blacklisted from sending staff feedback."),
                ephemeral=True,
            )
            return

        view = ConfirmView(ctx.author, timeout=15)
        embed = discord.Embed(
            title="Confirm Feedback Unblacklist",
            description=(
                f"Are you sure you want to remove **{user.display_name}** from the feedback blacklist?\n\n"
                f"> **Requested By:** {ctx.author.mention}\n"
                f"> **Target:** {user.mention}"
            ),
            color=BLANK_COLOR,
        )
        embed.set_author(name=ctx.guild.name, icon_url=ctx.guild.icon.url if ctx.guild.icon else "")
        brand_footer(embed)
        msg = await ctx.send(embed=embed, view=view)
        view.message = msg
        await view.wait()

        if view.value:
            try:
                with open(feedback_blacklists, "r") as file:
                    lines = file.readlines()
                with open(feedback_blacklists, "w") as file:
                    for line in lines:
                        if f"{{userid: {user.id}}}" not in line:
                            file.write(line)
            except FileNotFoundError:
                pass
            await msg.edit(
                embed=success_embed("User Removed", f"**{user.name}** has been removed from the feedback blacklist."),
                view=None,
            )
        elif view.value is False:
            await msg.edit(
                embed=discord.Embed(title="Action Cancelled", description="The action has been cancelled.", color=BLANK_COLOR),
                view=None,
            )
        else:
            await msg.edit(
                embed=discord.Embed(title="Action Timed Out", description="The action has timed out.", color=BLANK_COLOR),
                view=None,
            )

    @commands.hybrid_command(name="feedbacksync", description="Sync the full staff feedback channel history into the cache.")
    @is_bot_dev()
    async def feedbacksync(self, ctx: commands.Context):
        if ctx.guild is None:
            await ctx.send(embed=error_embed("Server Only", "This command can only be used in a server."))
            return

        if ctx.interaction and not ctx.interaction.response.is_done():
            await ctx.defer(ephemeral=True)

        feedback_channel = await self._resolve_feedback_channel(ctx.guild)
        if not feedback_channel:
            await ctx.send(embed=error_embed("Channel Not Found", "The configured staff feedback channel could not be found."))
            return

        lock = self._get_feedback_sync_lock(ctx.guild.id)
        if lock.locked():
            await ctx.send(embed=warning_embed("Sync Already Running", "A feedback sync is already in progress for this server."), ephemeral=True)
            return

        started_at = time.monotonic()
        initial_embed = _build_feedback_sync_embed(
            ctx.guild,
            title="Feedback Sync Starting",
            status=f"Preparing to scan {feedback_channel.mention}...",
            color=BLANK_COLOR,
            percent=0,
            scanned_messages=0,
            recorded_entries=0,
            started_at=started_at,
        )
        if ctx.interaction:
            await ctx.send(embed=initial_embed, ephemeral=True)
            progress_message = await ctx.interaction.original_response()
        else:
            progress_message = await ctx.send(embed=initial_embed)

        async with lock:
            try:
                cache, scanned_messages, recorded_entries = await self._run_feedback_sync(feedback_channel, progress_message)
            except (discord.Forbidden, discord.HTTPException, AttributeError):
                failure_embed = error_embed(
                    "Sync Failed",
                    "I couldn't read the full feedback channel history. Check my permissions and try again.",
                )
                await progress_message.edit(embed=failure_embed)
                return

        completed_embed = _build_feedback_sync_embed(
            ctx.guild,
            title="Feedback Sync Complete",
            status=f"Finished syncing {feedback_channel.mention}.",
            color=BLANK_COLOR,
            percent=100,
            scanned_messages=scanned_messages,
            recorded_entries=recorded_entries,
            started_at=started_at,
            synced_at=int(cache.get("last_synced_at") or time.time()),
        )
        await progress_message.edit(embed=completed_embed)


async def setup(bot):
    await bot.add_cog(StaffManagement(bot))
