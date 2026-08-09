import asyncio
import json
import logging

import discord
from discord.ext import commands
from discord import app_commands

from config import (
    HEADERS, KEY_HEADERS, ADMIN_PRIVILEGE_ROLE_IDS, blacklisted_command,
    is_role_authorized,
)
from cogs.helpers import (
    Colors, BLANK_COLOR, CHECK, CROSS, CSRP_ICON,
    success_embed, error_embed, info_embed, brand_footer, embed_description,
    api_get, api_post, PaginatorView, user_tag,
)

log = logging.getLogger(__name__)

PRC_API = "https://api.erlc.gg/v2"
PRC_HEADERS = HEADERS
PRC_SERVER_OFFLINE_STATUSES = {288, 422, 3002}

WANTED_STARS = "★"


def _prc_status_message(status: int, *, action: str = "complete this action") -> tuple[str, str]:
    if status == 429:
        return "Rate Limited", "CSRP has exceeded its rate limit. Please try again shortly."
    if status in PRC_SERVER_OFFLINE_STATUSES:
        return "Server Offline", "The ERLC server is shut down or unavailable right now."
    if status == 500:
        return "API Error", "The PRC API returned a 500 error. Please try again."
    return "Unexpected Error", f"The PRC API returned an unexpected error. Status: `{status}`"


