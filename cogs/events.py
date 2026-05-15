import discord
from discord.ext import commands, tasks
from discord.utils import utcnow
import re
import json
import logging
import sentry_sdk
import random
from datetime import timedelta, datetime

from config import (
    SERVER_KEY, LOGGING_CHANNEL_ID, ERRORS_CHANNEL, MODERATION_ROLE_IDS,
    CHANNEL_ID, BAN_CHANNEL, LOG_SERVER_URL, LOG_SERVER_AUTH,
    LATENCY_API_URL, MOD_CHANNEL_ID, MOD_ROLE_ID,
    casefile, afk_file, CSRPUTILS_DEVS,
)
from cogs.helpers import (
    Colors, BLANK_COLOR, CSRP_ICON, CHECK, CROSS, PENDING, DEVELOPER,
    success_embed, error_embed, info_embed, brand_footer, embed_description,
    api_get, api_post, generalised_interaction_check_failure,
)
from cogs.settings import get_guild_settings


def load_afk():
    try:
        with open(afk_file, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_afk(data):
    with open(afk_file, "w") as f:
        json.dump(data, f, indent=4)


async def check_usernames():
    try:
        status, data = await api_get(
            'https://api.erlc.gg/v1/server/players',
            headers={'Server-Key': SERVER_KEY},
        )
        if status != 200 or not isinstance(data, list):
            return []
    except Exception:
        return []

    matching_users = []
    for user in data:
        if isinstance(user, dict) and 'Player' in user:
            username, user_id = user['Player'].split(':')
            username_lower = username.lower()
            if username_lower == "aliseneth61":
                continue
            if username_lower.startswith(('all', 'others', 'ail', 'ali', 'aii', 'a1i', 'ai1', 'a1l', 'al1')):
                matching_users.append({
                    'username': username,
                    'user_id': user_id,
                    'team': user.get('Team', 'N/A'),
                    'permission': user.get('Permission', 'N/A'),
                })
    return matching_users


async def ban_user(user_id, reason):
    try:
        await api_post(
            "https://api.erlc.gg/v1/server/command",
            headers={"Content-Type": "application/json", "Server-Key": SERVER_KEY},
            json={"command": f":ban {user_id} {reason}"},
        )
    except Exception as e:
        print(f"Failed to ban user ID: {user_id}: {e}")


async def logban(username, reason):
    try:
        from config import ERM_API_AUTH
        await api_post(
            "https://api.ermbot.xyz/api/Moderation/CreatPunishment",
            headers={"Content-Type": "application/json", "Authorization": ERM_API_AUTH},
            json={"username": username, "type": "Ban", "reason": reason},
        )
    except Exception as e:
        print(f"Failed to log ban: {e}")


class DurationModal(discord.ui.Modal, title="Enter Mute Duration"):
    duration = discord.ui.TextInput(label="Duration (e.g., 10m, 2h, 1d)", placeholder="Enter duration", required=True)

    def __init__(self, member, view):
        super().__init__()
        self.member = member
        self.view = view

    async def on_submit(self, interaction: discord.Interaction):
        time_multiplier = {'m': 60, 'h': 3600, 'd': 86400}
        duration_text = self.duration.value.lower()
        try:
            unit = duration_text[-1]
            if unit not in time_multiplier:
                raise ValueError("Invalid time format. Use m, h, or d.")
            amount = int(duration_text[:-1])
            if amount <= 0:
                raise ValueError("Duration must be greater than 0.")
            total_seconds = amount * time_multiplier[unit]
            if total_seconds > 604800:
                raise ValueError("Duration cannot exceed 7 days.")
            until_time = utcnow() + timedelta(seconds=total_seconds)
            await self.member.timeout(until_time, reason="Member was reported.")
            self.view.action_taken = "Mute"
            await interaction.response.send_message(
                embed=success_embed("User Muted", f"{self.member.mention} has been muted for `{duration_text}`."),
                ephemeral=True,
            )
        except ValueError as e:
            await interaction.response.send_message(embed=error_embed("Invalid Duration", str(e)), ephemeral=True)
        except discord.Forbidden:
            await interaction.response.send_message(embed=error_embed("Missing Permissions", "I do not have permission to mute that user."), ephemeral=True)


class PendingBanView(discord.ui.View):
    def __init__(self, user, message, initiator):
        super().__init__(timeout=15)
        self.user = user
        self.message = message
        self.initiator = initiator
        self.is_canceled = False

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user != self.initiator:
            await generalised_interaction_check_failure(interaction)
            return False
        return True

    async def on_timeout(self):
        if not self.is_canceled:
            embed = discord.Embed(title="Action Timed Out", description="The action has timed out.", color=BLANK_COLOR)
            brand_footer(embed)
            if self.message:
                try:
                    await self.message.edit(embed=embed, view=None)
                except discord.HTTPException:
                    pass

    @discord.ui.button(label="Confirm Ban", style=discord.ButtonStyle.danger)
    async def confirm_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        member = interaction.guild.get_member(self.user.id)
        case = "Unknown"
        try:
            with open(casefile, "r") as file:
                number = int(file.read().strip())
            number += 1
            with open(casefile, "w") as file:
                file.write(str(number))
                case = number
        except Exception:
            pass
        if member:
            try:
                dm = await member.create_dm()
                await dm.send(f"**Case #{case}** — You have been banned from California State Roleplay.\nReason: A message you sent has been reported.")
            except discord.Forbidden:
                pass
            await member.ban(reason="Reported message")
            if self.message:
                await self.message.delete()
            await interaction.response.send_message(embed=success_embed("User Banned", "The user has been banned."))

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.is_canceled = True
        await interaction.response.edit_message(embed=discord.Embed(title="Action Cancelled", description="The action has been cancelled.", color=BLANK_COLOR), view=None)


class ReportActionsView(discord.ui.View):
    def __init__(self, user, message, embed):
        super().__init__(timeout=None)
        self.user = user
        self.reported_message = message
        self.embed = embed
        self.message = None

    @discord.ui.button(label="Mute", style=discord.ButtonStyle.danger)
    async def mute_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        member = interaction.guild.get_member(self.user.id)
        if member:
            await interaction.response.send_modal(DurationModal(member, self))
        else:
            await interaction.response.send_message(embed=error_embed("User Not Found", "User is not in the server."), ephemeral=True)

    @discord.ui.button(label="Ban", style=discord.ButtonStyle.danger)
    async def ban_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        member = interaction.guild.get_member(self.user.id)
        await interaction.response.defer()
        if member:
            pending_embed = discord.Embed(
                title="Confirm Ban",
                description=(
                    f"Are you sure you want to ban **{member.display_name}**?\n\n"
                    f"> **Requested By:** {interaction.user.mention}\n"
                    f"> **Target:** {member.mention}"
                ),
                color=BLANK_COLOR,
            )
            pending_embed.set_author(name=interaction.guild.name, icon_url=interaction.guild.icon.url if interaction.guild.icon else "")
            brand_footer(pending_embed)
            pending_view = PendingBanView(self.user, None, interaction.user)
            pending_message = await interaction.channel.send(embed=pending_embed, view=pending_view)
            pending_view.message = pending_message
        else:
            await interaction.followup.send(embed=error_embed("User Not Found", "User is not in the server."), ephemeral=True)

    @discord.ui.button(label="Acknowledge", style=discord.ButtonStyle.secondary)
    async def acknowledge_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.embed.title = "Report Handled"
        self.embed.color = BLANK_COLOR
        self.embed.description = embed_description(
            self.embed.description or "",
            f"> **Action Taken:** Acknowledged by {interaction.user.mention}",
        )
        if self.message:
            await self.message.edit(embed=self.embed, view=None)
        await interaction.response.send_message(embed=success_embed("Report Acknowledged", "The report has been acknowledged."), ephemeral=True)


class LeaveFeedbackModal(discord.ui.Modal, title="Leave Feedback"):
    answer = discord.ui.TextInput(
        label="Your Response",
        style=discord.TextStyle.paragraph,
        placeholder="Type your answer here...",
        required=True,
        max_length=1000,
    )

    def __init__(self, question, question_num, total, guild_name):
        super().__init__()
        self.answer.label = f"Q{question_num}/{total}: {question}"[:45]
        self.question = question
        self.guild_name = guild_name

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.send_message(
            f"Thank you for your feedback on: **{self.question}**",
            ephemeral=True,
        )


class LeaveFeedbackView(discord.ui.View):
    def __init__(self, questions, guild_name, log_channel_id, bot):
        super().__init__(timeout=86400)
        self.questions = questions
        self.guild_name = guild_name
        self.log_channel_id = log_channel_id
        self.bot = bot
        self.responses = {}

        for i, q in enumerate(questions):
            button = discord.ui.Button(
                label=f"Question {i + 1}",
                style=discord.ButtonStyle.primary,
                custom_id=f"leave_fb_{i}",
                row=i // 5,
            )
            button.callback = self._make_callback(i, q)
            self.add_item(button)

    def _make_callback(self, index, question):
        async def callback(interaction: discord.Interaction):
            modal = LeaveFeedbackQuestionModal(
                question, index + 1, len(self.questions), self.guild_name, self, index
            )
            await interaction.response.send_modal(modal)
        return callback


class LeaveFeedbackQuestionModal(discord.ui.Modal, title="Leave Feedback"):
    answer = discord.ui.TextInput(
        label="Your Response",
        style=discord.TextStyle.paragraph,
        placeholder="Type your answer here...",
        required=True,
        max_length=1000,
    )

    def __init__(self, question, question_num, total, guild_name, parent_view, index):
        super().__init__()
        label = f"Q{question_num}: {question}"
        self.answer.label = label[:45]
        self.question = question
        self.guild_name = guild_name
        self.parent_view = parent_view
        self.index = index

    async def on_submit(self, interaction: discord.Interaction):
        self.parent_view.responses[self.index] = self.answer.value

        answered = len(self.parent_view.responses)
        total = len(self.parent_view.questions)

        if answered >= total and self.parent_view.log_channel_id and self.parent_view.bot:
            log_channel = self.parent_view.bot.get_channel(self.parent_view.log_channel_id)
            if log_channel:
                lines = []
                for i, q in enumerate(self.parent_view.questions):
                    resp = self.parent_view.responses.get(i, "No response")
                    lines.append(f"> **{q}**\n> {resp}")
                embed = discord.Embed(
                    title="Leave Feedback Received",
                    description=(
                        f"**User:** {interaction.user.mention} (`{interaction.user.name}`)\n\n"
                        + "\n\n".join(lines)
                    ),
                    color=BLANK_COLOR,
                    timestamp=utcnow(),
                )
                embed.set_author(name=self.guild_name, icon_url=CSRP_ICON)
                brand_footer(embed)
                try:
                    await log_channel.send(embed=embed)
                except discord.HTTPException:
                    pass

        await interaction.response.send_message(
            f"Thanks for answering! ({answered}/{total} questions answered)",
            ephemeral=True,
        )


class Events(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.sentry_errors = {}
        self.report_ctx_menu = discord.app_commands.ContextMenu(
            name="Report Message",
            callback=self._report_message_callback,
        )

    async def cog_load(self):
        self.bot.tree.add_command(self.report_ctx_menu)

    async def cog_unload(self):
        self.bot.tree.remove_command(self.report_ctx_menu.name, type=self.report_ctx_menu.type)

    @commands.Cog.listener()
    async def on_ready(self):
        logging.info(f"Logged in as {self.bot.user}.")
        try:
            await self.bot.tree.sync()
            logging.info("Slash commands synced successfully!")
        except Exception as e:
            logging.error(f"Error syncing commands: {e}")

        if not self.periodic_check.is_running():
            self.periodic_check.start()
        if not self.discord_checks.is_running():
            self.discord_checks.start()

        await self.bot.change_presence(activity=discord.Activity(type=discord.ActivityType.watching, name="CSRP | .gg/calf"))

        channel = self.bot.get_channel(int(LOGGING_CHANNEL_ID))
        if channel:
            embed = discord.Embed(
                title="Bot Online",
                description=f"Logged in as **{self.bot.user}** and ready to serve.",
                color=BLANK_COLOR,
                timestamp=utcnow(),
            )
            embed.set_author(name="CSRP Utilities", icon_url=CSRP_ICON)
            brand_footer(embed)
            await channel.send(embed=embed)

    async def _report_message_callback(self, interaction: discord.Interaction, message: discord.Message):
        mod_channel = self.bot.get_channel(MOD_CHANNEL_ID)
        if not mod_channel:
            await interaction.response.send_message(embed=error_embed("Channel Not Found", "Moderation channel not found."), ephemeral=True)
            return

        user = message.author
        try:
            await interaction.guild.fetch_member(user.id)
            in_server = True
        except discord.NotFound:
            in_server = False

        embed = discord.Embed(
            title="Message Reported",
            description=embed_description(
                (
                    f"> **Reporter:** {interaction.user.mention}\n"
                    f"> **User:** {user.mention if in_server else f'{user} (Not in server)'}\n"
                    f"> **Channel:** {message.channel.mention}"
                ),
                f"> **Message Content:** {message.content[:1024] if message.content else '(No text content)'}",
                f"> **Jump:** [Click Here]({message.jump_url})",
            ),
            color=BLANK_COLOR,
            timestamp=utcnow(),
        )
        embed.set_author(name=interaction.guild.name, icon_url=interaction.guild.icon.url if interaction.guild.icon else "")
        embed.set_footer(text=f"User ID: {user.id} • Reported by {interaction.user.name}", icon_url=CSRP_ICON)

        view = ReportActionsView(user, message, embed)
        report_msg = await mod_channel.send(content=f"<@&{MOD_ROLE_ID}>", embed=embed, view=view)
        view.message = report_msg

        await interaction.response.send_message(embed=success_embed("Report Submitted", "Report submitted successfully!"), ephemeral=True)

    @commands.Cog.listener()
    async def on_command_completion(self, ctx):
        log_channel = self.bot.get_channel(LOGGING_CHANNEL_ID)
        if log_channel:
            embed = discord.Embed(
                title="Command Logged",
                description=(
                    f"> **Command:** `{ctx.command}`\n"
                    f"> **User:** {ctx.author.mention}\n"
                    f"> **Channel:** {ctx.channel.mention}"
                ),
                color=BLANK_COLOR,
                timestamp=ctx.message.created_at,
            )
            embed.set_author(name="CSRP Utilities", icon_url=CSRP_ICON)
            embed.set_thumbnail(url=CSRP_ICON)
            embed.set_footer(text=f"User ID: {ctx.author.id}", icon_url=CSRP_ICON)
            await log_channel.send(embed=embed)

    @commands.Cog.listener()
    async def on_command_error(self, ctx, error):
        if isinstance(error, commands.MissingRequiredArgument):
            await ctx.send(embed=error_embed("Missing Argument", f"Missing required argument: `{error.param.name}`"))
            return
        if isinstance(error, commands.NotOwner):
            await ctx.send(embed=error_embed("Not Permitted", "You do not have permission to use this command."))
            return
        if isinstance(error, commands.CommandNotFound):
            return
        if isinstance(error, commands.MissingPermissions):
            await ctx.send(embed=error_embed("Not Permitted", "You do not have permission to use this command."))
            return
        if isinstance(error, commands.BotMissingPermissions):
            await ctx.send(embed=error_embed("Missing Permissions", "I lack the required permissions to execute this command. Please try again later."))
            return
        if isinstance(error, commands.CheckFailure):
            await ctx.send(embed=error_embed("Not Permitted", "You do not have permission to use this command."))
            return
        if isinstance(error, commands.MemberNotFound):
            await ctx.send(embed=error_embed("Member Not Found", "Could not find that member."))
            return
        if isinstance(error, commands.NoPrivateMessage):
            await ctx.send(embed=error_embed("Server Only", "This command cannot be used in private messages."))
            return

        await self._handle_command_error(ctx, error)

    async def _handle_command_error(self, ctx, error):
        error_id = f"error_{random.randint(100000, 999999)}"
        sentry_url = None

        log_channel = self.bot.get_channel(ERRORS_CHANNEL)
        if log_channel:
            try:
                embed = discord.Embed(
                    title="Error Logged",
                    description=embed_description(
                        (
                            f"> **Command:** `{ctx.command}`\n"
                            f"> **User:** {ctx.author.mention}\n"
                            f"> **Channel:** {ctx.channel.mention}\n"
                            f"> **Error ID:** `{error_id}`"
                        ),
                        f"```{str(error)[:1000]}```",
                    ),
                    color=BLANK_COLOR,
                    timestamp=ctx.message.created_at,
                )
                embed.set_author(name="CSRP Utilities", icon_url=CSRP_ICON)
                embed.set_thumbnail(url=CSRP_ICON)
                brand_footer(embed)
                await log_channel.send(embed=embed)
            except Exception as log_error:
                sentry_sdk.capture_exception(log_error)

        try:
            with sentry_sdk.push_scope() as scope:
                scope.set_tag("error_id", error_id)
                scope.set_context("Command Details", {
                    "user": ctx.author.id if ctx.author else "Unknown",
                    "command": ctx.command.name if ctx.command else "Unknown",
                    "channel": ctx.channel.name if ctx.channel else "DM",
                    "message": ctx.message.content if ctx.message else "Unknown",
                })
                event_id = sentry_sdk.capture_exception(error)
            sentry_url = f"https://sentry.io/organizations/csrpdevteam/issues/?query={event_id}"
        except Exception as sentry_error:
            sentry_sdk.capture_exception(sentry_error)

        self.sentry_errors[error_id] = {"user": ctx.author.name, "command": str(ctx.command), "channel": str(ctx.channel), "error": str(error)}

        if ctx.author.id in CSRPUTILS_DEVS:
            embed = discord.Embed(
                title="Command Failure",
                description=(
                    f"An error occurred. If this persists, please [join our support server](https://discord.gg/B8959ZPPpp).\n\n"
                    f"> {DEVELOPER} **{ctx.author.name}**, you are a CSRP Utilities developer."
                ),
                color=BLANK_COLOR,
            )
            embed.set_author(name="CSRP Utilities", icon_url=CSRP_ICON)
            embed.add_field(
                name="Debug Information",
                value=(
                    f"> **Error ID:** `{error_id}`\n"
                    + (f"> **Sentry:** [View Issue]({sentry_url})\n" if sentry_url else "> **Sentry:** N/A\n")
                ),
                inline=False,
            )
            brand_footer(embed)
            await ctx.send(embed=embed)
            return

        embed = discord.Embed(
            title="Command Failure",
            description=(
                "An error occurred. If this persists, please [join our support server](https://discord.gg/B8959ZPPpp).\n\n"
                f"> **Error ID:** `{error_id}`"
            ),
            color=BLANK_COLOR,
        )
        embed.set_author(name="CSRP Utilities", icon_url=CSRP_ICON)
        brand_footer(embed)
        await ctx.send(embed=embed)
        raise error

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot:
            return

        ctx = await self.bot.get_context(message)
        invoked_afk_command = bool(ctx.valid and ctx.command and ctx.command.qualified_name == "afk")

        afk_data = load_afk()

        user_id = str(message.author.id)
        if user_id in afk_data and not invoked_afk_command:
            old_nick = afk_data[user_id].get("name", message.author.display_name)
            try:
                if message.guild and message.guild.me.guild_permissions.manage_nicknames:
                    await message.author.edit(nick=old_nick)
            except (discord.Forbidden, discord.HTTPException):
                pass
            del afk_data[user_id]
            try:
                save_afk(afk_data)
                await message.channel.send(embed=success_embed("Welcome Back", f"Welcome back, {message.author.mention}! Your AFK status was removed."))
            except Exception:
                pass

        for mention in message.mentions:
            mention_id = str(mention.id)
            if mention_id in afk_data:
                reason = afk_data[mention_id]["reason"]
                if len(reason) > 1000:
                    reason = reason[:997] + "..."
                try:
                    embed = discord.Embed(
                        title="User is AFK",
                        description=f"{mention.mention} is AFK: `{reason}`",
                        color=BLANK_COLOR,
                    )
                    brand_footer(embed)
                    await message.channel.send(embed=embed, delete_after=10)
                except discord.HTTPException:
                    pass

        if self.bot.user in message.mentions:
            if "prefix" in message.content.lower():
                await message.channel.send(embed=info_embed("Bot Prefix", "My prefix is `?`."))

    @commands.Cog.listener()
    async def on_guild_join(self, guild):
        await self.bot.tree.sync(guild=guild)

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        if member.bot:
            return
        guild = member.guild
        settings = get_guild_settings(guild.id)
        if not settings.get("feedback_enabled"):
            return
        questions = settings.get("feedback_questions", [])
        if not questions:
            return

        log_channel_id = settings.get("retirement_log_channel")

        embed = discord.Embed(
            title="We're sorry to see you go!",
            description=(
                f"You recently left **{guild.name}**.\n\n"
                "We'd love to hear your feedback. Click the buttons below to answer each question."
            ),
            color=BLANK_COLOR,
        )
        embed.set_author(name=guild.name, icon_url=guild.icon.url if guild.icon else CSRP_ICON)
        brand_footer(embed)

        for i, q in enumerate(questions):
            embed.add_field(name=f"Question {i + 1}", value=q, inline=False)

        view = LeaveFeedbackView(questions, guild.name, log_channel_id, self.bot)

        try:
            await member.send(embed=embed, view=view)
        except discord.Forbidden:
            pass

    @tasks.loop(seconds=45)
    async def periodic_check(self):
        channel = self.bot.get_channel(int(BAN_CHANNEL))
        if not channel:
            return
        try:
            users = await check_usernames()
        except Exception:
            return

        if not users:
            return

        for user in users:
            try:
                alert_embed = discord.Embed(
                    title="Possible Raid Attempt Detected",
                    description=embed_description(
                        "A player with a suspicious username has been detected and automatically banned.",
                        (
                            f"> **Username:** `{user['username']}`\n"
                            f"> **User ID:** `{user['user_id']}`\n"
                            f"> **Team:** {user['team']}\n"
                            f"> **Permission:** {user['permission']}"
                        ),
                    ),
                    color=BLANK_COLOR,
                    timestamp=utcnow(),
                )
                alert_embed.set_author(name="California State Roleplay", icon_url=CSRP_ICON)
                alert_embed.set_thumbnail(url=CSRP_ICON)
                brand_footer(alert_embed)
                await channel.send(embed=alert_embed)

                ban_reason = "Banned for having a username that starts with 'all' or 'others'."
                await ban_user(user['user_id'], ban_reason)
                await logban(user['username'], ban_reason)

            except Exception as e:
                print(f"Error processing user {user['username']}: {e}")

    @tasks.loop(minutes=5)
    async def discord_checks(self):
        guild = self.bot.get_guild(965829463512330260)
        if not guild:
            return

        try:
            status, data = await api_get(
                "https://api.erlc.gg/v1/server/players",
                headers={"Server-Key": SERVER_KEY},
            )
            if status != 200 or not isinstance(data, list):
                return
        except Exception:
            return

        missing_members = []
        for player in data:
            if "Player" not in player:
                continue
            username = player["Player"].split(":")[0]
            pattern = re.compile(re.escape(username), re.IGNORECASE)
            member_found = any(
                pattern.search(member.name) or pattern.search(member.display_name) or
                (hasattr(member, "global_name") and member.global_name and pattern.search(member.global_name))
                for member in guild.members
            )
            if not member_found:
                missing_members.append(username)

        channel = self.bot.get_channel(1334017501754949642)
        if not channel:
            return

        if missing_members:
            missing_members = [u.strip() for u in missing_members]
            pm_command = f":pm {','.join(missing_members)} You must join our DC server using the code: CALF."

            try:
                status, _ = await api_post(
                    "https://api.erlc.gg/v1/server/command",
                    headers={"Content-Type": "application/json", "Server-Key": SERVER_KEY},
                    json={"command": str(pm_command)},
                )

                if status == 200:
                    embed = discord.Embed(
                        title="Discord Check Result",
                        description="The following users have been PMed:\n\n```\n" + "\n".join(missing_members) + "\n```",
                        color=BLANK_COLOR,
                    )
                else:
                    embed = discord.Embed(
                        title="PM Failure",
                        description=f"Failed to PM. Response Code: `{status}`",
                        color=BLANK_COLOR,
                    )
                embed.set_author(name="CSRP Utilities", icon_url=CSRP_ICON)
                brand_footer(embed)
                await channel.send(embed=embed)
            except Exception as e:
                embed = discord.Embed(
                    title="PM Failure",
                    description=f"Error sending PM command: `{e}`",
                    color=BLANK_COLOR,
                )
                embed.set_author(name="CSRP Utilities", icon_url=CSRP_ICON)
                brand_footer(embed)
                await channel.send(embed=embed)
        else:
            embed = discord.Embed(
                title="Discord Check Result",
                description="All players are in the Discord server.",
                color=BLANK_COLOR,
            )
            embed.set_author(name="CSRP Utilities", icon_url=CSRP_ICON)
            brand_footer(embed)
            await channel.send(embed=embed)


async def setup(bot):
    await bot.add_cog(Events(bot))
