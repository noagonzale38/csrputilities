import discord
from discord.ext import commands, tasks
import asyncio
import time

from config import (
    KEY_HEADERS, CHANNEL_ID, SESSION_CHANNEL,
    is_role_authorized, is_session_permitted,
)
from cogs.helpers import (
    Colors, BLANK_COLOR, CSRP_ICON, SESSION_IMAGE, CHECK, CROSS,
    success_embed, error_embed, info_embed, brand_footer, embed_description,
    api_get, generalised_interaction_check_failure,
)
from cogs.settings import get_permission_user_ids

PingEnabled = False
SESSION_INFO_RUNNING = False
ssu_message = None


class LowPlayerView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self._marked_users = set()

    @discord.ui.button(label="Added Bots", style=discord.ButtonStyle.green, custom_id="added_bots_button")
    async def added_bots_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id in self._marked_users:
            self._marked_users.remove(interaction.user.id)
            await interaction.response.send_message(embed=success_embed("Mark Removed", "Removed your mark."), ephemeral=True)
        else:
            self._marked_users.add(interaction.user.id)
            await interaction.response.send_message(embed=success_embed("Mark Added", "Marked that you added bots."), ephemeral=True)

    @discord.ui.button(label="Members Adding Bots", style=discord.ButtonStyle.primary, custom_id="members_button")
    async def members_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self._marked_users:
            await interaction.response.send_message(embed=info_embed("No Members", "No members have marked yet."), ephemeral=True)
            return
        users = "\n".join(f"> <@{uid}>" for uid in self._marked_users)
        embed = discord.Embed(title="Members Adding Bots", description=users, color=BLANK_COLOR)
        embed.set_author(name="CSRP Utilities", icon_url=CSRP_ICON)
        brand_footer(embed)
        await interaction.response.send_message(embed=embed, ephemeral=True)


