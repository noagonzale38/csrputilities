import asyncio
import discord
import aiohttp
import inspect
import re
import types
from collections import defaultdict
from typing import Any, Optional


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


CSRP_ICON = "https://csrptickets-storage.s3.us-east-1.amazonaws.com/018b50d0d885271446f02f157fe8e00a.png"
CSRP_BANNER = "https://media.discordapp.net/attachments/1304614453525876746/1304614808691277824/calf.png"
SESSION_IMAGE = "https://media.discordapp.net/attachments/1160385986501546034/1203141901683916870/image.png?ex=65e27936&is=65d00436&hm=757874665037e2b196c2f0fc6aab587f39709eefdd8891d1054dd44a71fe6c52&format=webp&quality=lossless&"

CHECK = "<:botCheck:1340435415257055426>"
CROSS = "<:botX:1340880074051948626>"
CLOCK = "<:clock:1510136396894044330>"
PENDING = CLOCK
LOADING = "<a:bot_loading:1322039568928608276>"
ONLINE = "<:online_bot:1329634269370257491>"
DEVELOPER = "<:developer:1367323901339893801>"
CSRP_EMOJI = "<:CSRP:1170178385595609158>"

_TIMESTAMP_RE = re.compile(r"(?<!<:clock:1510136396894044330>\s)(<t:\d+(?::[tTdDfFR])?>)")
_MENTION_INVISIBLE_RE = re.compile(r"[\u200b\u200c\u200d\u200e\u200f\u2060\ufeff]")
_ERROR_TITLE_HINTS = (
    "error",
    "failed",
    "failure",
    "invalid",
    "missing",
    "not found",
    "not permitted",
    "not authorized",
    "cannot",
    "denied",
    "blacklisted",
    "blocked",
    "cancelled",
)
_LOADING_TITLE_HINTS = ("loading", "processing", "converting", "fetching", "syncing")
_CLOCK_TITLE_HINTS = ("pending", "timed out", "reminder", "cooldown", "wait")
_SUCCESS_TITLE_HINTS = (
    "success",
    "complete",
    "completed",
    "executed",
    "sent",
    "submitted",
    "generated",
    "cleared",
    "added",
    "removed",
    "updated",
    "accepted",
    "resumed",
    "activated",
    "created",
    "issued",
    "spoken",
    "muted",
    "warned",
    "banned",
    "unbanned",
    "kicked",
    "infracted",
    "skipped",
    "paused",
    "stopped",
)
_EMBED_BYPASS_FILES = ("cogs/embed_creator.py",)
_PATCH_FLAG = "_components_v2_converted"
_INSTALL_FLAG = "_csrp_components_v2_installed"


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


def _decorate_time_text(text: str | None) -> str | None:
    if not text:
        return text
    return _TIMESTAMP_RE.sub(f"{CLOCK} \\1", text)


def _sanitize_components_text(text: str | None) -> str | None:
    if text is None:
        return None
    return normalize_display_mentions(text)


def normalize_display_mentions(text: str | None) -> str | None:
    """Restore mention syntax that was disarmed with invisible characters.

    Pair this with ``allowed_mentions=discord.AllowedMentions.none()`` when sending
    to make mentions render without notifying users, roles, or everyone/here.
    """
    if text is None or not any(token in text for token in ("@", "<#")):
        return text
    return _MENTION_INVISIBLE_RE.sub("", text)


def user_tag(user: Any, fallback_name: str | None = None) -> str:
    user_id = getattr(user, "id", None)
    name = (
        getattr(user, "display_name", None)
        or getattr(user, "global_name", None)
        or getattr(user, "name", None)
        or fallback_name
        or str(user)
    )
    safe_name = str(name).replace("`", "").strip() or "unknown-user"
    if user_id is None:
        return f"`@{safe_name}`"
    return f"`@{safe_name} | {user_id}`"


def _prefix_title(title: str | None, emoji: str) -> str | None:
    if not title:
        return title
    stripped = title.strip()
    if stripped.startswith("<:") or stripped.startswith("<a:"):
        return stripped
    return f"{emoji} {stripped}"


def _decorate_embed_title(title: str | None) -> str | None:
    if not title:
        return title

    lowered = title.lower()
    if any(hint in lowered for hint in _LOADING_TITLE_HINTS):
        return _prefix_title(title, LOADING)
    if any(hint in lowered for hint in _CLOCK_TITLE_HINTS):
        return _prefix_title(title, CLOCK)
    if any(hint in lowered for hint in _ERROR_TITLE_HINTS):
        return _prefix_title(title, CROSS)
    if any(hint in lowered for hint in _SUCCESS_TITLE_HINTS):
        return _prefix_title(title, CHECK)
    return title


