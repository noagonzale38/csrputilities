import discord
from discord.ext import commands
from discord import app_commands
import json
import time
from typing import Optional

from cogs.helpers import (
    BLANK_COLOR, CSRP_ICON,
    brand_footer, success_embed, error_embed, warning_embed, embed_description,
)
from cogs.settings import get_guild_settings, has_setting_permission, RANK_ORDER

RETIREMENTS_FILE = "retirements.json"
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


def load_retirements() -> dict:
    try:
        with open(RETIREMENTS_FILE, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_retirements(data: dict):
    with open(RETIREMENTS_FILE, "w") as f:
        json.dump(data, f, indent=4)


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


class StaffManagement(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

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
                    f"> **User:** {user.mention}\n"
                    f"> **Retired By:** {ctx.author.mention}\n"
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
            f"{user.mention} has been retired. Their roles have been saved for potential reinstatement.",
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
            await ctx.send(embed=error_embed("No Record", f"{user.mention} does not have a retirement record."))
            return

        highest_rank = retirement.get("highest_rank")
        rank_roles = settings.get("rank_roles", {})
        actor_rank = _get_member_highest_rank(ctx.author, settings)

        if not _can_manage_rank(actor_rank, highest_rank):
            await ctx.send(embed=error_embed(
                "Insufficient Rank",
                f"You cannot reinstate {user.mention} because their saved rank (**{highest_rank or 'Unknown'}**) is higher than yours.",
            ))
            return

        if not highest_rank or highest_rank not in RANK_ORDER:
            await ctx.send(embed=warning_embed(
                "Manual Handling Required",
                f"{user.mention}'s previous rank (`{highest_rank or 'Unknown'}`) is not in the standard hierarchy. Reinstatement requires further handling.",
            ))
            return

        if highest_rank not in DEMOTION_MAP:
            await ctx.send(embed=warning_embed(
                "Manual Handling Required",
                f"{user.mention}'s previous rank was **{highest_rank}** (lowest in hierarchy). Reinstatement requires further handling.",
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
                    f"> **User:** {user.mention}\n"
                    f"> **Reinstated By:** {ctx.author.mention}"
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

    @commands.hybrid_command(name="staff_feedback", description="Leave feedback for a staff member.")
    @app_commands.describe(
        user="The staff member to leave feedback for",
        rating="Rating from 1 to 10",
        reason="Your feedback / reason for the rating",
    )
    async def staff_feedback(self, ctx: commands.Context, user: discord.Member, rating: int, *, reason: str):
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

        feedback_channel = self.bot.get_channel(feedback_channel_id)
        if not feedback_channel:
            await ctx.send(embed=error_embed("Channel Not Found", "The configured staff feedback channel could not be found."))
            return

        embed = discord.Embed(
            title="Staff Feedback",
            description=(
                f"> **User:** {user.mention}\n"
                f"> **Rating:** `{rating}/10`\n"
                f"> **Reason:** {reason}"
            ),
            color=BLANK_COLOR,
            timestamp=discord.utils.utcnow(),
        )
        embed.set_author(name=ctx.guild.name, icon_url=ctx.guild.icon.url if ctx.guild.icon else CSRP_ICON)
        embed.set_thumbnail(url=user.display_avatar.url)
        embed.set_footer(text=f"Feedback by {ctx.author.name}", icon_url=ctx.author.display_avatar.url)

        await feedback_channel.send(embed=embed)
        await ctx.send(embed=success_embed("Feedback Submitted", f"Your feedback for {user.mention} has been submitted."), ephemeral = True)


async def setup(bot):
    await bot.add_cog(StaffManagement(bot))
