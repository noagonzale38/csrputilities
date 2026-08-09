import discord
from discord.ext import commands
from discord import app_commands
import time
import io
import contextlib
import os
import re
import shlex
import subprocess
import traceback
import logging
from dateutil.parser import parse as parse_time_str
from moviepy.editor import VideoFileClip
import aiohttp
import asyncio

from config import (
    LATENCY_API_URL, LOG_SERVER_AUTH, COOKIE_API_AUTH,
    SENTRY_API_KEY, DEV_ROLE_ID_ADMIN,
    is_support, is_bot_dev, is_bot_staff, is_sales_authorized,
)
from cogs.helpers import (
    Colors, BLANK_COLOR, CSRP_ICON, CSRP_BANNER, CHECK, CROSS, ONLINE, LOADING, PENDING,
    success_embed, error_embed, info_embed, loading_embed, brand_footer, embed_description,
    api_get, ConfirmView, PaginatorView, generalised_interaction_check_failure,
)
from cogs.settings import get_guild_settings, has_setting_permission, member_has_rank_or_higher
from cogs.erlc import _resolve_roblox_users, _resolve_roblox_username
from lib.claude_runner import ClaudeRunControl, stream_claude_prompt

MESSAGE_LINK_RE = re.compile(
    r"https?://(?:ptb\.|canary\.)?discord(?:app)?\.com/channels/(\d+)/(\d+)/(\d+)"
)

start_time = time.time()
CLAUDE_PREVIEW_LIMIT = 1200
CLAUDE_CONTEXT_LIMIT = 6000

database_options = {
    "postgres": "ticketsbot",
    "postgres-archive": "archive",
    "postgres-cache": "botcache",
}

RXX_QUEUE_CATEGORY_ID = 1139516721166827531
RXX_QUEUE_ALLOWED_ROLE_IDS = {
    1137117556348567614,
    1131166127964291172,
    1157648329619021844,
    793162371702194207,
}
RXX_QUEUE_SOURCE_CATEGORY_IDS = {
    1250633639545536523,
    1176986720772833421,
    1191433020868132924,
}


def _truncate_tail(value: str, limit: int) -> str:
    value = value.strip()
    if len(value) <= limit:
        return value
    return f"...\n{value[-limit:]}"


def _sanitize_codeblock(value: str) -> str:
    return value.replace("```", "​`​`​`")


class ClaudeReplyModal(discord.ui.Modal, title="Reply to Claude"):
    reply_prompt = discord.ui.TextInput(
        label="Follow-up Prompt",
        style=discord.TextStyle.paragraph,
        max_length=4000,
    )

    def __init__(self, session_view: "ClaudeSessionView"):
        super().__init__()
        self.session_view = session_view

    async def on_submit(self, interaction: discord.Interaction):
        await self.session_view.start_follow_up(interaction, self.reply_prompt.value)