def _should_bypass_components_v2() -> bool:
    for frame_info in inspect.stack(context=0)[2:12]:
        filename = frame_info.filename.replace("\\", "/")
        if filename.endswith(_EMBED_BYPASS_FILES):
            return True
    return False


def _normalize_embed_payload(
    embed: Any,
    embeds: Any,
) -> tuple[discord.Embed | None, list[discord.Embed]]:
    normalized_embed = embed if isinstance(embed, discord.Embed) else None

    normalized_embeds: list[discord.Embed] = []
    if isinstance(embeds, (list, tuple)):
        normalized_embeds = [item for item in embeds if isinstance(item, discord.Embed)]

    return normalized_embed, normalized_embeds


def _normalize_message_content(
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
) -> tuple[tuple[Any, ...], dict[str, Any]]:
    normalized_kwargs = dict(kwargs)
    normalized_args = args

    if normalized_args and "content" not in normalized_kwargs:
        normalized_kwargs["content"] = normalized_args[0]
        normalized_args = normalized_args[1:]

    return normalized_args, normalized_kwargs


def _get_embed_color(embed: discord.Embed) -> discord.Color | None:
    color_value = getattr(embed.color, "value", None)
    if color_value is None:
        return None
    return discord.Color(color_value)


def _embed_text_block(embed: discord.Embed) -> str | None:
    lines: list[str] = []

    author_name = getattr(embed.author, "name", None)
    author_url = getattr(embed.author, "url", None)
    if author_name:
        sanitized_author_name = _sanitize_components_text(author_name) or ""
        author_text = f"[{sanitized_author_name}]({author_url})" if author_url else sanitized_author_name
        lines.append(f"-# {author_text}")

    title = _sanitize_components_text(_decorate_embed_title(embed.title))
    if title:
        title_text = f"[{title}]({embed.url})" if embed.url else title
        lines.append(f"## {title_text}")

    if embed.description:
        if lines:
            lines.append("")
        lines.append(_sanitize_components_text(_decorate_time_text(embed.description)) or "")

    if embed.timestamp:
        if embed.description:
            lines.append("")
        lines.append(f"{CLOCK} {discord.utils.format_dt(embed.timestamp)}")

    return "\n".join(lines).strip() or None


def _embed_fields(embed: discord.Embed) -> list[str]:
    blocks: list[str] = []
    for field in embed.fields:
        name = _sanitize_components_text(field.name or "Field") or "Field"
        value = _sanitize_components_text(_decorate_time_text(field.value)) or ""
        if value.strip():
            blocks.append(f"### {name}\n{value}")
        else:
            blocks.append(f"### {name}")
    return blocks


def _embed_to_container(embed: discord.Embed) -> discord.ui.Container:
    container = discord.ui.Container(accent_color=_get_embed_color(embed))
    header_block = _embed_text_block(embed)
    thumbnail_url = embed.thumbnail.url if embed.thumbnail else None

    if header_block and thumbnail_url:
        section = discord.ui.Section(accessory=discord.ui.Thumbnail(thumbnail_url))
        section.add_item(discord.ui.TextDisplay(header_block))
        container.add_item(section)
    elif header_block:
        container.add_item(discord.ui.TextDisplay(header_block))
    elif thumbnail_url:
        section = discord.ui.Section(accessory=discord.ui.Thumbnail(thumbnail_url))
        section.add_item(discord.ui.TextDisplay("## Message"))
        container.add_item(section)

    for block in _embed_fields(embed):
        if container.children:
            container.add_item(discord.ui.Separator(spacing=discord.SeparatorSpacing.small))
        container.add_item(discord.ui.TextDisplay(block))

    if embed.image and embed.image.url:
        if container.children:
            container.add_item(discord.ui.Separator(spacing=discord.SeparatorSpacing.small))
        container.add_item(
            discord.ui.MediaGallery(
                discord.MediaGalleryItem(embed.image.url)
            )
        )

    if not container.children:
        container.add_item(discord.ui.TextDisplay("## Message"))

    return container


def _bind_layout_callbacks(layout: discord.ui.LayoutView, legacy_view: discord.ui.View) -> None:
    async def _interaction_check(self, interaction: discord.Interaction) -> bool:
        return await legacy_view.interaction_check(interaction)

    async def _on_timeout(self) -> None:
        if hasattr(legacy_view, "message"):
            legacy_view.message = getattr(self, "message", getattr(legacy_view, "message", None))
        await legacy_view.on_timeout()

    async def _on_error(self, interaction: discord.Interaction, error: Exception, item: discord.ui.Item[Any]) -> None:
        await legacy_view.on_error(interaction, error, item)

    layout.interaction_check = types.MethodType(_interaction_check, layout)
    layout.on_timeout = types.MethodType(_on_timeout, layout)
    layout.on_error = types.MethodType(_on_error, layout)


