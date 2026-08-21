import discord
from discord.ext import commands, tasks
from discord.utils import utcnow
import re
import json
import logging
import sentry_sdk
import uuid
import io
from datetime import timedelta, datetime

import asyncio
import aiohttp
import boto3
from botocore.exceptions import ClientError

from config import (
    HEADERS, KEY_HEADERS, LOGGING_CHANNEL_ID, MODERATION_ROLE_IDS,
    CHANNEL_ID, BAN_CHANNEL, LOG_SERVER_URL, LOG_SERVER_AUTH,
    LATENCY_API_URL, MOD_CHANNEL_ID, MOD_ROLE_ID,
    afk_file,
    AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, S3_BUCKET_NAME, AWS_REGION,
    BOT_ADMINISTRATION, STAFF_FEEDBACK_CHANNEL,
)
from cogs.helpers import (
    Colors, BLANK_COLOR, CSRP_ICON, CHECK, CROSS, PENDING,
    success_embed, error_embed, info_embed, brand_footer, embed_description, user_tag,
    api_get, api_post, generalised_interaction_check_failure,
)
from cogs.settings import get_guild_settings
from modlog_store import get_next_case


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
            headers=KEY_HEADERS,
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
            headers=HEADERS,
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
        case = get_next_case()
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
    CIRCLE_CHANNEL_ID = 988922384927055912
    CIRCLE_FILE_URL = "https://csrptickets-storage.s3.us-east-1.amazonaws.com/circle.mp3"
    SPAM_THRESHOLD = 5
    SPAM_WINDOW = 5.0

    SSU_GUILD_ID = 965829463512330260
    SSU_STAFF_ROLE_ID = 968852438922715176
    SSU_EXEMPT_ROLE_IDS = {
        1137117556348567614,
        1137129271769436340,
        985228543191548004,
        1441172991563141130,
    }
    SSU_EXEMPT_USER_IDS = {1092489655888379915}
    # Pinging these users never counts as asking staff for an SSU
    SSU_EXEMPT_PING_USER_IDS = {1092489655888379915}
    SSU_ANNOUNCE_CHANNEL_URL = "https://discord.com/channels/965829463512330260/1159839282635227286"
    SSU_REQUEST_RE = re.compile(
        "|".join(
            [
                # "host an SSU", "start SSU", "can we have an SSU", "do an SSU"
                r"\b(?:host|start|run|open|do|make|begin|hold|have)\s+(?:an?\s+|the\s+)?ssus?\b",
                # "I want an SSU", "we need an SSU", "wanna SSU"
                r"\b(?:want|wants|need|needs|wanna)\s+(?:an?\s+|the\s+)?ssus?\b",
                # "can we get an SSU", "give us an SSU"
                r"\b(?:get|give\s+(?:us|me))\s+(?:an?\s+|the\s+)?ssus?\b",
                # "wanna get on SSU", "hop on an SSU", "come on ssu", "jump in the ssu"
                r"\b(?:get|hop|jump|come|be|join|pop|log)\s+(?:on|onto|in|into|up)\s+(?:an?\s+|the\s+)?ssus?\b",
                # "let's SSU", "lets an ssu"
                r"\b(?:let'?s|lets)\s+(?:an?\s+|the\s+)?ssus?\b",
                # "who's hosting an SSU", "anyone doing ssu"
                r"\b(?:hosting|starting|running|doing|holding)\s+(?:an?\s+|the\s+)?ssus?\b",
                # "please SSU", "pls ssu"
                r"\b(?:please|pls|plz)\s+ssus?\b",
                # "SSU please", "SSU now", "SSU today", "SSU when", "SSU?"
                r"\bssus?\s+(?:please|pls|plz|now|today|tonight|soon|when|time|rn|tmr|tomorrow|later)\b",
                r"\bssus?\s*\?",
                # "when's the SSU", "when is the next SSU"
                r"\bwhen(?:'?s|\s+is|\s+will|\s+are)?\s+(?:the\s+|an?\s+)?(?:next\s+)?ssus?\b",
                # "any SSU", "is there gonna be an SSU", "will there be an SSU"
                r"\b(?:any|is\s+there(?:\s+gonna\s+be)?|will\s+there\s+be)\s+(?:an?\s+|the\s+)?ssus?\b",
                # "can you SSU", "can someone ssu"
                r"\bcan\s+(?:you|u|someone|somebody|we)\s+(?:please\s+|pls\s+|plz\s+)?ssus?\b",
            ]
        ),
        re.IGNORECASE,
    )

    def __init__(self, bot):
        self.bot = bot
        self._circle_timestamps: list[float] = []
        self.report_ctx_menu = discord.app_commands.ContextMenu(
            name="Report Message",
            callback=self._report_message_callback,
        )

    async def cog_load(self):
        self.bot.tree.add_command(self.report_ctx_menu)

    async def cog_unload(self):
        self.bot.tree.remove_command(self.report_ctx_menu.name, type=self.report_ctx_menu.type)

    def _get_s3_client(self):
        return boto3.client(
            "s3",
            region_name=AWS_REGION,
            aws_access_key_id=AWS_ACCESS_KEY_ID,
            aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
        )

    async def _handle_s3_upload(self, message: discord.Message):
        admin_role_ids = set(BOT_ADMINISTRATION)
        user_role_ids = {role.id for role in message.author.roles}
        if not (user_role_ids & admin_role_ids):
            await message.reply(
                embed=error_embed("Not Permitted", "You do not have permission to use this command."),
                mention_author=False,
            )
            return

        ref = message.reference
        if not ref or not ref.message_id:
            await message.reply(
                embed=error_embed("No Reply", "You must reply to a message that contains an image."),
                mention_author=False,
            )
            return

        try:
            target_message = await message.channel.fetch_message(ref.message_id)
        except (discord.NotFound, discord.HTTPException):
            await message.reply(
                embed=error_embed("Fetch Failed", "Could not fetch the replied message."),
                mention_author=False,
            )
            return

        image_url = None
        filename = None
        for attachment in target_message.attachments:
            if attachment.content_type and attachment.content_type.startswith("image/"):
                image_url = attachment.url
                filename = attachment.filename
                break

        if not image_url and target_message.embeds:
            for embed in target_message.embeds:
                if embed.image and embed.image.url:
                    image_url = embed.image.url
                    filename = image_url.split("/")[-1].split("?")[0] or "image.png"
                    break
                if embed.thumbnail and embed.thumbnail.url:
                    image_url = embed.thumbnail.url
                    filename = image_url.split("/")[-1].split("?")[0] or "image.png"
                    break

        if not image_url:
            await message.reply(
                embed=error_embed("No Image", "The replied message does not contain an image."),
                mention_author=False,
            )
            return

        ext = filename.rsplit(".", 1)[-1] if "." in filename else "png"
        object_key = f"uploads/{uuid.uuid4().hex}.{ext}"

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(image_url) as resp:
                    if resp.status != 200:
                        await message.reply(
                            embed=error_embed("Download Failed", "Failed to download the image from Discord."),
                            mention_author=False,
                        )
                        return
                    image_data = await resp.read()
                    content_type = resp.headers.get("Content-Type", f"image/{ext}")
        except Exception as e:
            await message.reply(
                embed=error_embed("Download Error", f"Error downloading image: `{e}`"),
                mention_author=False,
            )
            return

        try:
            s3 = self._get_s3_client()
            await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: s3.put_object(
                    Bucket=S3_BUCKET_NAME,
                    Key=object_key,
                    Body=image_data,
                    ContentType=content_type,
                ),
            )
        except ClientError as e:
            await message.reply(
                embed=error_embed("Upload Failed", f"S3 upload failed: `{e}`"),
                mention_author=False,
            )
            return

        object_url = f"https://{S3_BUCKET_NAME}.s3.{AWS_REGION}.amazonaws.com/{object_key}"
        await message.reply(
            embed=success_embed("S3 Upload Complete", f"**Object URL:**\n{object_url}"),
            mention_author=False,
        )

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
                    f"> **User:** {user_tag(ctx.author)}\n"
                    f"> **Channel:** {ctx.channel.mention}"
                ),
                color=BLANK_COLOR,
                timestamp=ctx.message.created_at,
            )
            embed.set_author(name="CSRP Utilities", icon_url=CSRP_ICON)
            embed.set_thumbnail(url=CSRP_ICON)
            embed.set_footer(text=f"User ID: {ctx.author.id}", icon_url=CSRP_ICON)
            await log_channel.send(embed=embed)

    async def _check_ssu_ping(self, message: discord.Message):
        if not message.guild or message.guild.id != self.SSU_GUILD_ID:
            return
        # A message that's nothing but "ssu" alongside the ping counts as a request too
        bare_content = re.sub(r"<@[!&#]?\d+>", "", message.content).strip().strip("!?.,~ ").lower()
        if bare_content not in ("ssu", "ssus") and not self.SSU_REQUEST_RE.search(message.content):
            return

        author = message.author
        if author.id == message.guild.owner_id or author.id in self.SSU_EXEMPT_USER_IDS:
            return
        if any(role.id in self.SSU_EXEMPT_ROLE_IDS for role in author.roles):
            return

        author_is_staff = any(r.id == self.SSU_STAFF_ROLE_ID for r in author.roles)
        pinged_staff = any(r.id == self.SSU_STAFF_ROLE_ID for r in message.role_mentions) or any(
            isinstance(m, discord.Member) and any(r.id == self.SSU_STAFF_ROLE_ID for r in m.roles)
            and m.id not in self.SSU_EXEMPT_PING_USER_IDS
            and not (author_is_staff and m.id == author.id)
            for m in message.mentions
        )
        if not pinged_staff:
            return
        for member in message.mentions:
            has_ssu_role = any(role.id in SSU_STAFF_ROLE_ID for role in member.roles) 
        if not has_ssu_role and not “host ssu”in message.content.lower():
            pass
        embed = discord.Embed(
            title="⚠️ Asking for an SSU",
            description=(
                "Please don't ping staff to host an SSU. When a Session Commences, "
                f"you'll see it in {self.SSU_ANNOUNCE_CHANNEL_URL}. Continued pinging "
                "of staff for this reason will result in moderation. Thank you!"
            ),
            color=discord.Color.yellow(),
        )
        brand_footer(embed)
        try:
            await message.reply(embed=embed, mention_author=False)
        except discord.HTTPException:
            pass

    @commands.Cog.listener()
    async def on_message(self, message):
        TICKET_CATEGORY_ID = 1176986720772833421

        if message.channel.id == self.CIRCLE_CHANNEL_ID and not message.author.bot and "circle" in message.content:
            now = asyncio.get_event_loop().time()
            self._circle_timestamps = [t for t in self._circle_timestamps if now - t < self.SPAM_WINDOW]
            if len(self._circle_timestamps) < self.SPAM_THRESHOLD:
                self._circle_timestamps.append(now)
                try:
                    async with aiohttp.ClientSession() as session:
                        async with session.get(self.CIRCLE_FILE_URL) as resp:
                            if resp.status == 200:
                                data = await resp.read()
                                file = discord.File(io.BytesIO(data), filename="circle.mp3")
                                await message.reply(file=file, mention_author=False)
                except Exception:
                    pass

        if message.author.bot:
            if (
                message.channel.category_id == TICKET_CATEGORY_ID
                and message.embeds
            ):
                for embed in message.embeds:
                    text_to_check = " ".join(filter(None, [
                        embed.description or "",
                        embed.title or "",
                        " ".join(f.value for f in embed.fields if f.value),
                    ])).lower()
                    fastpass_keywords = ["fast pass", "fastpass", "quick pass", "quickpass", "transfer"]
                    if any(keyword in text_to_check for keyword in fastpass_keywords):
                        await message.channel.send(
                            "<:CSRP:1170178385595609158> **| FastPass/Transfers**\n"
                            "In order to better assist you, please provide the following:\n"
                            "- Your timezone\n"
                            "- Link to the server you are transferring from\n"
                            "- Proof of your roles there"
                        )
                        try:
                            await message.channel.edit(name="⚪-ia")
                        except (discord.Forbidden, discord.HTTPException):
                            pass
                        break
            return

        await self._check_ssu_ping(message)

        ctx = await self.bot.get_context(message)

        if message.channel.id == STAFF_FEEDBACK_CHANNEL:
            is_feedback_cmd = ctx.valid and ctx.command and ctx.command.qualified_name == "staff_feedback"
            exempt_role_ids = {1137117556348567614, 1137129271769436340, 1160302513820536882, 985228543191548004}
            is_exempt = isinstance(message.author, discord.Member) and any(
                role.id in exempt_role_ids for role in message.author.roles
            )
            if not is_feedback_cmd and not is_exempt:
                try:
                    await message.delete()
                except (discord.Forbidden, discord.NotFound, discord.HTTPException):
                    pass
                return

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

            if "s3upload" in message.content.lower():
                await self._handle_s3_upload(message)

    @commands.Cog.listener()
    async def on_guild_join(self, guild):
        await self.bot.tree.sync(guild=guild)

    @commands.Cog.listener()
    async def on_member_ban(self, guild: discord.Guild, user):
        log_channel = self.bot.get_channel(1317814337532072027)
        if not log_channel:
            return

        # user is only a Member (with roles) if they were cached when banned
        if isinstance(user, discord.Member):
            roles = [r.mention for r in reversed(user.roles) if r != guild.default_role]
            roles_text = ", ".join(roles) if roles else "None"
            if len(roles_text) > 1024:
                roles_text = roles_text[:1010].rsplit(",", 1)[0] + ", ..."
        else:
            roles_text = "Unknown (member was not in cache)"

        embed = discord.Embed(
            title="Member Banned",
            description=(
                f"> **User:** {user_tag(user)}\n"
                f"> **User ID:** {user.id}"
            ),
            color=BLANK_COLOR,
            timestamp=discord.utils.utcnow(),
        )
        embed.add_field(name="Roles", value=roles_text, inline=False)
        embed.set_author(name="CSRP Utilities", icon_url=CSRP_ICON)
        embed.set_thumbnail(url=user.display_avatar.url)
        embed.set_footer(text=f"User ID: {user.id}", icon_url=CSRP_ICON)
        await log_channel.send(embed=embed)

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
        settings = get_guild_settings(guild.id)
        if not settings.get("discord_checks_enabled", True):
            return

        try:
            status, data = await api_get(
                "https://api.erlc.gg/v1/server/players",
                headers=KEY_HEADERS,
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
                    headers=HEADERS,
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
