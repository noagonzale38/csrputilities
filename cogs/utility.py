import discord
from discord.ext import commands
from discord import app_commands
import time
import io
import os
import re
import shlex
import subprocess
import traceback
from dateutil.parser import parse as parse_time_str
from moviepy.editor import VideoFileClip
import aiohttp
import asyncio

from config import (
    LATENCY_API_URL, LOG_SERVER_AUTH, COOKIE_API_AUTH, SERVER_KEY,
    SENTRY_API_KEY, DEV_ROLE_ID_ADMIN,
    is_support, is_bot_dev, is_bot_staff, is_sales_authorized,
)
from cogs.helpers import (
    Colors, BLANK_COLOR, CSRP_ICON, CSRP_BANNER, CHECK, CROSS, ONLINE, LOADING, PENDING,
    success_embed, error_embed, info_embed, loading_embed, brand_footer, embed_description,
    api_get, ConfirmView,
)
from cogs.settings import get_guild_settings, has_setting_permission

MESSAGE_LINK_RE = re.compile(
    r"https?://(?:ptb\.|canary\.)?discord(?:app)?\.com/channels/(\d+)/(\d+)/(\d+)"
)

start_time = time.time()

database_options = {
    "postgres": "ticketsbot",
    "postgres-archive": "archive",
    "postgres-cache": "botcache",
}


class Utility(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.start_time = start_time

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
            "mute": "Moderation",
            "unban": "Moderation",
            "unmute": "Moderation",
            "warn": "Moderation",
            "fail": "Training",
            "pass": "Training",
            "training-result": "Training",
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
        permissions = channel.permissions_for(ctx.guild.me)
        if ctx.message and permissions.manage_messages:
            try:
                await ctx.message.delete()
            except (discord.NotFound, discord.Forbidden):
                pass
        await ctx.send(message)

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

    @commands.hybrid_command(name="sales", description="Get current group sales data.")
    @is_sales_authorized()
    async def sales(self, ctx):
        await ctx.defer()
        try:
            status, data = await api_get(
                'https://api.cookie-api.com/api/group/group-sales?workspace_id=639826',
                headers={'Authorization': COOKIE_API_AUTH},
            )
            if not data:
                await ctx.send(embed=error_embed("Fetch Failed", "Failed to fetch sales data."))
                return

            sales_data = data.get('sales')
            if not isinstance(sales_data, list):
                await ctx.send(embed=error_embed("Unexpected Response", "Unexpected response format."))
                return
            if not sales_data:
                await ctx.send(embed=info_embed("Recent Transactions", "No recent transactions found."))
                return

            description = ""
            for tx in sales_data:
                try:
                    buyer = tx.get('agent', {}).get('name', 'Unknown Buyer')
                    item = tx.get('details', {}).get('name', 'Unknown Item')
                    amount = tx.get('currency', {}).get('amount', '???')
                    created = parse_time_str(tx.get('created'))
                    timestamp = int(created.timestamp())
                    description += f"> **{buyer}** bought **{item}** for **{amount} Robux**\n> <t:{timestamp}:R>\n\n"
                except Exception as inner_e:
                    description += f"> Error parsing transaction: `{inner_e}`\n\n"

            embed = discord.Embed(title="Recent Transactions", description=description, color=BLANK_COLOR)
            embed.set_author(name="California State Roleplay", icon_url=CSRP_ICON)
            brand_footer(embed)
            await ctx.send(embed=embed)
        except Exception as e:
            await ctx.send(embed=error_embed("Request Failed", f"Request failed: `{e}`"))

    @commands.hybrid_command(name="sentry", description="Get a Sentry issue by error ID.")
    @is_bot_staff()
    async def sentry(self, ctx, error_id: str):
        loading_msg = await ctx.reply(embed=loading_embed("Fetching Sentry Issue", "Fetching Sentry issue..."))

        api_headers = {'Authorization': f'Bearer {SENTRY_API_KEY}'}

        async def _fetch_issues(eid):
            url = "https://sentry.io/api/0/projects/csrp-devteam/csrp-utilities/issues/"
            try:
                status, data = await api_get(url, headers={**api_headers, "Content-Type": "application/json"})
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

        embed = discord.Embed(
            title="Partnership",
            description=content,
            color=discord.Color.yellow(),
        )
        embed.set_author(name=ctx.guild.name, icon_url=ctx.guild.icon.url if ctx.guild.icon else CSRP_ICON)
        brand_footer(embed)
        await ctx.send(embed=embed)


async def setup(bot):
    await bot.add_cog(Utility(bot))