async def _roblox_api_post(url: str, payload: dict):
    """POST JSON to a Roblox API endpoint via curl, returning parsed JSON or None."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "curl", "-s", "--max-time", "10",
            "-H", "Content-Type: application/json",
            "-d", json.dumps(payload), url,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=12)
        if proc.returncode == 0 and stdout:
            return json.loads(stdout)
        log.warning(f"[ERLC] curl POST failed for {url}: rc={proc.returncode} stderr={stderr.decode()[:200]}")
    except asyncio.TimeoutError:
        log.warning(f"[ERLC] curl POST timeout for {url}")
    except Exception as e:
        log.warning(f"[ERLC] Error POSTing to {url}: {type(e).__name__}: {e}")
    return None


async def _resolve_roblox_users(user_ids: list) -> dict:
    """Batch-resolve Roblox user IDs to {id: username} (one API call per 200 IDs)."""
    results = {}
    ids_to_fetch = [uid for uid in user_ids if uid]
    if not ids_to_fetch:
        return results

    log.info(f"[ERLC] Resolving {len(ids_to_fetch)} Roblox user(s): {ids_to_fetch}")

    numeric_to_original = {}
    for uid in ids_to_fetch:
        results[uid] = str(uid)
        try:
            numeric_to_original[int(uid)] = uid
        except (TypeError, ValueError):
            pass

    numeric_ids = list(numeric_to_original)
    for start in range(0, len(numeric_ids), 200):
        chunk = numeric_ids[start:start + 200]
        data = await _roblox_api_post(
            "https://users.roblox.com/v1/users",
            {"userIds": chunk, "excludeBannedUsers": False},
        )
        for entry in (data or {}).get("data", []):
            uid = numeric_to_original.get(entry.get("id"))
            name = entry.get("name")
            if uid is not None and name:
                results[uid] = name

    return results


async def _resolve_roblox_username(username: str):
    """Resolve a Roblox username to (id, canonical_name), or None if not found."""
    data = await _roblox_api_post(
        "https://users.roblox.com/v1/usernames/users",
        {"usernames": [username], "excludeBannedUsers": False},
    )
    for entry in (data or {}).get("data", []):
        if entry.get("id"):
            return entry["id"], entry.get("name", username)
    return None


def _roblox_link(user_id, username: str) -> str:
    return f"[{username}](https://roblox.com/users/{user_id}/profile)"


class ERLC(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def _send_command(self, command: str):
        return await api_post(
            f"{PRC_API}/server/command",
            headers=PRC_HEADERS,
            json={"command": command},
        )

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
                    "> `/erlc cslookup` — Look up a callsign\n"
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
                        f"> **Executed By:** {user_tag(ctx.author)}\n"
                        f"> **Status:** Sent successfully"
                    ),
                    color=BLANK_COLOR,
                )
                embed.set_author(name=ctx.guild.name, icon_url=ctx.guild.icon.url if ctx.guild.icon else "")
                brand_footer(embed)
                await ctx.send(embed=embed)
            else:
                title, message = _prc_status_message(status, action="send this command")
                await ctx.send(embed=error_embed(title, message))

        except Exception as e:
            await ctx.send(embed=error_embed("Connection Error", f"Error connecting to the server: `{e}`"))

    @erlc_group.command(name="players", description="Get current players in server.")
    async def erlc_players(self, ctx):
        await ctx.defer()
        try:
            status, data = await api_get(
                f"{PRC_API}/server?Players=true", headers=KEY_HEADERS
            )
            if status != 200:
                title, message = _prc_status_message(status, action="fetch players")
                await ctx.send(embed=error_embed(title, message))
                return

            players_data = data.get("Players") if data else None
            if not players_data:
                await ctx.send(embed=info_embed("No Players Online", "No players are currently online."))
                return

            current_players = data.get("CurrentPlayers", len(players_data))
            max_players = data.get("MaxPlayers", "?")

            categories = {"Server Administrator": [], "Server Moderator": [], "Normal": []}
            for player in players_data:
                permission = player.get("Permission", "Normal")
                name = player.get("Player", "Unknown")
                team = player.get("Team", "Unknown")
                callsign = player.get("Callsign")
                wanted = int(player.get("WantedStars", 0) or 0)
                location = player.get("Location", {})
                postal = location.get("PostalCode", "")
                street = location.get("StreetName", "")

                parts = [f"`{name}`"]
                parts.append(f"Team: **{team}**")
                if callsign:
                    parts.append(f"CS: `{callsign}`")
                if wanted and wanted > 0:
                    parts.append(f"{WANTED_STARS * wanted} ({wanted})")
                if street and postal:
                    parts.append(f"📍 {street}, {postal}")
                elif postal:
                    parts.append(f"📍 {postal}")

                line = "> " + " · ".join(parts)
                categories.get(permission, categories["Normal"]).append(line)

            all_lines = []
            for perm, players in categories.items():
                if not players:
                    continue
                all_lines.append(f"**{perm} — {len(players)}**")
                all_lines.extend(players)
                all_lines.append("")

            per_page = 15
            pages = []
            for i in range(0, len(all_lines), per_page):
                chunk = "\n".join(all_lines[i:i + per_page]).strip()
                embed = discord.Embed(
                    title=f"Online Players — {current_players}/{max_players}",
                    description=chunk,
                    color=BLANK_COLOR,
                    timestamp=discord.utils.utcnow(),
                )
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
            await ctx.send(embed=error_embed("Fetch Failed", f"Failed to fetch players: `{e}`"))

    @erlc_group.command(name="server", description="Get current server information.")
    async def erlc_server(self, ctx):
        await ctx.defer()
        try:
            status, data = await api_get(f"{PRC_API}/server", headers=KEY_HEADERS)
            if status != 200:
                title, message = _prc_status_message(status, action="fetch server info")
                await ctx.send(embed=error_embed(title, message))
                return
            if not data:
                await ctx.send(embed=error_embed("Fetch Failed", "Failed to fetch server info."))
                return

            owner_id = data.get("OwnerId")
            co_owner_ids = data.get("CoOwnerIds", [])

            all_ids = [owner_id] + list(co_owner_ids)
            resolved = await _resolve_roblox_users(all_ids)

            owner_link = _roblox_link(owner_id, resolved.get(owner_id, str(owner_id))) if owner_id else "None"
            if co_owner_ids:
                co_owner_str = ", ".join(
                    _roblox_link(cid, resolved.get(cid, str(cid))) for cid in co_owner_ids
                )
            else:
                co_owner_str = "None"

            team_balance = "Enabled" if data.get("TeamBalance") else "Disabled"
            verified_req = data.get("AccVerifiedReq", "N/A")

            embed = discord.Embed(
                title="Server Information",
                description=(
                    f"> **Server Name:** `{data.get('Name', 'N/A')}`\n"
                    f"> **Players:** `{data.get('CurrentPlayers', 0)}/{data.get('MaxPlayers', 0)}`\n"
                    f"> **Join Key:** `{data.get('JoinKey', 'N/A')}`\n"
                    f"> **Owner:** {owner_link}\n"
                    f"> **Co-Owners:** {co_owner_str}\n"
                    f"> **Verified Req:** `{verified_req}`\n"
                    f"> **Team Balance:** `{team_balance}`"
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
                title, error_message = _prc_status_message(status, action="send this hint")
                await ctx.send(embed=error_embed(title if status in PRC_SERVER_OFFLINE_STATUSES else "Hint Failed", error_message))
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
                title, error_message = _prc_status_message(status, action="send this message")
                await ctx.send(embed=error_embed(title if status in PRC_SERVER_OFFLINE_STATUSES else "Message Failed", error_message))
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
                        f"> **Moderator:** {user_tag(ctx.author)}\n"
                        f"> **Reason:** {reason}"
                    ),
                    color=BLANK_COLOR,
                )
                embed.set_author(name=ctx.guild.name, icon_url=ctx.guild.icon.url if ctx.guild.icon else "")
                brand_footer(embed)
                await ctx.send(embed=embed)
            else:
                title, error_message = _prc_status_message(status, action="kick this player")
                await ctx.send(embed=error_embed(title if status in PRC_SERVER_OFFLINE_STATUSES else "Kick Failed", error_message))
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
                        f"> **Moderator:** {user_tag(ctx.author)}\n"
                        f"> **Reason:** {reason}"
                    ),
                    color=BLANK_COLOR,
                )
                embed.set_author(name=ctx.guild.name, icon_url=ctx.guild.icon.url if ctx.guild.icon else "")
                brand_footer(embed)
                await ctx.send(embed=embed)
            else:
                title, error_message = _prc_status_message(status, action="ban this player")
                await ctx.send(embed=error_embed(title if status in PRC_SERVER_OFFLINE_STATUSES else "Ban Failed", error_message))
        except Exception as e:
            await ctx.send(embed=error_embed("Connection Error", f"Error connecting to the server: `{e}`"))

    @erlc_group.command(name="cslookup", description="Look up a player's callsign or find a player by callsign.")
    @app_commands.describe(query="A username or callsign to search for.")
    async def cslookup(self, ctx: commands.Context, *, query: str):
        await ctx.defer()
        try:
            status, data = await api_get(
                f"{PRC_API}/server?Players=true",
                headers=KEY_HEADERS,
            )
            if status != 200:
                title, message = _prc_status_message(status, action="fetch server data")
                await ctx.send(embed=error_embed(title, message))
                return
            if not data or "Players" not in data:
                await ctx.send(embed=error_embed("No Data", "Could not retrieve player data from the server."))
                return

            players = data["Players"]
            search = query.strip()
            search_lower = search.lower()
            found = None

            for player in players:
                player_field = player.get("Player", "")
                username = player_field.split(":")[0] if ":" in player_field else player_field
                callsign = player.get("Callsign")

                if username.lower() == search_lower:
                    found = player
                    break
                if callsign and callsign.lower() == search_lower:
                    found = player
                    break

            if not found:
                await ctx.send(embed=error_embed("Not Found", f"No player or callsign matching `{search}` was found in the server."))
                return

            found_username = found.get("Player", "Unknown").split(":")[0]
            found_callsign = found.get("Callsign") or "None"
            found_team = found.get("Team", "Unknown")
            found_wanted = int(found.get("WantedStars", 0) or 0)
            location = found.get("Location", {})
            postal = location.get("PostalCode", "")
            street = location.get("StreetName", "")

            desc_lines = [
                f"> **User:** {found_username}",
                f"> **Team:** {found_team}",
                f"> **Callsign:** {found_callsign}",
            ]
            if found_wanted and found_wanted > 0:
                desc_lines.append(f"> **Wanted:** {WANTED_STARS * found_wanted} ({found_wanted})")
            if street and postal:
                desc_lines.append(f"> **Location:** {street}, {postal}")
            elif postal:
                desc_lines.append(f"> **Location:** {postal}")

            embed = discord.Embed(
                title="Callsign Lookup",
                description="\n".join(desc_lines),
                color=BLANK_COLOR,
            )
            embed.set_author(name=ctx.guild.name, icon_url=ctx.guild.icon.url if ctx.guild.icon else "")
            embed.set_thumbnail(url=CSRP_ICON)
            brand_footer(embed)
            await ctx.send(embed=embed)

        except Exception as e:
            await ctx.send(embed=error_embed("Fetch Failed", f"Failed to look up callsign: `{e}`"))

    @erlc_group.command(name="modcalls", description="Retrieve modcall logs.")
    async def modcalls(self, ctx):
        await ctx.defer()
        try:
            status, resp = await api_get(
                f"{PRC_API}/server?ModCalls=true", headers=KEY_HEADERS
            )
            if status != 200:
                title, message = _prc_status_message(status, action="fetch modcalls")
                await ctx.send(embed=error_embed(title, message))
                return

            data = resp.get("ModCalls") if resp else None
            if not data:
                await ctx.send(embed=info_embed("No Modcalls", "No modcall logs found."))
                return

            data = sorted(data, key=lambda entry: int(entry.get("Timestamp") or 0), reverse=True)

            per_page = 5
            pages = []
            for i in range(0, len(data), per_page):
                chunk = data[i:i + per_page]
                desc = "\n\n".join(
                    f"> **Caller:** {mc.get('Caller', 'Unknown')}\n"
                    f"> **Moderator:** {mc.get('Moderator') or 'None'}\n"
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
            status, resp = await api_get(
                f"{PRC_API}/server?CommandLogs=true", headers=KEY_HEADERS
            )
            if status != 200:
                title, message = _prc_status_message(status, action="fetch command logs")
                await ctx.send(embed=error_embed(title, message))
                return

            data = resp.get("CommandLogs") if resp else None
            if not data:
                await ctx.send(embed=info_embed("No Command Logs", "No command logs found."))
                return

            data = sorted(data, key=lambda entry: int(entry.get("Timestamp") or 0), reverse=True)

            per_page = 5
            pages = []
            for i in range(0, len(data), per_page):
                chunk = data[i:i + per_page]
                desc = "\n\n".join(
                    f"> **Player:** {log.get('Player', 'Unknown')}\n"
                    f"> **Command:** `{log.get('Command', 'Unknown')}`\n"
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
