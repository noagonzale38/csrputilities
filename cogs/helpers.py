import discord
import aiohttp
from typing import Optional


BLANK_COLOR = 0x2B2D31
GREEN_COLOR = discord.Colour.brand_green()
RED_COLOR = 0xED4348
ORANGE_COLOR = discord.Colour.orange()


class Colors:
    BRAND = discord.Color(BLANK_COLOR)
    SUCCESS = GREEN_COLOR
    ERROR = discord.Color(RED_COLOR)
    WARNING = ORANGE_COLOR
    INFO = discord.Color(BLANK_COLOR)


CSRP_ICON = "https://csrptickets-storage.s3.us-east-1.amazonaws.com/csrp.png"
CSRP_BANNER = "https://media.discordapp.net/attachments/1304614453525876746/1304614808691277824/calf.png"
SESSION_IMAGE = "https://media.discordapp.net/attachments/1160385986501546034/1203141901683916870/image.png?ex=65e27936&is=65d00436&hm=757874665037e2b196c2f0fc6aab587f39709eefdd8891d1054dd44a71fe6c52&format=webp&quality=lossless&"

CHECK = "<:botCheck:1340435415257055426>"
CROSS = "<:botX:1340880074051948626>"
PENDING = "<:Pending:1340119277327614024>"
LOADING = "<a:bot_loading:1322039568928608276>"
ONLINE = "<:online_bot:1329634269370257491>"
DEVELOPER = "<:developer:1367323901339893801>"
CSRP_EMOJI = "<:CSRP:1170178385595609158>"


def brand_footer(embed: discord.Embed) -> discord.Embed:
    embed.set_footer(text="CSRP Utilities", icon_url=CSRP_ICON)
    return embed


def embed_description(*sections: str) -> str:
    return "\n\n".join(section.strip() for section in sections if section and section.strip())


def success_embed(title: str, description: str) -> discord.Embed:
    embed = discord.Embed(title=title, description=description, color=BLANK_COLOR)
    return brand_footer(embed)


def error_embed(title: str, description: str) -> discord.Embed:
    embed = discord.Embed(title=title, description=description, color=BLANK_COLOR)
    return brand_footer(embed)


def info_embed(title: str, description: str) -> discord.Embed:
    embed = discord.Embed(title=title, description=description, color=BLANK_COLOR)
    return brand_footer(embed)


def warning_embed(title: str, description: str) -> discord.Embed:
    embed = discord.Embed(title=title, description=description, color=BLANK_COLOR)
    return brand_footer(embed)


def loading_embed(title: str = "Processing", description: str = "Please wait...") -> discord.Embed:
    embed = discord.Embed(title=title, description=description, color=BLANK_COLOR)
    return brand_footer(embed)


async def invis_embed(ctx, content: str, **kwargs):
    """ERM-style success response: checkmark + bold username + message."""
    return await ctx.send(
        content=f"{CHECK}  **{ctx.author.name}**, {content}",
        **kwargs,
    )


async def failure_embed(ctx, content: str, **kwargs):
    """ERM-style failure response: cross + bold username + message."""
    return await ctx.send(
        content=f"{CROSS}  **{ctx.author.name}**, {content}",
        **kwargs,
    )


async def pending_embed(ctx, content: str, **kwargs):
    """ERM-style pending response: pending + bold username + message."""
    return await ctx.send(
        content=f"{PENDING}  **{ctx.author.name}**, {content}",
        **kwargs,
    )


async def int_invis_embed(interaction: discord.Interaction, content: str, **kwargs):
    """ERM-style interaction success response."""
    try:
        await interaction.response.send_message(
            content=f"{CHECK}  **{interaction.user.name}**, {content}",
            **kwargs,
        )
    except discord.InteractionResponded:
        await interaction.followup.send(
            content=f"{CHECK}  **{interaction.user.name}**, {content}",
            **kwargs,
        )


async def int_failure_embed(interaction: discord.Interaction, content: str, **kwargs):
    """ERM-style interaction failure response."""
    try:
        await interaction.response.send_message(
            content=f"{CROSS}  **{interaction.user.name}**, {content}",
            **kwargs,
        )
    except discord.InteractionResponded:
        await interaction.followup.send(
            content=f"{CROSS}  **{interaction.user.name}**, {content}",
            **kwargs,
        )


async def int_pending_embed(interaction: discord.Interaction, content: str, **kwargs):
    """ERM-style interaction pending response."""
    try:
        await interaction.response.send_message(
            content=f"{PENDING}  **{interaction.user.name}**, {content}",
            **kwargs,
        )
    except discord.InteractionResponded:
        await interaction.followup.send(
            content=f"{PENDING}  **{interaction.user.name}**, {content}",
            **kwargs,
        )


async def generalised_interaction_check_failure(interaction: discord.Interaction):
    """ERM-style 'Not Permitted' embed for unauthorized button clicks."""
    await interaction.response.send_message(
        embed=discord.Embed(
            title="Not Permitted",
            description="You are not permitted to interact with these buttons.",
            color=BLANK_COLOR,
        ),
        ephemeral=True,
    )


async def api_get(url: str, headers: Optional[dict] = None, timeout: int = 10):
    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=timeout)) as resp:
            data = None
            if resp.content_type == "application/json":
                data = await resp.json()
            return resp.status, data


async def api_post(url: str, headers: Optional[dict] = None, json: Optional[dict] = None, data: Optional[dict] = None, timeout: int = 10):
    async with aiohttp.ClientSession() as session:
        async with session.post(url, headers=headers, json=json, data=data, timeout=aiohttp.ClientTimeout(total=timeout)) as resp:
            resp_data = None
            if resp.content_type == "application/json":
                resp_data = await resp.json()
            return resp.status, resp_data


class ConfirmView(discord.ui.View):
    def __init__(self, author: discord.Member, *, timeout: float = 30):
        super().__init__(timeout=timeout)
        self.author = author
        self.value: Optional[bool] = None
        self.message: Optional[discord.Message] = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author.id:
            await generalised_interaction_check_failure(interaction)
            return False
        return True

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True
        if self.message:
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                pass

    @discord.ui.button(label="Yes", style=discord.ButtonStyle.green)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        self.value = True
        self.stop()

    @discord.ui.button(label="No", style=discord.ButtonStyle.danger)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        self.value = False
        self.stop()


class PaginatorView(discord.ui.View):
    def __init__(self, pages: list[discord.Embed], author: discord.Member, *, timeout: float = 120):
        super().__init__(timeout=timeout)
        self.pages = pages
        self.author = author
        self.current = 0
        self.message: Optional[discord.Message] = None
        self._update_buttons()

    def _update_buttons(self):
        self.prev_btn.disabled = self.current == 0
        self.next_btn.disabled = self.current >= len(self.pages) - 1
        self.page_btn.label = f"{self.current + 1}/{len(self.pages)}"

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author.id:
            await generalised_interaction_check_failure(interaction)
            return False
        return True

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True
        if self.message:
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                pass

    @discord.ui.button(label="❮", style=discord.ButtonStyle.secondary)
    async def prev_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.current = max(0, self.current - 1)
        self._update_buttons()
        await interaction.response.edit_message(embed=self.pages[self.current], view=self)

    @discord.ui.button(label="1/1", style=discord.ButtonStyle.gray, disabled=True)
    async def page_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        pass

    @discord.ui.button(label="❯", style=discord.ButtonStyle.secondary)
    async def next_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.current = min(len(self.pages) - 1, self.current + 1)
        self._update_buttons()
        await interaction.response.edit_message(embed=self.pages[self.current], view=self)
