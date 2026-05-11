import discord
from discord.ext import commands
from discord import app_commands
import json
import re
import time
import random
from datetime import timedelta

from config import (
    MODERATION_ROLE_IDS, INFRACTION_CHANNEL, APPEALS_CHANNEL_ID,
    modlogs_file, casefile, is_moderation, is_role_authorized, is_bot_dev, BOT_OWNER_ID,
)
from cogs.helpers import (
    Colors, BLANK_COLOR, CSRP_ICON, CSRP_BANNER, CHECK, CROSS, PENDING,
    success_embed, error_embed, info_embed, warning_embed, brand_footer, embed_description,
    ConfirmView, PaginatorView, generalised_interaction_check_failure,
)


def save_modlog(user_id, action, reason, moderator_id, case_id):
    timestamp = int(time.time())
    log_entry = {
        "user_id": user_id,
        "action": action,
        "reason": reason,
        "moderator_id": moderator_id,
        "case_id": case_id,
        "timestamp": timestamp,
    }
    try:
        with open(modlogs_file, "r") as f:
            modlogs = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        modlogs = []
    modlogs.append(log_entry)
    with open(modlogs_file, "w") as f:
        json.dump(modlogs, f, indent=4)


def clear_user_modlogs(user_id):
    try:
        with open(modlogs_file, "r") as f:
            modlogs = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        modlogs = []
    modlogs = [log for log in modlogs if log["user_id"] != user_id]
    with open(modlogs_file, "w") as f:
        json.dump(modlogs, f, indent=4)


def clear_all_modlogs_data():
    with open(modlogs_file, "w") as f:
        json.dump([], f, indent=4)


def parse_time(time_str):
    match = re.compile(r'(\d+)([mhdw])').fullmatch(time_str.strip().lower())
    if not match:
        return None
    value, unit = match.groups()
    value = int(value)
    return {'m': value * 60, 'h': value * 3600, 'd': value * 86400, 'w': value * 604800}.get(unit)


def get_next_case():
    try:
        with open(casefile, "r") as file:
            number = int(file.read().strip())
        number += 1
        with open(casefile, "w") as file:
            file.write(str(number))
        return number
    except Exception as e:
        print(f"Error reading casefile: {e}")
        return "Unknown"


def extract_ignore_restrictions_flag(text: str):
    flag = "--ignore-restrictions"
    bypass_requested = flag in text
    cleaned_text = re.sub(r"\s*--ignore-restrictions\s*", " ", text).strip()
    cleaned_text = re.sub(r"\s{2,}", " ", cleaned_text)
    return cleaned_text, bypass_requested


