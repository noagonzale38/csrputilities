import discord
from discord.ext import commands
from discord import app_commands

from config import (
    SERVER_KEY, ADMIN_PRIVILEGE_ROLE_IDS, blacklisted_command,
    is_role_authorized,
)
from cogs.helpers import (
    Colors, BLANK_COLOR, CHECK, CROSS, CSRP_ICON,
    success_embed, error_embed, info_embed, brand_footer, embed_description,
    api_get, api_post, PaginatorView,
)

PRC_API = "https://api.erlc.gg/v1"
PRC_HEADERS = {"Content-Type": "application/json", "Server-Key": SERVER_KEY}


class ERLC(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def _send_command(self, command: str):
        return await api_post(f"{PRC_API}/server/command", headers=PRC_HEADERS, json={"command": command})

    @commands.hybrid_group(name="erlc", description="ERLC server management commands.")
    async def erlc_group(self, ctx: commands.Context):
        if ctx.invoked_subcommand is None:
            embed = discord.Embed(
                title="ERLC Commands",
                description=(
                    "> `/erlc command` — Send a custom command\n"
                    "> `/erlc players` — View online players\n"
                    "> `/erlc server` — View server info\n"
                    "> `/erlc hint` — Send an in-game hint\n"
                    "> `/erlc message` — Send an in-game message\n"
                    "> `/erlc modcalls` — View modcall logs\n"
                    "> `/erlc commandlogs` — View command logs\n"
                    "> `/erlc kick` — Kick a player\n"
                    "> `/erlc ban` — Ban a player"
                ),
                color=BLANK_COLOR,
            )
            embed.set_author(name=ctx.guild.name, icon_url=ctx.guild.icon.url if ctx.guild.icon else "")
            embed.set_thumbnail(url=CSRP_ICON)
            brand_footer(embed)
            await ctx.send(embed=embed)

    @erlc_group.command(name="command", description="Send a custom command to the server.")
    @is_role_authorized()
    @app_commands.describe(command="Command to send to the server.")
    async def command(self, ctx: commands.Context, *, command: str):
        await ctx.defer()

        try:
            with open(blacklisted_command, "r") as file:
                bl_users = {line.strip() for line in file}
        except FileNotFoundError:
            bl_users = set()

        if f"{{userid: {ctx.author.id}}}" in bl_users:
            await ctx.send(embed=error_embed("Blacklisted", "You have been blacklisted from using ERLC commands."))
            return

        if not command.startswith(":"):
            command = f":{command}"

        if command.startswith(":admin") or command.startswith(":unadmin"):
            if not any(role.id in ADMIN_PRIVILEGE_ROLE_IDS for role in ctx.author.roles):
                await ctx.send(embed=error_embed("Missing Role", "You do not have the required role for elevated commands."))
                return

        if any(x in command.lower() for x in ["all", "others"]) and any(
                command.startswith(y) for y in [":ban", ":unban", ":unmod", ":unadmin"]):
            await ctx.send(embed=error_embed("Action Blocked", "Mass actions are blocked for raid prevention."))
            return

        try:
            status, _ = await self._send_command(command)

            if status == 200:
                embed = discord.Embed(
                    title="Command Executed",
                    description=(
                        f"> **Command:** `{command}`\n"
                        f"> **Executed By:** {ctx.author.mention}\n"
                        f"> **Status:** Sent successfully"
                    ),
                    color=BLANK_COLOR,
                )
                embed.set_author(name=ctx.guild.name, icon_url=ctx.guild.icon.url if ctx.guild.icon else "")
                brand_footer(embed)
                await ctx.send(embed=embed)
            elif status == 429:
                await ctx.send(embed=error_embed("Rate Limited", "CSRP has exceeded its rate limit. Please try again shortly."))
            elif status == 422:
                await ctx.send(embed=error_embed("Server Offline", "The in-game server is currently shut down."))
            elif status == 500:
                await ctx.send(embed=error_embed("API Error", "The PRC API returned a 500 error. Please try again."))
            else:
                await ctx.send(embed=error_embed("Unexpected Error", f"The PRC API returned an unexpected error. Status: `{status}`"))

        except Exception as e:
            await ctx.send(embed=error_embed("Connection Error", f"Error connecting to the server: `{e}`"))

    @erlc_group.command(name="players", description="Get current players in server.")
    async def erlc_players(self, ctx):
        await ctx.defer()
        try:
            status, players_data = await api_get(f"{PRC_API}/server/players", headers={"Server-Key": SERVER_KEY})
            if status != 200 or not players_data:
                await ctx.send(embed=error_embed("Fetch Failed", "Failed to fetch players. Please try again later."))
                return

            current_players = len(players_data)
            if current_players == 0:
                await ctx.send(embed=info_embed("No Players Online", "No players are currently online."))
                return

            categories = {"Server Administrator": [], "Server Moderator": [], "Normal": []}
            for player in players_data:
                permission = player.get("Permission", "Normal")
                name = player.get("Player", "Unknown")
                team = player.get("Team", "Unknown")
                callsign = player.get("Callsign") or "N/A"
                line = f"> `{name}` — {team} ({callsign})"
                categories.get(permission, categories["Normal"]).append(line)

            description_parts = []
            for perm, players in categories.items():
                if not players:
                    continue
                description_parts.append(f"**{perm} — {len(players)}**\n" + "\n".join(players))
            embed = discord.Embed(
                title=f"Online Players — {current_players}",
                description="\n\n".join(description_parts),
                color=BLANK_COLOR,
                timestamp=discord.utils.utcnow(),
            )
            embed.set_author(name=ctx.guild.name, icon_url=ctx.guild.icon.url if ctx.guild.icon else "")

            brand_footer(embed)
            await ctx.send(embed=embed)
        except Exception as e:
            await ctx.send(embed=error_embed("Fetch Failed", f"Failed to fetch players: `{e}`"))

    @erlc_group.command(name="server", description="Get current server information.")
    async def erlc_server(self, ctx):
        await ctx.defer()
        try:
            status, data = await api_get(f"{PRC_API}/server", headers={"Server-Key": SERVER_KEY})
            if status != 200 or not data:
                await ctx.send(embed=error_embed("Fetch Failed", f"Failed to fetch server info. Status: `{status}`"))
                return

            embed = discord.Embed(
                title="Server Information",
                description=(
                    f"> **Server Name:** `{data.get('Name', 'N/A')}`\n"
                    f"> **Players:** `{data.get('CurrentPlayers', 0)}/{data.get('MaxPlayers', 0)}`\n"
                    f"> **Join Key:** `{data.get('JoinKey', 'N/A')}`\n"
                    f"> **Owner:** `{data.get('OwnerId', 'N/A')}`\n"
                    f"> **Co-Owner:** `{data.get('CoOwnerId', 'N/A')}`"
                ),
                color=BLANK_COLOR,
                timestamp=discord.utils.utcnow(),
            )
            embed.set_author(name=ctx.guild.name, icon_url=ctx.guild.icon.url if ctx.guild.icon else "")
            embed.set_thumbnail(url=CSRP_ICON)
            brand_footer(embed)
            await ctx.send(embed=embed)
        except Exception as e:
            await ctx.send(embed=error_embed("Connection Error", f"Connection error: `{e}`"))

    @erlc_group.command(name="hint", description="Send a hint to the server.")
    @is_role_authorized()
    @app_commands.describe(message="Hint to send to the server.")
    async def hint(self, ctx: commands.Context, *, message: str):
        await ctx.defer()
        try:
            status, _ = await self._send_command(f":h {message}")
            if status == 200:
                await ctx.send(embed=success_embed("Hint Sent", "Hint sent successfully to the server."))
            else:
                await ctx.send(embed=error_embed("Hint Failed", f"An error occurred. Status Code: `{status}`"))
        except Exception as e:
            await ctx.send(embed=error_embed("Connection Error", f"Error connecting to the server: `{e}`"))

    @erlc_group.command(name="message", description="Send an in-game message to the server.")
    @is_role_authorized()
    @app_commands.describe(message="The message to send.")
    async def message(self, ctx: commands.Context, *, message: str):
        await ctx.defer()
        try:
            status, _ = await self._send_command(f":m {message}")
            if status == 200:
                await ctx.send(embed=success_embed("Message Sent", "Message sent successfully to the server."))
            else:
                await ctx.send(embed=error_embed("Message Failed", f"An error occurred. Status Code: `{status}`"))
        except Exception as e:
            await ctx.send(embed=error_embed("Connection Error", f"Error connecting to the server: `{e}`"))

    @erlc_group.command(name="kick", description="Kick a player from the in-game server.")
    @is_role_authorized()
    @app_commands.describe(player="The player's username or ID", reason="Reason for the kick")
    async def kick(self, ctx: commands.Context, player: str, *, reason: str = "No reason provided"):
        await ctx.defer()
        try:
            status, _ = await self._send_command(f":kick {player} {reason}")
            if status == 200:
                embed = discord.Embed(
                    title="Player Kicked",
                    description=(
                        f"> **Player:** `{player}`\n"
                        f"> **Moderator:** {ctx.author.mention}\n"
                        f"> **Reason:** {reason}"
                    ),
                    color=BLANK_COLOR,
                )
                embed.set_author(name=ctx.guild.name, icon_url=ctx.guild.icon.url if ctx.guild.icon else "")
                brand_footer(embed)
                await ctx.send(embed=embed)
            elif status == 422:
                await ctx.send(embed=error_embed("Server Offline", "The in-game server is currently shut down."))
            else:
                await ctx.send(embed=error_embed("Kick Failed", f"An error occurred. Status Code: `{status}`"))
        except Exception as e:
            await ctx.send(embed=error_embed("Connection Error", f"Error connecting to the server: `{e}`"))

    @erlc_group.command(name="ban", description="Ban a player from the in-game server.")
    @is_role_authorized()
    @app_commands.describe(player="The player's username or ID", reason="Reason for the ban")
    async def ban(self, ctx: commands.Context, player: str, *, reason: str = "No reason provided"):
        await ctx.defer()

        if any(x in player.lower() for x in ["all", "others"]):
            await ctx.send(embed=error_embed("Action Blocked", "Mass actions are blocked for raid prevention."))
            return

        try:
            status, _ = await self._send_command(f":ban {player} {reason}")
            if status == 200:
                embed = discord.Embed(
                    title="Player Banned",
                    description=(
                        f"> **Player:** `{player}`\n"
                        f"> **Moderator:** {ctx.author.mention}\n"
                        f"> **Reason:** {reason}"
                    ),
                    color=BLANK_COLOR,
                )
                embed.set_author(name=ctx.guild.name, icon_url=ctx.guild.icon.url if ctx.guild.icon else "")
                brand_footer(embed)
                await ctx.send(embed=embed)
            elif status == 422:
                await ctx.send(embed=error_embed("Server Offline", "The in-game server is currently shut down."))
            else:
                await ctx.send(embed=error_embed("Ban Failed", f"An error occurred. Status Code: `{status}`"))
        except Exception as e:
            await ctx.send(embed=error_embed("Connection Error", f"Error connecting to the server: `{e}`"))

    @erlc_group.command(name="modcalls", description="Retrieve modcall logs.")
    async def modcalls(self, ctx):
        await ctx.defer()
        try:
            status, data = await api_get(f"{PRC_API}/server/modcalls", headers={"Server-Key": SERVER_KEY})
            if status != 200 or not data:
                await ctx.send(embed=error_embed("No Modcalls", "No modcall logs found."))
                return

            per_page = 5
            pages = []
            for i in range(0, len(data), per_page):
                chunk = data[i:i + per_page]
                desc = "\n\n".join(
                    f"> **Caller:** {mc.get('Caller', 'Unknown')}\n"
                    f"> **Moderator:** {mc.get('Moderator', 'Unknown')}\n"
                    f"> **Time:** <t:{mc.get('Timestamp', 0)}:F>"
                    for mc in chunk
                )
                embed = discord.Embed(title="Modcall Logs", description=desc, color=BLANK_COLOR)
                embed.set_author(name=ctx.guild.name, icon_url=ctx.guild.icon.url if ctx.guild.icon else "")
                brand_footer(embed)
                pages.append(embed)

            if len(pages) == 1:
                await ctx.send(embed=pages[0])
            else:
                view = PaginatorView(pages, ctx.author)
                msg = await ctx.send(embed=pages[0], view=view)
                view.message = msg

        except Exception as e:
            await ctx.send(embed=error_embed("Fetch Failed", f"Failed to fetch modcall logs: `{e}`"))

    @erlc_group.command(name="commandlogs", description="Retrieve command logs.")
    async def commandlogs(self, ctx):
        await ctx.defer()
        try:
            status, data = await api_get(f"{PRC_API}/server/commandlogs", headers={"Server-Key": SERVER_KEY})
            if status != 200 or not data:
                await ctx.send(embed=error_embed("No Command Logs", "No command logs found."))
                return

            per_page = 5
            pages = []
            for i in range(0, len(data), per_page):
                chunk = data[i:i + per_page]
                desc = "\n\n".join(
                    f"> **Player:** {log.get('Player', 'Unknown')}\n"
                    f"> **Command:** {log.get('Command', 'Unknown')}\n"
                    f"> **Time:** <t:{log.get('Timestamp', 0)}:F>"
                    for log in chunk
                )
                embed = discord.Embed(title="Command Logs", description=desc, color=BLANK_COLOR)
                embed.set_author(name=ctx.guild.name, icon_url=ctx.guild.icon.url if ctx.guild.icon else "")
                brand_footer(embed)
                pages.append(embed)

            if len(pages) == 1:
                await ctx.send(embed=pages[0])
            else:
                view = PaginatorView(pages, ctx.author)
                msg = await ctx.send(embed=pages[0], view=view)
                view.message = msg

        except Exception as e:
            await ctx.send(embed=error_embed("Fetch Failed", f"Failed to fetch command logs: `{e}`"))


async def setup(bot):
    await bot.add_cog(ERLC(bot))