class ClaudeSessionView(discord.ui.View):
    def __init__(self, cog: "Utility", ctx: commands.Context, prompt: str):
        super().__init__(timeout=None)
        self.cog = cog
        self.ctx = ctx
        self.owner = ctx.author
        self.prompt = prompt
        self.message: discord.Message | None = None
        self.control: ClaudeRunControl | None = None
        self.latest_stdout = ""
        self.latest_stderr = ""
        self.last_return_code: int | None = None
        self.last_error: str | None = None
        self.run_task: asyncio.Task | None = None
        self.finished = False
        self.stop_requested = False
        self.timed_out = False
        self._set_button_states()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner.id:
            await generalised_interaction_check_failure(interaction)
            return False
        return True

    def _set_button_states(self) -> None:
        if self.timed_out:
            for child in self.children:
                child.disabled = True
            return
        self.reply_button.disabled = not self.finished
        self.stop_button.disabled = self.finished
        self.restart_button.disabled = not self.finished

    def build_embed(self) -> discord.Embed:
        summary = []
        if self.last_error:
            summary.append("> **Status:** Failed to Start")
        elif self.finished:
            if self.stop_requested:
                summary.append("> **Status:** Stopped")
            else:
                summary.append(f"> **Status:** {'Completed' if self.last_return_code == 0 else 'Failed'}")
            if self.last_return_code is not None:
                summary.append(f"> **Exit Code:** `{self.last_return_code}`")
            summary.append("> **Controls:** Use `Reply to Claude` below to continue this session")
        else:
            summary.append("> **Status:** Running")
            summary.append("> **Controls:** Use `Stop Claude` below to cancel this run")
        summary.append(f"> **User:** {self.owner.mention}")
        summary.append(f"> **Prompt:** `{self.prompt[:200]}`")
        if self.latest_stdout.strip():
            preview = _sanitize_codeblock(_truncate_tail(self.latest_stdout, CLAUDE_PREVIEW_LIMIT))
            summary.append(f"**Stdout Preview:**\n```\n{preview}\n```")
        filtered_stderr = "\n".join(
            line for line in self.latest_stderr.splitlines()
            if "no stdin data received" not in line
        )
        if filtered_stderr.strip():
            preview = _sanitize_codeblock(_truncate_tail(filtered_stderr, CLAUDE_PREVIEW_LIMIT))
            summary.append(f"**Stderr Preview:**\n```\n{preview}\n```")
        if self.last_error:
            summary.append(f"> **Error:** `{self.last_error[:300]}`")

        description = "\n".join(summary)
        if len(description) > 4000:
            description = description[:4000] + "\n..."

        embed = discord.Embed(
            title="Claude Command Complete" if self.finished else "Claude Command Running",
            description=description,
            color=BLANK_COLOR if (self.last_return_code in (None, 0) and not self.last_error) else discord.Color.red(),
        )
        author_name = self.ctx.guild.name if self.ctx.guild else self.owner.display_name
        embed.set_author(
            name=author_name,
            icon_url=self.ctx.guild.icon.url if self.ctx.guild and self.ctx.guild.icon else "",
        )
        brand_footer(embed)
        return embed

    async def refresh_message(self) -> None:
        self._set_button_states()
        if not self.message:
            return
        try:
            await self.message.edit(embed=self.build_embed(), view=self)
        except discord.HTTPException as exc:
            logging.warning("Failed to update Claude session embed: %s", exc)

    def _build_follow_up_prompt(self, prompt: str) -> str:
        prior_stdout = _truncate_tail(self.latest_stdout, CLAUDE_CONTEXT_LIMIT) or "(no stdout)"
        prior_stderr = _truncate_tail(self.latest_stderr, CLAUDE_CONTEXT_LIMIT // 2) or "(no stderr)"
        return (
            "Continue this Claude task using the previous run as context.\n\n"
            f"Previous prompt:\n{self.prompt}\n\n"
            f"Previous stdout:\n{prior_stdout}\n\n"
            f"Previous stderr:\n{prior_stderr}\n\n"
            f"Follow-up request:\n{prompt}"
        )

    async def _send_output_file(self) -> None:
        output_sections = []
        if self.latest_stdout.strip():
            output_sections.append(self.latest_stdout.strip())
        if self.last_error:
            output_sections.append(f"ERROR\n{'=' * 5}\n{self.last_error}")

        if not output_sections:
            return

        with contextlib.suppress(discord.HTTPException):
            output_file = discord.File(
                io.BytesIO("\n\n".join(output_sections).encode("utf-8")),
                filename="claude-output.txt",
            )
            await self.ctx.send(file=output_file)

    async def start_run(self, prompt: str) -> None:
        self.prompt = prompt
        self.latest_stdout = ""
        self.latest_stderr = ""
        self.last_return_code = None
        self.last_error = None
        self.finished = False
        self.stop_requested = False
        self.control = ClaudeRunControl()
        await self.refresh_message()

        async def on_update(stdout_text: str, stderr_text: str, finished: bool):
            self.latest_stdout = stdout_text
            self.latest_stderr = stderr_text
            if not finished:
                await self.refresh_message()

        try:
            return_code, stdout, stderr = await stream_claude_prompt(
                prompt,
                on_update=on_update,
                update_interval=15,
                control=self.control,
            )
            self.last_return_code = return_code
            self.latest_stdout = stdout
            self.latest_stderr = stderr
        except OSError as exc:
            self.last_error = str(exc)
        finally:
            self.finished = True
            self.control = None
            if self.cog._active_claude_sessions.get(self.owner.id) is self:
                self.cog._active_claude_sessions.pop(self.owner.id, None)
            await self._send_output_file()
            await self.refresh_message()

    async def start_follow_up(self, interaction: discord.Interaction, reply_prompt: str) -> None:
        if not self.finished:
            await interaction.response.send_message(
                embed=error_embed("Claude Busy", "Wait for the current Claude run to finish before replying."),
                ephemeral=True,
            )
            return

        if self.run_task and not self.run_task.done():
            await interaction.response.send_message(
                embed=error_embed("Claude Busy", "A follow-up run is already starting."),
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True, thinking=False)
        follow_up_prompt = self._build_follow_up_prompt(reply_prompt)
        self.cog._active_claude_sessions[self.owner.id] = self
        self.cog._track_claude_session_task(self, self.start_run(follow_up_prompt))
        await interaction.followup.send("Started follow-up Claude run.", ephemeral=True)

    @discord.ui.button(label="Reply to Claude", style=discord.ButtonStyle.primary)
    async def reply_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(ClaudeReplyModal(self))

    @discord.ui.button(label="Stop Claude", style=discord.ButtonStyle.danger)
    async def stop_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.finished or self.control is None:
            await interaction.response.send_message(
                embed=info_embed("Claude Not Running", "There is no active Claude process to stop."),
                ephemeral=True,
            )
            return

        self.stop_requested = True
        await interaction.response.defer(ephemeral=True, thinking=False)
        await self.control.stop()
        await interaction.followup.send("Stopping the active Claude run.", ephemeral=True)

    @discord.ui.button(label="Restart Bot", style=discord.ButtonStyle.secondary)
    async def restart_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.finished:
            await interaction.response.send_message(
                embed=error_embed("Claude Running", "Wait for the Claude run to finish before restarting."),
                ephemeral=True,
            )
            return

        await interaction.response.send_message(
            embed=success_embed("Restarting", "Restarting bot with PM2..."),
            ephemeral=True,
        )
        asyncio.create_task(self._pm2_restart())

    async def _pm2_restart(self) -> None:
        await asyncio.sleep(1.0)
        try:
            process = await asyncio.create_subprocess_exec(
                "pm2", "restart", "bot",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await process.communicate()
        except Exception as exc:
            logging.error("Failed to restart bot with pm2: %s", exc)

    async def on_timeout(self):
        if self.run_task and not self.run_task.done():
            return
        self.timed_out = True
        await self.refresh_message()


class Utility(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.start_time = start_time
        self._active_claude_sessions: dict[int, ClaudeSessionView] = {}

    async def _send_partnership_log(self, ctx: commands.Context, target_channel, content: str, message_link: str = None, sent_message=None):
        settings = get_guild_settings(ctx.guild.id)
        log_channel_id = settings.get("partnership_log_channel")
        if not log_channel_id:
            return

        try:
            log_channel = self.bot.get_channel(int(log_channel_id))
        except (TypeError, ValueError):
            return
        if log_channel is None:
            return

        source = "Dashboard" if ctx.__class__.__name__ == "DashboardCommandContext" else "Bot Command"
        content_preview = content or "(No text content)"
        if len(content_preview) > 1024:
            content_preview = f"{content_preview[:1021]}..."

        embed = discord.Embed(
            title="Partnership Sent",
            color=discord.Color.yellow(),
            timestamp=discord.utils.utcnow(),
        )
        embed.add_field(name="Sent By", value=f"{ctx.author.mention} (`{ctx.author.id}`)", inline=False)
        embed.add_field(name="Source", value=source, inline=True)
        embed.add_field(name="Destination", value=getattr(target_channel, "mention", f"`{target_channel.id}`"), inline=True)
        embed.add_field(name="Content", value=content_preview, inline=False)
        if message_link:
            embed.add_field(name="Source Message", value=message_link, inline=False)
        jump_url = getattr(sent_message, "jump_url", None)
        if jump_url:
            embed.add_field(name="Sent Message", value=jump_url, inline=False)
        brand_footer(embed)

        try:
            await log_channel.send(embed=embed)
        except discord.HTTPException:
            pass

    def _iter_slash_commands(self):
        for command in self.bot.tree.walk_commands():
            if isinstance(command, app_commands.ContextMenu):
                continue
            yield command

    def _command_lookup(self):
        return {
            command.qualified_name.lower(): command
            for command in self._iter_slash_commands()
        }

    def _command_parameters(self, command) -> str:
        params = getattr(command, "parameters", [])
        if isinstance(params, dict):
            params = params.values()

        parts = []
        for param in params:
            display_name = getattr(param, "display_name", None) or getattr(param, "name", None)
            if not display_name:
                continue
            required = getattr(param, "required", False)
            parts.append(f"<{display_name}>" if required else f"[{display_name}]")
        return " ".join(parts) if parts else "None"

    def _track_claude_session_task(self, session_view: ClaudeSessionView, coro) -> None:
        task = asyncio.create_task(coro)
        session_view.run_task = task

        def _consume_task_result(completed_task: asyncio.Task) -> None:
            with contextlib.suppress(asyncio.CancelledError):
                exc = completed_task.exception()
                if exc is not None:
                    logging.error(
                        "Unhandled error in Claude session task",
                        exc_info=(type(exc), exc, exc.__traceback__),
                    )

        task.add_done_callback(_consume_task_result)

    def _command_category(self, qualified_name: str) -> str:
        if qualified_name.startswith("erlc "):
            return "ERLC"
        if qualified_name.startswith("hit "):
            return "Hits"
        if qualified_name.startswith("embed "):
            return "Embeds"
        if qualified_name.startswith("api "):
            return "API"

        exact_map = {
            "ban": "Moderation",
            "clear_all_modlogs": "Moderation",
            "clear_modlogs": "Moderation",
            "infract": "Moderation",
            "kick": "Moderation",
            "lookup": "Moderation",
            "modlogs": "Moderation",
            "moderationsync": "Moderation",
            "mute": "Moderation",
            "unban": "Moderation",
            "unmute": "Moderation",
            "warn": "Moderation",
            "fail": "Training",
            "pass": "Training",
            "training-result": "Training",
            "demote": "Staff",
            "retire": "Staff",
            "reinstate": "Staff",
            "staff_feedback": "Staff",
            "play": "Music",
            "queue": "Music",
            "nowplaying": "Music",
            "skip": "Music",
            "pause": "Music",
            "resume": "Music",
            "stop": "Music",
            "afk": "Fun",
            "trivia": "Fun",
            "1v1trivia": "Fun",
            "remindme": "Fun",
            "ship": "Fun",
            "coinflip": "Fun",
            "8ball": "Fun",
            "avatar": "Fun",
            "who_is_cool": "Fun",
            "vctts": "Fun",
            "dog": "Fun",
            "cat": "Fun",
            "session": "Sessions",
            "sessioninfo": "Sessions",
            "command_blacklist": "Admin",
            "remove_blacklist": "Admin",
            "report_blacklist": "Admin",
            "remove_reportblacklist": "Admin",
        }
        return exact_map.get(qualified_name, "Utility")

    def _normalize_sql_input(self, command: str) -> str:
        command = command.strip()
        if not command:
            return command

        try:
            parts = shlex.split(command)
        except ValueError:
            return command

        if not parts:
            return command

        if parts[0] == "docker" and len(parts) > 1 and parts[1] in {"exec", "compose"}:
            try:
                psql_index = parts.index("psql")
            except ValueError:
                return command
            parts = parts[psql_index:]
        elif parts[0] != "psql" and not (len(parts) > 1 and parts[1] == "psql"):
            return command
        elif parts[0] != "psql":
            parts = parts[1:]

        if not parts or parts[0] != "psql":
            return command

        index = 1
        option_tokens = {"-U", "-d", "-h", "-p", "-v", "--username", "--dbname", "--host", "--port", "--set"}
        flag_tokens = {"-t", "-A", "-q", "-X", "-i", "-n", "-1", "--single-transaction", "--echo-errors"}

        while index < len(parts):
            token = parts[index]
            if token == "-c" and index + 1 < len(parts):
                return parts[index + 1]
            if token in option_tokens and index + 1 < len(parts):
                index += 2
                continue
            if token in flag_tokens:
                index += 1
                continue
            return " ".join(parts[index:])

        return command

    @commands.hybrid_command(name="ping", description="Shows the bot's latency.")
    async def ping(self, ctx):
        bot_latency = round(self.bot.latency * 1000)
        api_latency = "N/A"
        try:
            headers = {"Authorization": LOG_SERVER_AUTH}
            status, data = await api_get(LATENCY_API_URL, headers=headers, timeout=5)
            if data:
                api_latency = data.get('latency', 'N/A')
        except Exception:
            pass

        embed = discord.Embed(
            title="Pong!",
            description=(
                f"> **Bot Latency:** `{bot_latency}ms`\n"
                f"> **API Latency:** `{api_latency}`"
            ),
            color=BLANK_COLOR,
        )
        embed.set_author(name=ctx.guild.name, icon_url=ctx.guild.icon.url if ctx.guild.icon else "")
        brand_footer(embed)
        await ctx.send(embed=embed)

    @commands.hybrid_command(name="uptime", description="Shows how long the bot has been online.")
    async def uptime(self, ctx):
        uptime_seconds = int(time.time() - self.start_time)
        days, remainder = divmod(uptime_seconds, 86400)
        hours, remainder = divmod(remainder, 3600)
        minutes, seconds = divmod(remainder, 60)

        parts = []
        if days:
            parts.append(f"**{days}**d")
        if hours:
            parts.append(f"**{hours}**h")
        if minutes:
            parts.append(f"**{minutes}**m")
        parts.append(f"**{seconds}**s")

        embed = discord.Embed(
            title="Uptime",
            description=(
                f"> **Duration:** {' '.join(parts)}\n"
                f"> **Started:** <t:{int(self.start_time)}:R>"
            ),
            color=BLANK_COLOR,
        )
        embed.set_author(name=ctx.guild.name, icon_url=ctx.guild.icon.url if ctx.guild.icon else "")
        brand_footer(embed)
        await ctx.send(embed=embed)

    @commands.hybrid_command(name="help", description="Get help with the bot.")
    async def help(self, ctx):
        latency = round(self.bot.latency * 1000)
        categories = {}
        for command in sorted(self._iter_slash_commands(), key=lambda cmd: cmd.qualified_name):
            qualified_name = command.qualified_name
            category = self._command_category(qualified_name)
            categories.setdefault(category, []).append(f"`/{qualified_name}`")

        category_order = [
            "Moderation",
            "ERLC",
            "Sessions",
            "Training",
            "Staff",
            "Fun",
            "Music",
            "Hits",
            "Embeds",
            "API",
            "Admin",
            "Utility",
        ]
        command_sections = []
        for category in category_order:
            commands_in_category = categories.get(category)
            if commands_in_category:
                command_sections.append(f"> **{category}** — {', '.join(commands_in_category)}")

        embed = discord.Embed(
            title="CSRP Utilities",
            description=embed_description(
                f"Hello, **{ctx.author.name}**! Here is some information about the bot.",
                (
                    f"> {ONLINE} **Online**\n"
                    f"> **Latency:** `{latency}ms`\n"
                    f"> **Uptime:** <t:{int(self.start_time)}:R>"
                ),
                "\n".join(command_sections),
                (
                    "> **Support:** [Join our support server](https://discord.gg/B8959ZPPpp)\n"
                    "> **Status Page:** [View Status](https://botstatus.csrperlc.com)\n"
                    "> **Creator:** `noagonzale38`"
                ),
            ),
            color=BLANK_COLOR,
        )
        embed.set_author(name="CSRP Utilities", icon_url=CSRP_ICON)
        embed.set_thumbnail(url=ctx.author.display_avatar.url)
        brand_footer(embed)
        await ctx.reply(embed=embed)

    @commands.hybrid_command(name="help_command", description="Get help with a specific command.")
    @app_commands.describe(command="The name of the command to get help with.")
    async def help_command(self, ctx: commands.Context, command: str):
        lookup = self._command_lookup()
        app_command = lookup.get(command.lower().strip())
        if not app_command:
            await ctx.send(embed=error_embed("Command Not Found", f"Command `{command}` not found. Use `/help` to see all commands."))
            return

        description = getattr(app_command, "description", None) or "No description provided."
        params = self._command_parameters(app_command)
        category = self._command_category(app_command.qualified_name)
        embed = discord.Embed(
            title=f"Help — /{app_command.qualified_name}",
            description=(
                f"> **Description:** {description}\n"
                f"> **Category:** `{category}`\n"
                f"> **Parameters:** `{params}`\n"
                f"> **Access:** `Role and permission checks apply in-server.`"
            ),
            color=BLANK_COLOR,
        )
        embed.set_author(name="CSRP Utilities", icon_url=CSRP_ICON)
        embed.set_thumbnail(url=CSRP_ICON)
        brand_footer(embed)
        await ctx.send(embed=embed)

    @help_command.autocomplete("command")
    async def command_autocomplete(self, interaction: discord.Interaction, current: str):
        command_list = sorted(self._command_lookup())
        return [app_commands.Choice(name=cmd, value=cmd) for cmd in command_list if current.lower() in cmd.lower()][:25]

    @commands.hybrid_command(name="dashboard", description="Get a link to the CSRP Utilities Dashboard.")
    async def dashboard(self, ctx):
        guild = ctx.guild
        embed = discord.Embed(title="Dashboard", description="To visit the CSRP Utilities Dashboard, click [here](https://dashstaging.officialcaliforniastateroleplay.com).", color=BLANK_COLOR, timestamp=discord.utils.utcnow())
        embed.set_author(name=guild.name, icon_url=guild.icon.url if guild.icon else "")
        if guild.icon:
            embed.set_thumbnail(url=guild.icon.url)
        brand_footer(embed)
        await ctx.send(embed=embed)

    @commands.hybrid_command(name="serverinfo", description="Shows information about the server.")
    async def serverinfo(self, ctx):
        guild = ctx.guild
        description = embed_description(
            (
                f"> **Owner:** {guild.owner.mention if guild.owner else 'Unknown'}\n"
                f"> **Created:** <t:{int(guild.created_at.timestamp())}:R>\n"
                f"> **Members:** `{guild.member_count}`"
            ),
            (
                f"> **Channels:** `{len(guild.text_channels)}` text • `{len(guild.voice_channels)}` voice\n"
                f"> **Roles:** `{len(guild.roles)}`\n"
                f"> **Boosts:** `{guild.premium_subscription_count}` (Tier {guild.premium_tier})"
            ),
        )
        embed = discord.Embed(title=guild.name, description=description, color=BLANK_COLOR, timestamp=discord.utils.utcnow())
        embed.set_author(name=guild.name, icon_url=guild.icon.url if guild.icon else "")
        if guild.icon:
            embed.set_thumbnail(url=guild.icon.url)
        if guild.banner:
            embed.set_image(url=guild.banner.url)
        brand_footer(embed)
        await ctx.send(embed=embed)

    @commands.hybrid_command(name="userinfo", description="Shows information about a user.")
    @app_commands.describe(user="The user to get info about")
    async def userinfo(self, ctx, user: discord.Member = None):
        user = user or ctx.author
        description_parts = [
            (
                f"> **Username:** `{user.name}`\n"
                f"> **ID:** `{user.id}`\n"
                f"> **Status:** `{user.status}`"
            ),
            (
                f"> **Account Created:** <t:{int(user.created_at.timestamp())}:R>\n"
                f"> **Joined Server:** {f'<t:{int(user.joined_at.timestamp())}:R>' if user.joined_at else 'Unknown'}"
            ),
        ]
        roles = [r.mention for r in reversed(user.roles) if r != ctx.guild.default_role]
        if roles:
            role_text = ", ".join(roles[:10])
            if len(roles) > 10:
                role_text += f" (+{len(roles) - 10} more)"
            description_parts.append(f"> **Roles ({len(roles)}):** {role_text}")
        embed = discord.Embed(title=user.display_name, description=embed_description(*description_parts), color=BLANK_COLOR)
        embed.set_author(name=ctx.guild.name, icon_url=ctx.guild.icon.url if ctx.guild.icon else "")
        embed.set_thumbnail(url=user.display_avatar.url)
        brand_footer(embed)
        await ctx.send(embed=embed)

    @commands.hybrid_command(name="status", description="Gives you a link to the status page.")
    async def status(self, ctx):
        embed = discord.Embed(
            title="Status Page",
            description=(
                "> **Live Status:** [Click here](https://botstatus.csrperlc.com)\n"
                "> **Discord Updates:** [Join our support server](https://discord.gg/B8959ZPPpp)"
            ),
            color=BLANK_COLOR,
        )
        embed.set_author(name="CSRP Utilities", icon_url=CSRP_ICON)
        embed.set_thumbnail(url=CSRP_ICON)
        brand_footer(embed)
        await ctx.send(embed=embed)

    @commands.hybrid_command(name="support", description="Gives you a link to the support server.")
    async def support(self, ctx):
        embed = discord.Embed(
            title="Support Server",
            description="Need help? [Click here](https://discord.gg/B8959ZPPpp) to join the support server.",
            color=BLANK_COLOR,
        )
        embed.set_author(name="CSRP Utilities", icon_url=CSRP_ICON)
        brand_footer(embed)
        view = discord.ui.View()
        view.add_item(discord.ui.Button(label="Join Support Server", url="https://discord.gg/B8959ZPPpp"))
        await ctx.send(embed=embed, view=view)

    @commands.hybrid_command(name="discord_rules", description="Shows the server's Discord rules.")
    async def discord_rules(self, ctx):
        embed = discord.Embed(
            title="Server Rules",
            description=(
                "> `1` **Drama** — Do not cause any drama in our chats.\n"
                "> `2` **Pinging** — Refrain from pinging Staff and High Ranks.\n"
                "> `3` **Nickname** — Your Discord username must be your Roblox username.\n"
                "> `4` **Advertising** — No advertising anywhere in our server.\n"
                "> `5` **Profanity** — Mild profanity is permitted, keep it to a minimum.\n"
                "> `6` **Language** — This is an English-speaking server.\n"
                "> `7` **Respect** — Be respectful to everybody.\n"
                "> `8` **Alt Accounts** — No alternative accounts.\n"
                "> `9` **NSFW** — Do not post NSFW content.\n"
                "> `10` **Toxicity** — Do not be toxic."
            ),
            color=BLANK_COLOR,
        )
        embed.set_author(name="California State Roleplay", icon_url=CSRP_ICON)
        embed.set_thumbnail(url=CSRP_ICON)
        brand_footer(embed)

        view = discord.ui.View()
        view.add_item(discord.ui.Button(style=discord.ButtonStyle.link, label="PRC Guidelines", url="https://discord.com/channels/505904189613015050/736688656139419689/965742742724575263"))
        view.add_item(discord.ui.Button(style=discord.ButtonStyle.link, label="Discord TOS", url="https://discord.com/terms"))
        view.add_item(discord.ui.Button(style=discord.ButtonStyle.link, label="Discord Guidelines", url="https://discord.com/guidelines"))
        await ctx.send(embed=embed, view=view)

    @commands.hybrid_command(name="say", description="Repeats the given message.")
    @is_support()
    @app_commands.describe(message="The message to repeat.")
    async def say(self, ctx, *, message: str):
        channel = ctx.channel
        allowed_mentions = None
        if not member_has_rank_or_higher(ctx.author, "Internal Affairs"):
            allowed_mentions = discord.AllowedMentions(users=True, roles=False, everyone=False)
        if ctx.interaction:
            await ctx.interaction.response.send_message("Done!", ephemeral=True)
            await channel.send(message, allowed_mentions=allowed_mentions)
        else:
            permissions = channel.permissions_for(ctx.guild.me)
            if permissions.manage_messages:
                try:
                    await ctx.message.delete()
                except (discord.NotFound, discord.Forbidden):
                    pass
            await channel.send(message, allowed_mentions=allowed_mentions)

    @app_commands.command(name="convert", description="Convert a video to mp4.")
    @app_commands.describe(file="The file to convert")
    async def convert(self, interaction: discord.Interaction, file: discord.Attachment):
        file_path = f"./{file.filename}"
        await file.save(file_path)

        if not file.filename.lower().endswith(('.mp4', '.mov', '.avi', '.mkv')):
            await interaction.response.send_message(embed=error_embed("Invalid File", "Please upload a valid video file (.mp4, .mov, .avi, .mkv)."))
            os.remove(file_path)
            return

        await interaction.response.send_message(embed=loading_embed("Converting Video", "Converting the video, please wait..."))

        try:
            video_clip = VideoFileClip(file_path)
            output_path = f"./converted_{file.filename.rsplit('.', 1)[0]}.mp4"
            video_clip.write_videofile(output_path, codec="libx264")
            video_clip.close()
            await interaction.edit_original_response(embed=success_embed("Conversion Complete", "Video conversion complete!"))
            await interaction.followup.send(file=discord.File(output_path))
        except Exception as e:
            await interaction.edit_original_response(embed=error_embed("Conversion Failed", f"An error occurred: `{e}`"))
        finally:
            if os.path.exists(file_path):
                os.remove(file_path)
            if 'output_path' in locals() and os.path.exists(output_path):
                os.remove(output_path)

    @app_commands.command(name="rxxqueue", description="Move this channel to the RXX queue category.")
    @app_commands.guild_only()
    async def rxxqueue(self, interaction: discord.Interaction):
        if not any(role.id in RXX_QUEUE_ALLOWED_ROLE_IDS for role in interaction.user.roles):
            await interaction.response.send_message(
                embed=error_embed("Missing Permissions", "You do not have permission to use this command."),
                ephemeral=True,
            )
            return

        channel = interaction.channel
        if not isinstance(channel, discord.TextChannel) or channel.category_id not in RXX_QUEUE_SOURCE_CATEGORY_IDS:
            await interaction.response.send_message(
                embed=error_embed("Invalid Channel", "This command can only be used in channels within the allowed categories."),
                ephemeral=True,
            )
            return

        target_category = interaction.guild.get_channel(RXX_QUEUE_CATEGORY_ID)
        if not isinstance(target_category, discord.CategoryChannel):
            await interaction.response.send_message(
                embed=error_embed("Category Not Found", "I couldn't find the RXX queue category."),
                ephemeral=True,
            )
            return

        try:
            await channel.edit(category=target_category)
        except discord.Forbidden:
            await interaction.response.send_message(
                embed=error_embed("Missing Permissions", "I don't have permission to move this channel."),
                ephemeral=True,
            )
            return
        except discord.HTTPException as e:
            await interaction.response.send_message(
                embed=error_embed("Move Failed", f"Failed to move the channel: `{e}`"),
                ephemeral=True,
            )
            return

        await interaction.response.send_message(
            embed=success_embed("Channel Moved", f"{channel.mention} has been moved to the RXX queue.")
        )

    @commands.hybrid_command(name="docker-exec", description="Execute a SQL command against CSRP Tickets database.")
    @is_bot_dev()
    @app_commands.describe(database="Select the target database", command="SQL command to execute")
    async def docker_exec(self, ctx: commands.Context, database: str, *, command: str):
        target_database = database_options.get(database, database)
        sql_command = self._normalize_sql_input(command)

        if not re.fullmatch(r"[A-Za-z0-9_]+", target_database):
            await ctx.send(embed=error_embed("Invalid Database", "Invalid database selection."), ephemeral=True)
            return

        docker_command = [
            "sudo",
            "-n",
            "docker",
            "exec",
            "-i",
            "postgres",
            "psql",
            "-v",
            "ON_ERROR_STOP=1",
            "-U",
            "postgres",
            "-d",
            target_database,
        ]
        debug_details = None
        try:
            result = subprocess.run(
                docker_command,
                input=sql_command,
                capture_output=True,
                text=True,
                timeout=30,
            )
            output = result.stdout if result.stdout else result.stderr
            if result.returncode != 0:
                debug_details = (
                    f"Database: {target_database}\n"
                    f"Docker command: {' '.join(docker_command)}\n\n"
                    f"Original command:\n{command}\n\n"
                    f"Normalized SQL command:\n{sql_command}\n\n"
                    f"Exit code: {result.returncode}\n\n"
                    f"STDOUT:\n{result.stdout or '(empty)'}\n\n"
                    f"STDERR:\n{result.stderr or '(empty)'}"
                )
        except Exception as e:
            output = str(e)
            debug_details = (
                f"Database: {target_database}\n"
                f"Docker command: {' '.join(docker_command)}\n\n"
                f"Original command:\n{command}\n\n"
                f"Normalized SQL command:\n{sql_command}\n\n"
                f"Python traceback:\n{traceback.format_exc()}"
            )

        if debug_details:
            try:
                if len(debug_details) <= 1900:
                    await ctx.author.send(f"```text\n{debug_details}\n```")
                else:
                    debug_file = discord.File(
                        io.BytesIO(debug_details.encode("utf-8")),
                        filename="docker-exec-debug.txt",
                    )
                    await ctx.author.send(
                        "The SQL command failed. Full debug details are attached.",
                        file=debug_file,
                    )
            except discord.HTTPException:
                pass

        if debug_details:
            embed = discord.Embed(title="Command Failed", description=f"```\n{output[:4000]}\n```", color=BLANK_COLOR)
        else:
            embed = discord.Embed(title="Command Executed", description=f"```\n{output[:4000]}\n```", color=BLANK_COLOR)
        embed.set_author(name=ctx.guild.name, icon_url=ctx.guild.icon.url if ctx.guild.icon else "")
        brand_footer(embed)
        await ctx.send(embed=embed)

    @commands.hybrid_command(name="claude", description="Run a Claude prompt from Discord.")
    @is_bot_dev()
    @app_commands.describe(prompt="The prompt to send to Claude")
    async def claude(self, ctx: commands.Context, *, prompt: str):
        await ctx.defer()
        active_session = self._active_claude_sessions.get(ctx.author.id)
        if active_session and not active_session.finished:
            await ctx.send(embed=error_embed("Claude Busy", "You already have a Claude run in progress. Use the existing Stop button first."))
            return

        session_view = ClaudeSessionView(self, ctx, prompt)
        progress_message = await ctx.send(embed=session_view.build_embed(), view=session_view, legacy_embeds=True)
        if ctx.interaction is not None:
            # Followup messages edit via the interaction webhook token, which
            # expires after 15 minutes; re-fetch so edits use the bot token.
            with contextlib.suppress(discord.HTTPException):
                progress_message = await ctx.channel.fetch_message(progress_message.id)
        session_view.message = progress_message
        self._active_claude_sessions[ctx.author.id] = session_view
        self._track_claude_session_task(session_view, session_view.start_run(prompt))

    @commands.hybrid_command(name="sales", description="Get current group sales data.")
    @is_sales_authorized()
    async def sales(self, ctx, username: str = None):
        await ctx.defer()
        try:
            status, data = await api_get(
                'https://api.cookie-api.com/api/group/group-sales?workspace_id=639826',
                headers={'Authorization': COOKIE_API_AUTH},
                retries=3,
            )
            if status == 429:
                await ctx.send(embed=error_embed("Rate Limited", "The sales API is rate limiting us. Please try again in a minute."))
                return
            if not data:
                await ctx.send(embed=error_embed("Fetch Failed", f"Failed to fetch sales data (HTTP {status})."))
                return

            sales_data = data.get('sales')
            if not isinstance(sales_data, list):
                api_error = data.get('error') or data.get('message') or data.get('detail')
                if api_error:
                    await ctx.send(embed=error_embed("Fetch Failed", f"API error (HTTP {status}): `{str(api_error)[:200]}`"))
                else:
                    await ctx.send(embed=error_embed("Unexpected Response", f"Unexpected response format (HTTP {status}): `{str(data)[:200]}`"))
                return
            if not sales_data:
                await ctx.send(embed=info_embed("Recent Transactions", "No recent transactions found."))
                return

            def _tx_created(tx):
                try:
                    return parse_time_str(tx.get('created')).timestamp()
                except Exception:
                    return 0
            sales_data = sorted(sales_data, key=_tx_created, reverse=True)

            if username:
                # Discord display names in the server are Roblox usernames, so
                # a mention (or raw user ID) resolves via the member's nickname.
                mention_match = re.fullmatch(r"<@!?(\d+)>|(\d{15,20})", username.strip())
                if mention_match and ctx.guild:
                    member_id = int(mention_match.group(1) or mention_match.group(2))
                    member = ctx.guild.get_member(member_id)
                    if member is None:
                        try:
                            member = await ctx.guild.fetch_member(member_id)
                        except discord.HTTPException:
                            member = None
                    if member is None:
                        await ctx.send(embed=info_embed("Recent Transactions", "Couldn't find that member in this server."))
                        return
                    username = member.display_name
                resolved = await _resolve_roblox_username(username)
                if not resolved:
                    await ctx.send(embed=info_embed("Recent Transactions", f"No Roblox user found named **{username}**."))
                    return
                target_id, username = resolved
                sales_data = [
                    tx for tx in sales_data
                    if str(tx.get('agent', {}).get('id')) == str(target_id)
                ]
                if not sales_data:
                    await ctx.send(embed=info_embed("Recent Transactions", f"No transactions found for **{username}**."))
                    return
                resolved_names = {tx.get('agent', {}).get('id'): username for tx in sales_data}
            else:
                sales_data = sales_data[:10]
                agent_ids = []
                for tx in sales_data:
                    agent_id = tx.get('agent', {}).get('id')
                    if agent_id and agent_id not in agent_ids:
                        agent_ids.append(agent_id)
                resolved_names = await _resolve_roblox_users(agent_ids)

            entries = []
            for tx in sales_data:
                try:
                    agent = tx.get('agent', {})
                    agent_id = agent.get('id')
                    buyer = resolved_names.get(agent_id)
                    if not buyer or buyer == str(agent_id):
                        buyer = agent.get('name', 'Unknown Buyer')
                    buyer = str(buyer)[:100]
                    item = tx.get('details', {}).get('name', 'Unknown Item')[:100]
                    amount = str(tx.get('currency', {}).get('amount', '???'))[:20]
                    created = parse_time_str(tx.get('created'))
                    timestamp = int(created.timestamp())
                    entries.append(f"> **{buyer}** bought **{item}** for **{amount} Robux**\n> <t:{timestamp}:R>")
                except Exception as inner_e:
                    entries.append(f"> Error parsing transaction: `{str(inner_e)[:80]}`")

            title = f"Recent Transactions — {username}" if username else "Recent Transactions"
            pages = []
            current_page = ""
            for entry in entries:
                if current_page and len(current_page) + len(entry) + 2 > 3800:
                    embed = discord.Embed(title=title, description=current_page.strip(), color=BLANK_COLOR)
                    embed.set_author(name="California State Roleplay", icon_url=CSRP_ICON)
                    brand_footer(embed)
                    pages.append(embed)
                    current_page = ""
                current_page += entry + "\n\n"
            if current_page.strip():
                embed = discord.Embed(title=title, description=current_page.strip(), color=BLANK_COLOR)
                embed.set_author(name="California State Roleplay", icon_url=CSRP_ICON)
                brand_footer(embed)
                pages.append(embed)

            if len(pages) == 1:
                await ctx.send(embed=pages[0])
            else:
                view = PaginatorView(pages, ctx.author)
                msg = await ctx.send(embed=pages[0], view=view)
                view.message = msg
        except Exception as e:
            await ctx.send(embed=error_embed("Request Failed", f"Request failed: `{e}`"))

    @commands.hybrid_command(name="sentry", description="Get a Sentry issue by error ID.")
    @is_bot_staff()
    async def sentry(self, ctx, error_id: str):
        loading_msg = await ctx.reply(embed=loading_embed("Fetching Sentry Issue", "Fetching Sentry issue..."))

        api_headers = {'Authorization': f'Bearer {SENTRY_API_KEY}'}

        async def _fetch_issues(eid):
            url = "https://sentry.io/api/0/projects/csrp-devteam/csrp-utilities/issues/"
            params = f"?query=error_id:{eid}"
            try:
                status, data = await api_get(url + params, headers={**api_headers, "Content-Type": "application/json"})
                return data if status == 200 else None
            except Exception:
                return None

        for attempt in range(1, 5):
            issues = await _fetch_issues(error_id)
            if issues:
                issue = issues[0]
                title = issue.get('title', 'N/A')
                value = issue.get('metadata', {}).get('value', 'N/A')
                handled = issue.get('isUnhandled', 'N/A')
                last_seen = issue.get('lastSeen', 'N/A')

                from datetime import datetime, timezone
                last_seen_dt = datetime.fromisoformat(last_seen.replace('Z', '+00:00')).replace(tzinfo=timezone.utc)
                last_seen_formatted = discord.utils.format_dt(last_seen_dt, style='R')
                issue_id = issue.get('id')
                error_url = f"https://csrp-devteam.sentry.io/issues/{issue_id}/?environment=production&project=4508560008806400" if issue_id else None

                sentry_description = (
                    f"> **Value:** `{value}`\n"
                    f"> **Unhandled:** `{handled}`\n"
                    f"> **Last Seen:** {last_seen_formatted}"
                )
                if error_url:
                    sentry_description += f"\n> **Sentry URL:** [View Issue]({error_url})"
                embed = discord.Embed(title=f"Sentry Issue: {title}", description=sentry_description, color=BLANK_COLOR)
                embed.set_author(name="CSRP Utilities", icon_url=CSRP_ICON)
                brand_footer(embed)
                await loading_msg.edit(embed=embed)
                return

            retry_interval = 2.0 * 1.3 ** (attempt - 1)
            retry_embed = discord.Embed(
                title="Retrying",
                description=f"No results found for `{error_id}`. Retrying in `{retry_interval:.1f}s`...",
                color=BLANK_COLOR,
            )
            brand_footer(retry_embed)
            await loading_msg.edit(embed=retry_embed)
            await asyncio.sleep(retry_interval)

        await loading_msg.edit(embed=error_embed("Not Found", f"No matching errors found for ID `{error_id}` after all attempts."))

    @commands.hybrid_group(name="api", description="API related commands.")
    async def api(self, ctx: commands.Context):
        if ctx.invoked_subcommand is None:
            embed = discord.Embed(
                title="API Commands",
                description="> `/api generate` — Generate a new API key",
                color=BLANK_COLOR,
            )
            embed.set_author(name="CSRP Utilities", icon_url=CSRP_ICON)
            embed.set_thumbnail(url=CSRP_ICON)
            brand_footer(embed)
            await ctx.send(embed=embed)

    @api.command(name="generate", description="Generate an API key for the CSRP Utilities API.")
    @is_bot_staff()
    async def generate(self, ctx: commands.Context):
        from config import API_GENERATE_AUTH

        view = ConfirmView(ctx.author, timeout=30)
        embed = discord.Embed(
            title="Generate New API Key",
            description=(
                "Are you sure you want to generate a new key?\n\n"
                "> **Note:** Old keys will remain valid until manually removed."
            ),
            color=BLANK_COLOR,
        )
        embed.set_author(name="CSRP Utilities", icon_url=CSRP_ICON)
        brand_footer(embed)
        msg = await ctx.send(embed=embed, view=view)
        view.message = msg
        await view.wait()

        if view.value is None:
            await msg.edit(embed=discord.Embed(title="Action Timed Out", description="The action has timed out.", color=BLANK_COLOR), view=None)
        elif view.value:
            try:
                status, data = await api_get(
                    "https://internal-logs-utilities.csrperlc.com/v1/generateAPI",
                    headers={"Authorization": API_GENERATE_AUTH},
                )
                if status == 200 and data:
                    api_embed = discord.Embed(
                        title="API Key Generated",
                        description=embed_description(
                            "Here is your API key. Please keep it safe.",
                            f"> **API Key:** ||`{data['api_key']}`||",
                        ),
                        color=BLANK_COLOR,
                    )
                    api_embed.set_author(name="CSRP Utilities", icon_url=CSRP_ICON)
                    brand_footer(api_embed)
                    try:
                        dm = await ctx.author.create_dm()
                        await dm.send(embed=api_embed)
                        await msg.edit(embed=success_embed("API Key Generated", "API key generated and sent to your DMs."), view=None)
                    except discord.Forbidden:
                        await msg.edit(embed=error_embed("DM Failed", "Failed to send DM. Please check your privacy settings."), view=None)
                else:
                    await msg.edit(embed=error_embed("Generation Failed", "Failed to generate API key. Please try again later."), view=None)
            except Exception:
                await msg.edit(embed=error_embed("Generation Failed", "Failed to generate API key. Please try again later."), view=None)
        else:
            await msg.edit(embed=discord.Embed(title="Action Cancelled", description="The action has been cancelled.", color=BLANK_COLOR), view=None)


    @commands.hybrid_command(name="partnership", description="Create a partnership announcement embed.")
    @app_commands.describe(
        body="The partnership details (text)",
        message_link="A Discord message link to pull content from",
    )
    async def partnership(self, ctx: commands.Context, body: str = None, message_link: str = None):
        if not has_setting_permission(ctx.guild.id, "partnership_allowed_roles", ctx.author):
            await ctx.send(embed=error_embed("Not Permitted", "You do not have permission to use this command."))
            return

        if not body and not message_link:
            await ctx.send(embed=error_embed("Missing Input", "Provide either a `body` or a `message_link`."))
            return

        content = body

        if message_link:
            match = MESSAGE_LINK_RE.search(message_link)
            if not match:
                await ctx.send(embed=error_embed("Invalid Link", "That doesn't look like a valid Discord message link."))
                return

            guild_id, channel_id, message_id = int(match.group(1)), int(match.group(2)), int(match.group(3))
            channel = self.bot.get_channel(channel_id)
            if not channel:
                await ctx.send(embed=error_embed("Channel Not Found", "I can't access the channel from that link."))
                return

            try:
                msg = await channel.fetch_message(message_id)
                content = msg.content or "(No text content in linked message)"
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                await ctx.send(embed=error_embed("Fetch Failed", "Could not fetch the linked message."))
                return

        target_channel = getattr(ctx, "channel", None)
        if target_channel is None:
            await ctx.send(embed=error_embed("Channel Not Found", "Select a channel for the partnership."))
            return

        embed = discord.Embed(
            title="Partnership",
            description=content,
            color=discord.Color.yellow(),
        )
        embed.set_author(name=ctx.guild.name, icon_url=ctx.guild.icon.url if ctx.guild.icon else CSRP_ICON)
        sent_message = await ctx.send(embed=embed)
        await self._send_partnership_log(ctx, target_channel, content, message_link, sent_message)


async def setup(bot):
    await bot.add_cog(Utility(bot))