class Moderation(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.infractions = {}

    async def _resolve_restriction_bypass(self, ctx, text: str):
        cleaned_text, bypass_requested = extract_ignore_restrictions_flag(text)
        if bypass_requested and ctx.author.id != BOT_OWNER_ID:
            await ctx.send(
                embed=error_embed(
                    "Unauthorized Flag",
                    "Only the bot owner can use `--ignore-restrictions`.",
                )
            )
            return None, None
        return cleaned_text, bypass_requested

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

        try:
            with open(modlogs_file, "r") as f:
                modlogs = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            modlogs = []

        user_logs = [log for log in modlogs if log["user_id"] == user.id]
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

    @commands.hybrid_command(name="kick", description="Kicks a member from the server.")
    @is_moderation()
    @app_commands.describe(user="The user to kick", reason="The reason for kicking the user")
    async def kick(self, ctx, user: discord.Member, *, reason: str):
        if any(role.id in MODERATION_ROLE_IDS for role in user.roles):
            await ctx.send(embed=error_embed("Cannot Kick User", "I cannot kick other moderators or administrators."))
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
                    f"> **Staff Member:** {ctx.author.mention}\n"
                    f"> **User:** {user.mention}\n"
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
    async def ban(self, ctx, user, *, reason: str):
        reason, ignore_restrictions = await self._resolve_restriction_bypass(ctx, reason)
        if reason is None:
            return
        if not reason:
            await ctx.send(embed=error_embed("Missing Reason", "Please provide a reason for the ban."))
            return

        user_id = None

        if isinstance(user, discord.Member):
            if not ignore_restrictions and any(role.id in MODERATION_ROLE_IDS for role in user.roles):
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
                if not ignore_restrictions and any(role.id in MODERATION_ROLE_IDS for role in member_to_ban.roles):
                    await ctx.send(embed=error_embed("Cannot Ban User", "I cannot ban other moderators or administrators."))
                    return
            except discord.NotFound:
                member_to_ban = None

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
        embed = discord.Embed(
            title="User Banned",
            description=embed_description(
                (
                    f"> **Staff Member:** {ctx.author.mention}\n"
                    f"> **User:** <@{user_id}>\n"
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
                    f"> **Staff Member:** {ctx.author.mention}\n"
                    f"> **User:** {user.mention}\n"
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
    async def mute(self, ctx, user: discord.Member, time: str, *, reason: str):
        reason, ignore_restrictions = await self._resolve_restriction_bypass(ctx, reason)
        if reason is None:
            return
        if not reason:
            await ctx.send(embed=error_embed("Missing Reason", "Please provide a reason for the mute."))
            return

        if not ignore_restrictions and any(role.id in MODERATION_ROLE_IDS for role in user.roles):
            await ctx.send(embed=error_embed("Cannot Mute User", "I cannot mute other moderators or administrators."))
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
                    f"> **Staff Member:** {ctx.author.mention}\n"
                    f"> **User:** {user.mention}\n"
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
                    f"> **Staff Member:** {ctx.author.mention}\n"
                    f"> **User:** {user.mention}\n"
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
    async def warn(self, ctx, user: discord.Member, *, reason: str):
        reason, ignore_restrictions = await self._resolve_restriction_bypass(ctx, reason)
        if reason is None:
            return
        if not reason:
            await ctx.send(embed=error_embed("Missing Reason", "Please provide a reason for the warning."))
            return

        if not ignore_restrictions and any(role.id in MODERATION_ROLE_IDS for role in user.roles):
            await ctx.send(embed=error_embed("Cannot Warn User", "I cannot warn other moderators or administrators."))
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
                    f"> **Staff Member:** {ctx.author.mention}\n"
                    f"> **User:** {user.mention}\n"
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
    async def infract(self, ctx, member: discord.Member, punishment: str, *, reason: str):
        infract_channel = self.bot.get_channel(INFRACTION_CHANNEL)
        if infract_channel is None:
            await ctx.send(embed=error_embed("Channel Not Found", "The infraction channel could not be found."))
            return

        ref_id = random.randint(100000, 999999)

        self.infractions[ref_id] = {
            "user": member,
            "action": punishment,
            "reason": reason,
            "infracted_by": ctx.author,
            "appeal": None,
            "reviewer": None,
            "status": None,
        }

        infraction_embed = discord.Embed(
            color=discord.Color.blue(),
            title="__CSRP Infraction__",
            description=(
                f"**━━━━━━━━━━━━━━━━━━━━━**\n\n"
                f"**User:** {member.mention}\n\n"
                f"**━━━━━━━━━━━━━━━━━━━━━**\n\n"
                f"**Action:** {punishment}\n\n"
                f"**━━━━━━━━━━━━━━━━━━━━━**\n \n"
                f"**Reason:** {reason}\n\n"
                f"**━━━━━━━━━━━━━━━━━━━━━**"
            ),
        )
        infraction_embed.set_footer(text=f"Signed By: {ctx.author}", icon_url=ctx.author.display_avatar.url)
        infraction_embed.set_thumbnail(
            url="https://media.discordapp.net/attachments/1155943381013368853/1170036267141054494/cachedImage.png?"
        )
        await infract_channel.send(f"<@{member.id}>", embed=infraction_embed)

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
                "Click the button below to appeal this infraction.",
            ),
            color=BLANK_COLOR,
        )
        dm_embed.set_author(name="California State Roleplay", icon_url=CSRP_ICON)
        dm_embed.set_thumbnail(url=CSRP_ICON)
        brand_footer(dm_embed)

        bot_ref = self.bot

        class AppealModal(discord.ui.Modal):
            def __init__(self_modal):
                super().__init__(title="Appeal Infraction", timeout=None)
                self_modal.punishment_input = discord.ui.TextInput(label="Punishment", placeholder="Enter the punishment", required=True)
                self_modal.reason_input = discord.ui.TextInput(label="Why should we accept your appeal?", style=discord.TextStyle.paragraph, required=True)
                self_modal.proof_input = discord.ui.TextInput(label="Related proof (optional)", placeholder="Paste a link here", required=False)
                self_modal.add_item(self_modal.punishment_input)
                self_modal.add_item(self_modal.reason_input)
                self_modal.add_item(self_modal.proof_input)

            async def on_submit(self_modal, modal_interaction):
                appeals_channel = bot_ref.get_channel(APPEALS_CHANNEL_ID)
                if appeals_channel is None:
                    await modal_interaction.response.send_message(embed=error_embed("Channel Not Found", "The appeals channel could not be found."), ephemeral=True)
                    return

                appeal_embed = discord.Embed(
                    title="New Appeal Submission",
                    description=embed_description(
                        (
                            f"> **Appellant:** {member.mention}\n"
                            f"> **Reference ID:** `{ref_id}`\n"
                            f"> **Punishment:** {self_modal.punishment_input.value}"
                        ),
                        (
                            f"> **Reason:** {self_modal.reason_input.value}\n"
                            f"> **Proof:** {self_modal.proof_input.value or 'No proof provided'}"
                        ),
                    ),
                    color=BLANK_COLOR,
                )
                appeal_embed.set_author(name="California State Roleplay", icon_url=CSRP_ICON)
                appeal_embed.set_thumbnail(url=member.display_avatar.url)
                brand_footer(appeal_embed)

                accept_btn = discord.ui.Button(label="Accept", style=discord.ButtonStyle.green)
                deny_btn = discord.ui.Button(label="Deny", style=discord.ButtonStyle.danger)

                async def accept_callback(button_interaction):
                    accepted_embed = discord.Embed(
                        title="Appeal Accepted",
                        description=embed_description(
                            f"Congratulations, {member.mention}! Your infraction appeal has been accepted.",
                            (
                                f"> **Reference ID:** `{ref_id}`\n"
                                f"> **Reviewed By:** {button_interaction.user.mention}"
                            ),
                        ),
                        color=BLANK_COLOR,
                    )
                    accepted_embed.set_author(name="California State Roleplay", icon_url=CSRP_ICON)
                    brand_footer(accepted_embed)
                    try:
                        await member.send(embed=accepted_embed)
                    except discord.Forbidden:
                        pass
                    appeal_embed.title = "Accepted Appeal"
                    appeal_embed.color = BLANK_COLOR
                    appeal_embed.description = embed_description(
                        appeal_embed.description or "",
                        f"> **Reviewed By:** {button_interaction.user.mention}",
                    )
                    await button_interaction.response.edit_message(embed=appeal_embed, view=None)

                async def deny_callback(button_interaction):
                    denied_embed = discord.Embed(
                        title="Appeal Denied",
                        description=f"Your infraction appeal has been denied. Please open a ticket with ref id `{ref_id}`.",
                        color=BLANK_COLOR,
                    )
                    denied_embed.set_author(name="California State Roleplay", icon_url=CSRP_ICON)
                    brand_footer(denied_embed)
                    try:
                        await member.send(embed=denied_embed)
                    except discord.Forbidden:
                        pass
                    appeal_embed.title = "Denied Appeal"
                    appeal_embed.color = BLANK_COLOR
                    appeal_embed.description = embed_description(
                        appeal_embed.description or "",
                        f"> **Reviewed By:** {button_interaction.user.mention}",
                    )
                    await button_interaction.response.edit_message(embed=appeal_embed, view=None)

                accept_btn.callback = accept_callback
                deny_btn.callback = deny_callback

                view = discord.ui.View(timeout=None)
                view.add_item(accept_btn)
                view.add_item(deny_btn)

                await appeals_channel.send(f"{ctx.author.mention}", embed=appeal_embed, view=view)
                await modal_interaction.response.send_message(
                    embed=success_embed("Appeal Submitted", f"Your appeal has been submitted. Reference ID: `{ref_id}`"),
                    ephemeral=True,
                )

        appeal_button = discord.ui.Button(label="Appeal Infraction", style=discord.ButtonStyle.primary)

        async def appeal_button_callback(interaction):
            await interaction.response.send_modal(AppealModal())

        appeal_button.callback = appeal_button_callback
        view = discord.ui.View(timeout=None)
        view.add_item(appeal_button)

        try:
            await member.send(embed=dm_embed, view=view)
            await ctx.send(embed=success_embed("User Infracted", "The user has been successfully infracted."), delete_after=5)
        except discord.Forbidden:
            await ctx.send(
                embed=warning_embed("DM Failed", "Unable to DM the user. The infraction embed has still been posted."),
                ephemeral=True,
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