def _legacy_view_to_layout(legacy_view: discord.ui.View) -> discord.ui.LayoutView:
    layout = discord.ui.LayoutView(timeout=legacy_view.timeout)
    _append_legacy_view_rows(layout, legacy_view)
    _bind_layout_callbacks(layout, legacy_view)
    return layout


def _append_legacy_view_rows(layout: discord.ui.LayoutView, legacy_view: discord.ui.View) -> None:
    rows: defaultdict[int, list[discord.ui.Item[Any]]] = defaultdict(list)

    for index, child in enumerate(legacy_view.children):
        row_number = getattr(child, "row", None)
        if row_number is None:
            row_number = index // 5
        rows[row_number].append(child)

    for row_number in sorted(rows):
        action_row = discord.ui.ActionRow()
        for child in rows[row_number]:
            action_row.add_item(child)
        layout.add_item(action_row)


def _append_embeds_to_layout(layout: discord.ui.LayoutView, embeds: list[discord.Embed]) -> None:
    for index, current_embed in enumerate(embeds):
        if layout.children:
            layout.add_item(discord.ui.Separator(spacing=discord.SeparatorSpacing.large))
        layout.add_item(_embed_to_container(current_embed))
        if index < len(embeds) - 1:
            layout.add_item(discord.ui.Separator(spacing=discord.SeparatorSpacing.large))


def _build_components_v2_view(
    embed: discord.Embed | None,
    embeds: list[discord.Embed] | None,
    view: discord.ui.View | discord.ui.LayoutView | None,
) -> tuple[discord.ui.LayoutView, discord.ui.View | None]:
    layout = view if isinstance(view, discord.ui.LayoutView) else None
    legacy_view = None if isinstance(view, discord.ui.LayoutView) else view

    all_embeds: list[discord.Embed] = []
    if embed is not None:
        all_embeds.append(embed)
    if embeds:
        all_embeds.extend(embeds)

    if layout is not None:
        _append_embeds_to_layout(layout, all_embeds)
        return layout, legacy_view

    layout = discord.ui.LayoutView(timeout=legacy_view.timeout if legacy_view is not None else None)
    _append_embeds_to_layout(layout, all_embeds)

    if legacy_view is not None and legacy_view.children:
        if layout.children:
            layout.add_item(discord.ui.Separator(spacing=discord.SeparatorSpacing.large))
        _append_legacy_view_rows(layout, legacy_view)
        _bind_layout_callbacks(layout, legacy_view)

    return layout, legacy_view


def _prepare_components_v2_kwargs(kwargs: dict[str, Any], *, editing: bool) -> tuple[dict[str, Any], discord.ui.View | None]:
    prepared = dict(kwargs)
    already_converted = prepared.pop(_PATCH_FLAG, False)
    legacy_bypass = prepared.pop("legacy_embeds", False)

    if already_converted or legacy_bypass or _should_bypass_components_v2():
        return prepared, None

    embed, embeds = _normalize_embed_payload(prepared.get("embed"), prepared.get("embeds"))
    if embed is None:
        prepared.pop("embed", None)
    if "embeds" in prepared:
        prepared["embeds"] = embeds

    content = prepared.get("content")
    if content not in (None, ""):
        return prepared, None

    if embed is None and not embeds:
        return prepared, None

    view = prepared.get("view")
    layout, legacy_view = _build_components_v2_view(embed, embeds, view)
    prepared["view"] = layout
    prepared.setdefault("allowed_mentions", discord.AllowedMentions.none())

    if editing:
        # Clearing embeds via `embeds=[]` is enough; passing both `embed` and
        # `embeds` trips discord.py's mutual-exclusion validation.
        prepared.pop("embed", None)
        prepared["embeds"] = []
    else:
        prepared.pop("embed", None)
        prepared.pop("embeds", None)

    return prepared, legacy_view