class SessionControlView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @staticmethod
    def _is_authorized(interaction: discord.Interaction) -> bool:
        if interaction.guild is None:
            return False
        authorized_users = set(get_permission_user_ids(interaction.guild.id, "authorized"))
        return interaction.user.id in authorized_users

    @discord.ui.button(label="SSD (Stop Pings)", style=discord.ButtonStyle.danger, custom_id="ssd_button")
    async def stop_pings(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self._is_authorized(interaction):
            await generalised_interaction_check_failure(interaction)
            return
        global PingEnabled
        PingEnabled = False
        await interaction.response.send_message(embed=success_embed("SSD Activated", "Pings stopped. SSD activated."), ephemeral=True)

    @discord.ui.button(label="SSU (Start Pings)", style=discord.ButtonStyle.green, custom_id="ssu_button")
    async def start_pings(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self._is_authorized(interaction):
            await generalised_interaction_check_failure(interaction)
            return
        await interaction.response.send_message(embed=success_embed("SSU Activated", "SSU activated. Pings will resume in 5 minutes."), ephemeral=True)
        await asyncio.sleep(300)
        global PingEnabled
        PingEnabled = True
        channel = interaction.guild.get_channel(int(CHANNEL_ID))
        if channel:
            await channel.send(embed=success_embed("Pings Resumed", "Pings resumed. SSU is now active!"))


def _build_session_embed(players, staff, queue):
    current_epoch = int(time.time())
    embed = discord.Embed(
        title="Session Information",
        description=embed_description(
            (
                "Join us to experience an immersive, elevated, and unparalleled roleplay environment. "
                "Our server usually runs 24/7 without interruption. This embed updates every 30 seconds."
            ),
            (
                "> **Server Name:** `California State Roleplay`\n"
                "> **Server Owner:** `Rxx9k`\n"
                "> **Server Code:** `calf` **or** [Click Here](https://policeroleplay.community/join/calf)\n"
                "> **Player Count:** "
                f"`{players}`\n"
                "> **Staff Count:** "
                f"`{staff}`\n"
                "> **Queue Count:** "
                f"`{queue}`"
            ),
            (
                "Please take a moment to review our "
                "[game rules](https://discord.com/channels/965829463512330260/969165052508774410).\n\n"
                f"-# Last Updated: <t:{current_epoch}:R>"
            ),
        ),
        color=BLANK_COLOR,
    )
    embed.set_author(name="California State Roleplay", icon_url=CSRP_ICON)
    embed.set_thumbnail(url=CSRP_ICON)
    embed.set_image(url=SESSION_IMAGE)
    brand_footer(embed)
    return embed


def _session_buttons():
    view = discord.ui.View()
    view.add_item(discord.ui.Button(label="Join Server", url="https://policeroleplay.community/join/calf"))
    view.add_item(discord.ui.Button(label="Roblox Group", url="https://www.roblox.com/groups/32958901/California-State-Roleplay-PRC#!/about"))
    return view


async def _get_player_count():
    try:
        status, data = await api_get(f"https://api.erlc.gg/v1/server", headers=KEY_HEADERS)
        if status == 200 and data:
            return data.get("CurrentPlayers", 0)
    except Exception:
        pass
    return 0


async def _get_staff_count():
    try:
        status, data = await api_get(f"https://api.erlc.gg/v1/server/players", headers=KEY_HEADERS)
        if status == 200 and isinstance(data, list):
            return sum(1 for p in data if isinstance(p, dict) and p.get("Permission") in ["Server Administrator", "Server Moderator"])
    except Exception:
        pass
    return 0


async def _get_queue_count():
    try:
        status, data = await api_get(f"https://api.erlc.gg/v1/server/queue", headers=KEY_HEADERS)
        if status == 200 and isinstance(data, list):
            return len(data)
    except Exception:
        pass
    return 0


class Sessions(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_ready(self):
        self.bot.add_view(SessionControlView())
        self.bot.add_view(LowPlayerView())
        if not self.check_players.is_running():
            self.check_players.start()

    @commands.hybrid_command(name="session", description="Manage ORT pings.")
    @is_role_authorized()
    async def session(self, ctx):
        embed = discord.Embed(
            title="Session Control Panel",
            description=(
                "Use the buttons below to control session pings.\n\n"
                "> **SSD** — Stop all ORT pings\n"
                "> **SSU** — Start ORT pings (5 min delay)"
            ),
            color=BLANK_COLOR,
        )
        embed.set_author(name="California State Roleplay", icon_url=CSRP_ICON)
        brand_footer(embed)
        await ctx.send(embed=embed, view=SessionControlView())

    @commands.hybrid_command(name="sessioninfo", with_app_command=True, description="Sends live session info to the session channel.")
    @is_session_permitted()
    async def ssu(self, ctx: commands.Context):
        global SESSION_INFO_RUNNING, ssu_message

        if SESSION_INFO_RUNNING:
            await ctx.send(embed=error_embed("Already Active", "A session information embed is already active."))
            return

        channel = self.bot.get_channel(SESSION_CHANNEL)
        players = await _get_player_count()
        staff = await _get_staff_count()
        queue = await _get_queue_count()

        embed = _build_session_embed(players, staff, queue)

        if ctx.message:
            try:
                await ctx.message.delete()
            except (discord.NotFound, discord.Forbidden):
                pass

        ssu_message = await channel.send(embed=embed, view=_session_buttons())
        self.update_ssu.start()
        SESSION_INFO_RUNNING = True

    @tasks.loop(seconds=30)
    async def update_ssu(self):
        global ssu_message, SESSION_INFO_RUNNING
        if not ssu_message:
            self.update_ssu.stop()
            return

        try:
            member = await self.bot.fetch_user(1316189468977397862)
            channel = self.bot.get_channel(SESSION_CHANNEL)
            if not channel:
                return
            messages = [message async for message in channel.history(limit=100)]
            if not messages:
                return
            message = discord.utils.get(messages, author=member)
            if message is None:
                return
        except discord.NotFound:
            self.update_ssu.stop()
            SESSION_INFO_RUNNING = False
            return

        players = await _get_player_count()
        staff = await _get_staff_count()
        queue = await _get_queue_count()

        embed = _build_session_embed(players, staff, queue)
        await message.edit(embed=embed, view=_session_buttons())

    @tasks.loop(minutes=30)
    async def check_players(self):
        global PingEnabled
        if not PingEnabled:
            return

        try:
            status, data = await api_get(
                "https://api.erlc.gg/v1/server/players",
                headers=KEY_HEADERS,
            )
            if status != 200 or not isinstance(data, list):
                return

            current_players = len(data)
            channel = self.bot.get_channel(int(CHANNEL_ID))
            if not channel:
                return

            role_to_ping = 1316095512742727761

            if current_players < 20:
                embed = discord.Embed(
                    title="Server Count Low",
                    description=(
                        f"**Ownership Recruitment Team** is needed in the game!\n\n"
                        f"> **Current Player Count:** `{current_players}`\n"
                        f"> **Optimal Server Count:** `30 members+`"
                    ),
                    color=BLANK_COLOR,
                )
                embed.set_author(name="California State Roleplay", icon_url=CSRP_ICON)
                embed.set_thumbnail(url=CSRP_ICON)
                brand_footer(embed)
                await channel.send(f"<@&{role_to_ping}>")
                await channel.send(embed=embed, view=LowPlayerView())
            else:
                embed = discord.Embed(
                    title="Server Count Update",
                    description=(
                        f"> **Current Player Count:** `{current_players}`\n"
                        f"> **Optimal Server Count:** `30 members+`"
                    ),
                    color=BLANK_COLOR,
                )
                embed.set_author(name="California State Roleplay", icon_url=CSRP_ICON)
                embed.set_thumbnail(url=CSRP_ICON)
                brand_footer(embed)
                await channel.send(embed=embed)

        except Exception as e:
            print(f"Error fetching player data: {e}")


async def setup(bot):
    await bot.add_cog(Sessions(bot))