def install_components_v2_transport() -> None:
    if getattr(discord, _INSTALL_FLAG, False):
        return

    from discord.abc import Messageable
    from discord.ext import commands

    original_messageable_send = Messageable.send
    original_context_send = commands.Context.send
    original_context_reply = commands.Context.reply
    original_message_edit = discord.Message.edit
    original_interaction_send = discord.InteractionResponse.send_message
    original_interaction_edit = discord.InteractionResponse.edit_message
    original_edit_original_response = discord.Interaction.edit_original_response
    original_webhook_send = discord.Webhook.send
    original_webhook_message_edit = discord.WebhookMessage.edit

    async def patched_messageable_send(self, *args, **kwargs):
        normalized_args, normalized_kwargs = _normalize_message_content(args, kwargs)
        prepared, legacy_view = _prepare_components_v2_kwargs(normalized_kwargs, editing=False)
        message = await original_messageable_send(self, *normalized_args, **prepared)
        if legacy_view is not None and hasattr(legacy_view, "message"):
            legacy_view.message = message
        if "view" in prepared and hasattr(prepared["view"], "message"):
            prepared["view"].message = message
        return message

    async def patched_context_send(self, *args, **kwargs):
        normalized_args, normalized_kwargs = _normalize_message_content(args, kwargs)
        prepared, legacy_view = _prepare_components_v2_kwargs(normalized_kwargs, editing=False)
        message = await original_context_send(self, *normalized_args, **prepared)
        if legacy_view is not None and hasattr(legacy_view, "message"):
            legacy_view.message = message
        if "view" in prepared and hasattr(prepared["view"], "message"):
            prepared["view"].message = message
        return message

    async def patched_context_reply(self, *args, **kwargs):
        normalized_args, normalized_kwargs = _normalize_message_content(args, kwargs)
        prepared, legacy_view = _prepare_components_v2_kwargs(normalized_kwargs, editing=False)
        message = await original_context_reply(self, *normalized_args, **prepared)
        if legacy_view is not None and hasattr(legacy_view, "message"):
            legacy_view.message = message
        if "view" in prepared and hasattr(prepared["view"], "message"):
            prepared["view"].message = message
        return message

    async def patched_message_edit(self, *args, **kwargs):
        prepared, legacy_view = _prepare_components_v2_kwargs(kwargs, editing=True)
        if legacy_view is not None and hasattr(legacy_view, "message"):
            legacy_view.message = self
        if "view" in prepared and hasattr(prepared["view"], "message"):
            prepared["view"].message = self
        return await original_message_edit(self, *args, **prepared)

    async def patched_interaction_send(self, *args, **kwargs):
        normalized_args, normalized_kwargs = _normalize_message_content(args, kwargs)
        prepared, _ = _prepare_components_v2_kwargs(normalized_kwargs, editing=False)
        return await original_interaction_send(self, *normalized_args, **prepared)

    async def patched_interaction_edit(self, *args, **kwargs):
        prepared, legacy_view = _prepare_components_v2_kwargs(kwargs, editing=True)
        interaction_message = getattr(self._parent, "message", None)
        if legacy_view is not None and hasattr(legacy_view, "message"):
            legacy_view.message = interaction_message
        if "view" in prepared and hasattr(prepared["view"], "message"):
            prepared["view"].message = interaction_message
        return await original_interaction_edit(self, *args, **prepared)

    async def patched_edit_original_response(self, *args, **kwargs):
        from discord.utils import MISSING
        kwargs = {k: v for k, v in kwargs.items() if v is not MISSING}
        prepared, _ = _prepare_components_v2_kwargs(kwargs, editing=True)
        return await original_edit_original_response(self, *args, **prepared)

    async def patched_webhook_send(self, *args, **kwargs):
        normalized_args, normalized_kwargs = _normalize_message_content(args, kwargs)
        prepared, _ = _prepare_components_v2_kwargs(normalized_kwargs, editing=False)
        return await original_webhook_send(self, *normalized_args, **prepared)

    async def patched_webhook_message_edit(self, *args, **kwargs):
        prepared, legacy_view = _prepare_components_v2_kwargs(kwargs, editing=True)
        if legacy_view is not None and hasattr(legacy_view, "message"):
            legacy_view.message = self
        if "view" in prepared and hasattr(prepared["view"], "message"):
            prepared["view"].message = self
        return await original_webhook_message_edit(self, *args, **prepared)

    Messageable.send = patched_messageable_send
    commands.Context.send = patched_context_send
    commands.Context.reply = patched_context_reply
    discord.Message.edit = patched_message_edit
    discord.InteractionResponse.send_message = patched_interaction_send
    discord.InteractionResponse.edit_message = patched_interaction_edit
    discord.Interaction.edit_original_response = patched_edit_original_response
    discord.Webhook.send = patched_webhook_send
    discord.WebhookMessage.edit = patched_webhook_message_edit
    setattr(discord, _INSTALL_FLAG, True)


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


async def api_get(url: str, headers: Optional[dict] = None, timeout: int = 10, retries: int = 0):
    async with aiohttp.ClientSession() as session:
        for attempt in range(retries + 1):
            async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=timeout)) as resp:
                if resp.status in (429, 502, 503) and attempt < retries:
                    try:
                        delay = min(float(resp.headers.get("Retry-After")), 15)
                    except (TypeError, ValueError):
                        delay = 2 ** attempt
                    await asyncio.sleep(delay)
                    continue
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
