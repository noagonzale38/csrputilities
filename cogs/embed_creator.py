import copy
import json
import re
import uuid
from typing import Optional

import discord
from discord.ext import commands
from discord import app_commands

from cogs.helpers import BLANK_COLOR, CSRP_ICON, brand_footer, error_embed, success_embed
from cogs.settings import has_setting_permission

EMBED_MESSAGES_FILE = "embed_messages.json"
HEX_COLOR_RE = re.compile(r"^#?(?:[0-9a-fA-F]{6})$")
ROLE_ID_RE = re.compile(r"<@&(\d+)>|(\d+)")

BUTTON_STYLES = {
    "primary": discord.ButtonStyle.primary,
    "secondary": discord.ButtonStyle.secondary,
    "success": discord.ButtonStyle.success,
    "danger": discord.ButtonStyle.danger,
}

WIZARD_STEPS = [
    "channel",
    "basics",
    "author",
    "footer",
    "media",
    "fields",
    "content",
    "embed2",
    "components",
    "review",
]


# ---------------------------------------------------------------------------
# Utility helpers
# ---------------------------------------------------------------------------

def _default_embed_config() -> dict:
    return {
        "title": "",
        "description": "",
        "url": "",
        "color": "#2B2D31",
        "author_name": "",
        "author_url": "",
        "author_icon_url": "",
        "footer_text": "",
        "footer_icon_url": "",
        "image_url": "",
        "thumbnail_url": "",
        "timestamp": False,
        "fields": [],
    }


def _default_draft(channel_id: int) -> dict:
    return {
        "definition_id": uuid.uuid4().hex[:10],
        "target_channel_id": channel_id,
        "content": "",
        "embeds": [_default_embed_config(), _default_embed_config()],
        "components": [],
    }


def load_embed_messages() -> dict:
    try:
        with open(EMBED_MESSAGES_FILE, "r") as f:
            data = json.load(f)
            if isinstance(data, dict):
                return data
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    return {}


def save_embed_messages(data: dict):
    with open(EMBED_MESSAGES_FILE, "w") as f:
        json.dump(data, f, indent=4)


def parse_color(value: str) -> int:
    raw = (value or "").strip()
    if not raw:
        return BLANK_COLOR
    named = {
        "red": 0xED4245,
        "green": 0x57F287,
        "blue": 0x5865F2,
        "yellow": 0xFEE75C,
        "orange": 0xFAA61A,
        "purple": 0x9B59B6,
        "white": 0xFFFFFF,
        "black": 0x000000,
        "gray": 0x95A5A6,
    }
    if raw.lower() in named:
        return named[raw.lower()]
    if HEX_COLOR_RE.fullmatch(raw):
        return int(raw.replace("#", ""), 16)
    return BLANK_COLOR


def parse_bool(value: str) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def find_role_ids(raw: str) -> list[int]:
    results = []
    for match in ROLE_ID_RE.finditer(raw or ""):
        role_id = match.group(1) or match.group(2)
        if role_id:
            results.append(int(role_id))
    return results


def build_embed(config: dict) -> Optional[discord.Embed]:
    if not any(
        config.get(key)
        for key in [
            "title",
            "description",
            "url",
            "author_name",
            "footer_text",
            "image_url",
            "thumbnail_url",
        ]
    ) and not config.get("fields"):
        return None

    embed = discord.Embed(
        title=config.get("title") or None,
        description=config.get("description") or None,
        url=config.get("url") or None,
        color=parse_color(config.get("color")),
    )
    if config.get("timestamp"):
        embed.timestamp = discord.utils.utcnow()

    if config.get("author_name"):
        embed.set_author(
            name=config.get("author_name"),
            url=config.get("author_url") or None,
            icon_url=config.get("author_icon_url") or None,
        )
    if config.get("footer_text"):
        embed.set_footer(
            text=config.get("footer_text"),
            icon_url=config.get("footer_icon_url") or None,
        )
    if config.get("image_url"):
        embed.set_image(url=config.get("image_url"))
    if config.get("thumbnail_url"):
        embed.set_thumbnail(url=config.get("thumbnail_url"))

    for field in config.get("fields", [])[:25]:
        name = field.get("name", "").strip()
        value = field.get("value", "").strip()
        if name and value:
            embed.add_field(name=name, value=value, inline=bool(field.get("inline")))
    return embed


def build_ephemeral_embeds(payload: dict) -> list[discord.Embed]:
    embed = None
    if payload.get("embed_title") or payload.get("embed_description") or payload.get("embed_fields"):
        embed = discord.Embed(
            title=payload.get("embed_title") or None,
            description=payload.get("embed_description") or None,
            color=parse_color(payload.get("embed_color")),
        )
        if payload.get("embed_footer"):
            embed.set_footer(text=payload["embed_footer"])
        for field in payload.get("embed_fields", [])[:25]:
            if field.get("name") and field.get("value"):
                embed.add_field(name=field["name"], value=field["value"], inline=bool(field.get("inline")))
    return [embed] if embed else []


def parse_fields_input(raw: str) -> list[dict]:
    fields = []
    for line in (raw or "").splitlines():
        parts = [part.strip() for part in line.split("|")]
        if len(parts) < 2:
            continue
        fields.append(
            {
                "name": parts[0],
                "value": parts[1],
                "inline": parse_bool(parts[2]) if len(parts) > 2 else False,
            }
        )
    return fields[:25]


def parse_toggle_options(raw: str) -> list[dict]:
    options = []
    for line in (raw or "").splitlines():
        parts = [part.strip() for part in line.split("|")]
        if len(parts) < 2:
            continue
        options.append(
            {
                "id": uuid.uuid4().hex[:8],
                "label": parts[0][:100],
                "description": parts[1][:100],
                "content": parts[2][:2000] if len(parts) > 2 else "",
                "embed_title": parts[3][:256] if len(parts) > 3 else "",
                "embed_description": parts[4][:4000] if len(parts) > 4 else "",
                "embed_color": parts[5][:20] if len(parts) > 5 else "#2B2D31",
            }
        )
    return options[:25]


def summarize_component(component: dict, index: int) -> str:
    ctype = component.get("type", "unknown").replace("_", " ").title()
    label = component.get("label") or component.get("placeholder") or "Unnamed"
    return f"> `{index}.` **{ctype}** — {label}"


def _progress_bar(current: int, total: int) -> str:
    filled = round((current + 1) / total * 10)
    return "▰" * filled + "▱" * (10 - filled)


# ---------------------------------------------------------------------------
# Built-message view  (attached to sent messages for persistent interactions)
# ---------------------------------------------------------------------------

class BuiltMessageView(discord.ui.View):
    def __init__(self, definition: dict, *, timeout=None):
        super().__init__(timeout=timeout)
        self.definition = definition
        self._build_items()

    def _build_items(self):
        for component in self.definition.get("components", [])[:25]:
            component_id = component.get("component_id")
            custom_id = f"emb:{self.definition['definition_id']}:{component_id}"
            ctype = component.get("type")

            if ctype == "link_button":
                self.add_item(
                    discord.ui.Button(
                        label=component.get("label", "Link")[:80],
                        url=component.get("url"),
                        emoji=component.get("emoji") or None,
                    )
                )
                continue

            if ctype == "toggle_button":
                button = discord.ui.Button(
                    label=component.get("label", "Open")[:80],
                    style=BUTTON_STYLES.get(component.get("style", "primary"), discord.ButtonStyle.primary),
                    custom_id=custom_id,
                    emoji=component.get("emoji") or None,
                )
                button.callback = self._build_toggle_button_callback(component)
                self.add_item(button)
                continue

            if ctype == "role_button":
                button = discord.ui.Button(
                    label=component.get("label", "Role")[:80],
                    style=BUTTON_STYLES.get(component.get("style", "secondary"), discord.ButtonStyle.secondary),
                    custom_id=custom_id,
                    emoji=component.get("emoji") or None,
                )
                button.callback = self._build_role_button_callback(component)
                self.add_item(button)
                continue

            if ctype == "toggle_select":
                options = [
                    discord.SelectOption(
                        label=option["label"][:100],
                        description=(option.get("description") or None),
                        value=option["id"],
                    )
                    for option in component.get("options", [])[:25]
                ]
                if not options:
                    continue
                select = discord.ui.Select(
                    placeholder=component.get("placeholder", "Choose an option")[:150],
                    options=options,
                    custom_id=custom_id,
                    min_values=1,
                    max_values=1,
                )
                select.callback = self._build_toggle_select_callback(component)
                self.add_item(select)
                continue

            if ctype == "role_select":
                options = []
                for role_data in component.get("roles", [])[:25]:
                    role_name = role_data.get("label") or role_data.get("name") or f"Role {role_data['role_id']}"
                    options.append(
                        discord.SelectOption(
                            label=role_name[:100],
                            description=(role_data.get("description") or None),
                            value=str(role_data["role_id"]),
                        )
                    )
                if not options:
                    continue
                select = discord.ui.Select(
                    placeholder=component.get("placeholder", "Choose roles")[:150],
                    options=options,
                    custom_id=custom_id,
                    min_values=1,
                    max_values=min(len(options), component.get("max_values", len(options))),
                )
                select.callback = self._build_role_select_callback(component)
                self.add_item(select)

    def _build_toggle_button_callback(self, component: dict):
        async def callback(interaction: discord.Interaction):
            embeds = build_ephemeral_embeds(component)
            await interaction.response.send_message(
                content=component.get("content") or None,
                embeds=embeds,
                ephemeral=True,
            )
        return callback

    def _build_toggle_select_callback(self, component: dict):
        option_map = {option["id"]: option for option in component.get("options", [])}

        async def callback(interaction: discord.Interaction):
            chosen = option_map.get(interaction.data["values"][0])
            if not chosen:
                await interaction.response.send_message(embed=error_embed("Missing Option", "That option no longer exists."), ephemeral=True)
                return
            embeds = build_ephemeral_embeds(chosen)
            await interaction.response.send_message(
                content=chosen.get("content") or None,
                embeds=embeds,
                ephemeral=True,
            )
        return callback

    def _build_role_button_callback(self, component: dict):
        async def callback(interaction: discord.Interaction):
            role = interaction.guild.get_role(component.get("role_id")) if interaction.guild else None
            if role is None:
                await interaction.response.send_message(embed=error_embed("Role Not Found", "That role no longer exists."), ephemeral=True)
                return
            result = await apply_role_action(interaction, role, component.get("mode", "toggle"))
            await interaction.response.send_message(embed=result, ephemeral=True)
        return callback

    def _build_role_select_callback(self, component: dict):
        role_ids = {int(role_data["role_id"]) for role_data in component.get("roles", [])}

        async def callback(interaction: discord.Interaction):
            selected_ids = {int(value) for value in interaction.data.get("values", [])}
            responses = []
            for role_id in selected_ids:
                if role_id not in role_ids:
                    continue
                role = interaction.guild.get_role(role_id) if interaction.guild else None
                if role is None:
                    continue
                result = await apply_role_action(interaction, role, component.get("mode", "toggle"), as_text=True)
                if result:
                    responses.append(result)

            if not responses:
                await interaction.response.send_message(embed=error_embed("No Changes", "No roles were updated."), ephemeral=True)
                return

            lines = "\n".join(f"> {text}" for text in responses)
            await interaction.response.send_message(
                embed=success_embed("Roles Updated", lines),
                ephemeral=True,
            )
        return callback


# ---------------------------------------------------------------------------
# Role action helper
# ---------------------------------------------------------------------------

async def apply_role_action(
    interaction: discord.Interaction,
    role: discord.Role,
    mode: str,
    *,
    as_text: bool = False,
):
    member = interaction.user if isinstance(interaction.user, discord.Member) else None
    if member is None:
        return error_embed("Server Only", "This action only works in a server.")

    me = interaction.guild.me if interaction.guild else None
    if me is None or not interaction.guild.me.guild_permissions.manage_roles:
        return "I need `Manage Roles` to do that." if as_text else error_embed("Missing Permissions", "I need `Manage Roles` to do that.")
    if role >= me.top_role:
        return "That role is higher than my top role." if as_text else error_embed("Role Too High", "That role is higher than my top role.")

    has_role = role in member.roles
    mode = (mode or "toggle").lower()

    try:
        if mode == "add":
            if has_role:
                return f"You already have {role.mention}." if as_text else _info_embed("No Change", f"You already have {role.mention}.")
            await member.add_roles(role, reason="Embed builder role component")
            return f"Added {role.mention}." if as_text else success_embed("Role Added", f"You were given {role.mention}.")

        if mode == "remove":
            if not has_role:
                return f"You do not have {role.mention}." if as_text else _info_embed("No Change", f"You do not have {role.mention}.")
            await member.remove_roles(role, reason="Embed builder role component")
            return f"Removed {role.mention}." if as_text else success_embed("Role Removed", f"{role.mention} was removed from you.")

        if has_role:
            await member.remove_roles(role, reason="Embed builder role component")
            return f"Removed {role.mention}." if as_text else success_embed("Role Removed", f"{role.mention} was removed from you.")

        await member.add_roles(role, reason="Embed builder role component")
        return f"Added {role.mention}." if as_text else success_embed("Role Added", f"You were given {role.mention}.")
    except discord.Forbidden:
        return "Discord denied the role update." if as_text else error_embed("Action Failed", "Discord denied the role update.")


def _info_embed(title: str, description: str) -> discord.Embed:
    embed = discord.Embed(title=title, description=description, color=BLANK_COLOR)
    return brand_footer(embed)


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------

async def _handle_interaction_error(interaction: discord.Interaction, error: Exception):
    raw = str(error)
    lower = raw.lower()

    if "emoji" in lower or "partialemoji" in lower:
        message = "Invalid emoji. Use a Unicode emoji (e.g. \U0001f517) or custom emoji format (`<:name:id>`)."
    elif isinstance(error, discord.HTTPException):
        if error.code == 50035:
            message = f"Discord rejected the input: {raw[:200]}"
        else:
            message = f"Discord error: {raw[:200]}"
    elif isinstance(error, (ValueError, TypeError)):
        message = f"Invalid input: {raw[:200]}"
    else:
        message = f"Something went wrong: {raw[:200]}"

    try:
        if interaction.response.is_done():
            await interaction.followup.send(embed=error_embed("Error", message), ephemeral=True)
        else:
            await interaction.response.send_message(embed=error_embed("Error", message), ephemeral=True)
    except discord.HTTPException:
        pass


def _validate_emoji(raw: str) -> tuple[str, Optional[str]]:
    """Return (cleaned_value, error_message_or_None)."""
    stripped = (raw or "").strip()
    if not stripped:
        return "", None
    try:
        discord.PartialEmoji.from_str(stripped)
        return stripped, None
    except Exception:
        return "", f"`{stripped[:20]}` is not a valid emoji. Use a Unicode emoji or `<:name:id>` format."


class _BaseModal(discord.ui.Modal):
    async def on_error(self, interaction: discord.Interaction, error: Exception) -> None:
        await _handle_interaction_error(interaction, error)


# ---------------------------------------------------------------------------
# Modals
# ---------------------------------------------------------------------------

class MessageContentModal(discord.ui.Modal, title="Edit Message Content"):
    content = discord.ui.TextInput(
        label="Message content outside the embed",
        style=discord.TextStyle.paragraph,
        required=False,
        max_length=2000,
    )

    def __init__(self, parent_view):
        super().__init__()
        self.parent_view = parent_view
        self.content.default = parent_view.draft.get("content", "")

    async def on_submit(self, interaction: discord.Interaction):
        self.parent_view.draft["content"] = self.content.value
        await self.parent_view.refresh(interaction)


class EmbedBasicsModal(discord.ui.Modal, title="Edit Embed Basics"):
    title_input = discord.ui.TextInput(label="Title", required=False, max_length=256)
    description_input = discord.ui.TextInput(label="Body", style=discord.TextStyle.paragraph, required=False, max_length=4000)
    url_input = discord.ui.TextInput(label="Title URL", required=False, max_length=400)
    color_input = discord.ui.TextInput(label="Color (#5865F2 or red)", required=False, max_length=20)
    timestamp_input = discord.ui.TextInput(label="Timestamp? yes/no", required=False, max_length=5)

    def __init__(self, editor_view):
        super().__init__()
        self.editor_view = editor_view
        config = editor_view.config
        self.title_input.default = config.get("title", "")
        self.description_input.default = config.get("description", "")
        self.url_input.default = config.get("url", "")
        self.color_input.default = config.get("color", "#2B2D31")
        self.timestamp_input.default = "yes" if config.get("timestamp") else "no"

    async def on_submit(self, interaction: discord.Interaction):
        config = self.editor_view.config
        config["title"] = self.title_input.value
        config["description"] = self.description_input.value
        config["url"] = self.url_input.value
        config["color"] = self.color_input.value or "#2B2D31"
        config["timestamp"] = parse_bool(self.timestamp_input.value)
        await self.editor_view.refresh(interaction)


class EmbedAuthorModal(discord.ui.Modal, title="Edit Author"):
    name_input = discord.ui.TextInput(label="Author name", required=False, max_length=256)
    url_input = discord.ui.TextInput(label="Author URL", required=False, max_length=400)
    icon_input = discord.ui.TextInput(label="Author icon URL", required=False, max_length=400)

    def __init__(self, editor_view):
        super().__init__()
        self.editor_view = editor_view
        config = editor_view.config
        self.name_input.default = config.get("author_name", "")
        self.url_input.default = config.get("author_url", "")
        self.icon_input.default = config.get("author_icon_url", "")

    async def on_submit(self, interaction: discord.Interaction):
        config = self.editor_view.config
        config["author_name"] = self.name_input.value
        config["author_url"] = self.url_input.value
        config["author_icon_url"] = self.icon_input.value
        await self.editor_view.refresh(interaction)


class EmbedFooterModal(discord.ui.Modal, title="Edit Footer"):
    text_input = discord.ui.TextInput(label="Footer text", required=False, max_length=2048)
    icon_input = discord.ui.TextInput(label="Footer icon URL", required=False, max_length=400)

    def __init__(self, editor_view):
        super().__init__()
        self.editor_view = editor_view
        config = editor_view.config
        self.text_input.default = config.get("footer_text", "")
        self.icon_input.default = config.get("footer_icon_url", "")

    async def on_submit(self, interaction: discord.Interaction):
        config = self.editor_view.config
        config["footer_text"] = self.text_input.value
        config["footer_icon_url"] = self.icon_input.value
        await self.editor_view.refresh(interaction)


class EmbedMediaModal(discord.ui.Modal, title="Edit Embed Media"):
    thumbnail_input = discord.ui.TextInput(label="Thumbnail URL", required=False, max_length=400)
    image_input = discord.ui.TextInput(label="Image URL", required=False, max_length=400)

    def __init__(self, editor_view):
        super().__init__()
        self.editor_view = editor_view
        config = editor_view.config
        self.thumbnail_input.default = config.get("thumbnail_url", "")
        self.image_input.default = config.get("image_url", "")

    async def on_submit(self, interaction: discord.Interaction):
        config = self.editor_view.config
        config["thumbnail_url"] = self.thumbnail_input.value
        config["image_url"] = self.image_input.value
        await self.editor_view.refresh(interaction)


class EmbedFieldsModal(discord.ui.Modal, title="Edit Embed Fields"):
    fields_input = discord.ui.TextInput(
        label="Fields: Name | Value | inline",
        style=discord.TextStyle.paragraph,
        required=False,
        max_length=4000,
        placeholder="Rules | Follow the server rules | yes",
    )

    def __init__(self, editor_view):
        super().__init__()
        self.editor_view = editor_view
        current = []
        for field in editor_view.config.get("fields", []):
            current.append(f"{field.get('name', '')} | {field.get('value', '')} | {'yes' if field.get('inline') else 'no'}")
        self.fields_input.default = "\n".join(current)

    async def on_submit(self, interaction: discord.Interaction):
        self.editor_view.config["fields"] = parse_fields_input(self.fields_input.value)
        await self.editor_view.refresh(interaction)


class LinkButtonModal(discord.ui.Modal, title="Add Link Button"):
    label_input = discord.ui.TextInput(label="Label", max_length=80)
    url_input = discord.ui.TextInput(label="URL", max_length=400)
    emoji_input = discord.ui.TextInput(label="Emoji (optional)", required=False, max_length=20)

    def __init__(self, component_view):
        super().__init__()
        self.component_view = component_view

    async def on_submit(self, interaction: discord.Interaction):
        self.component_view.parent_view.draft["components"].append(
            {
                "component_id": uuid.uuid4().hex[:8],
                "type": "link_button",
                "label": self.label_input.value,
                "url": self.url_input.value,
                "emoji": self.emoji_input.value,
            }
        )
        await self.component_view.refresh(interaction)


class ToggleButtonModal(discord.ui.Modal, title="Add Toggle Button"):
    label_input = discord.ui.TextInput(label="Label", max_length=80)
    style_input = discord.ui.TextInput(label="Style: primary/secondary/success/danger", max_length=20)
    content_input = discord.ui.TextInput(label="Ephemeral message", style=discord.TextStyle.paragraph, required=False, max_length=2000)
    embed_title_input = discord.ui.TextInput(label="Ephemeral embed title", required=False, max_length=256)
    embed_desc_input = discord.ui.TextInput(label="Ephemeral embed body", style=discord.TextStyle.paragraph, required=False, max_length=4000)

    def __init__(self, component_view):
        super().__init__()
        self.component_view = component_view
        self.style_input.default = "primary"

    async def on_submit(self, interaction: discord.Interaction):
        self.component_view.parent_view.draft["components"].append(
            {
                "component_id": uuid.uuid4().hex[:8],
                "type": "toggle_button",
                "label": self.label_input.value,
                "style": self.style_input.value.lower(),
                "content": self.content_input.value,
                "embed_title": self.embed_title_input.value,
                "embed_description": self.embed_desc_input.value,
                "embed_color": "#2B2D31",
                "emoji": "",
            }
        )
        await self.component_view.refresh(interaction)


class RoleButtonModal(discord.ui.Modal, title="Add Role Button"):
    label_input = discord.ui.TextInput(label="Label", max_length=80)
    role_input = discord.ui.TextInput(label="Role mention or ID", max_length=50)
    mode_input = discord.ui.TextInput(label="Mode: toggle/add/remove", max_length=20)
    style_input = discord.ui.TextInput(label="Style: primary/secondary/success/danger", max_length=20)

    def __init__(self, component_view):
        super().__init__()
        self.component_view = component_view
        self.mode_input.default = "toggle"
        self.style_input.default = "secondary"

    async def on_submit(self, interaction: discord.Interaction):
        role_ids = find_role_ids(self.role_input.value)
        if not role_ids:
            await interaction.response.send_message(embed=error_embed("Invalid Role", "Provide a valid role mention or ID."), ephemeral=True)
            return
        self.component_view.parent_view.draft["components"].append(
            {
                "component_id": uuid.uuid4().hex[:8],
                "type": "role_button",
                "label": self.label_input.value,
                "role_id": role_ids[0],
                "mode": self.mode_input.value.lower(),
                "style": self.style_input.value.lower(),
                "emoji": "",
            }
        )
        await self.component_view.refresh(interaction)


class ToggleSelectModal(discord.ui.Modal, title="Add Toggle Menu"):
    placeholder_input = discord.ui.TextInput(label="Placeholder", max_length=150)
    options_input = discord.ui.TextInput(
        label="Each line: Label | Description | Message | Embed Title | Embed Body | Color",
        style=discord.TextStyle.paragraph,
        max_length=4000,
        placeholder="Rules | Show the rules | Server rules here | Rules | Follow the rules | #5865F2",
    )

    def __init__(self, component_view):
        super().__init__()
        self.component_view = component_view

    async def on_submit(self, interaction: discord.Interaction):
        options = parse_toggle_options(self.options_input.value)
        if not options:
            await interaction.response.send_message(embed=error_embed("Invalid Options", "Add at least one valid option line."), ephemeral=True)
            return
        self.component_view.parent_view.draft["components"].append(
            {
                "component_id": uuid.uuid4().hex[:8],
                "type": "toggle_select",
                "placeholder": self.placeholder_input.value,
                "options": options,
            }
        )
        await self.component_view.refresh(interaction)


class RoleSelectModal(discord.ui.Modal, title="Add Role Menu"):
    placeholder_input = discord.ui.TextInput(label="Placeholder", max_length=150)
    mode_input = discord.ui.TextInput(label="Mode: toggle/add/remove", max_length=20)
    roles_input = discord.ui.TextInput(
        label="Role mentions or IDs separated by commas/new lines",
        style=discord.TextStyle.paragraph,
        max_length=2000,
        placeholder="<@&123>, <@&456>",
    )

    def __init__(self, component_view):
        super().__init__()
        self.component_view = component_view
        self.mode_input.default = "toggle"

    async def on_submit(self, interaction: discord.Interaction):
        role_ids = list(dict.fromkeys(find_role_ids(self.roles_input.value)))
        if not role_ids:
            await interaction.response.send_message(embed=error_embed("Invalid Roles", "Provide at least one valid role mention or ID."), ephemeral=True)
            return
        roles = []
        for role_id in role_ids[:25]:
            role = interaction.guild.get_role(role_id)
            if role:
                roles.append({"role_id": role.id, "label": role.name})
        if not roles:
            await interaction.response.send_message(embed=error_embed("Roles Missing", "None of those roles exist in this server."), ephemeral=True)
            return
        self.component_view.parent_view.draft["components"].append(
            {
                "component_id": uuid.uuid4().hex[:8],
                "type": "role_select",
                "placeholder": self.placeholder_input.value,
                "mode": self.mode_input.value.lower(),
                "roles": roles,
                "max_values": len(roles),
            }
        )
        await self.component_view.refresh(interaction)


# ---------------------------------------------------------------------------
# Remove-component sub-view  (used by the components wizard step)
# ---------------------------------------------------------------------------

class RemoveComponentSelect(discord.ui.Select):
    def __init__(self, component_view):
        self.component_view = component_view
        options = [
            discord.SelectOption(
                label=(component.get("label") or component.get("placeholder") or f"Component {index + 1}")[:100],
                value=str(index),
                description=component.get("type", "component").replace("_", " ")[:100],
            )
            for index, component in enumerate(component_view.parent_view.draft.get("components", []))
        ][:25]
        super().__init__(
            placeholder="Select a component to remove",
            options=options or [discord.SelectOption(label="No components", value="-1")],
            min_values=1,
            max_values=1,
        )
        self.disabled = not options

    async def callback(self, interaction: discord.Interaction):
        index = int(self.values[0])
        if index >= 0:
            self.component_view.parent_view.draft["components"].pop(index)
        await self.component_view.refresh(interaction)


class RemoveComponentView(discord.ui.View):
    def __init__(self, component_view):
        super().__init__(timeout=300)
        self.component_view = component_view
        self.parent_view = component_view.parent_view
        self.add_item(RemoveComponentSelect(component_view))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return await self.parent_view.interaction_check(interaction)

    @discord.ui.button(label="Back", style=discord.ButtonStyle.secondary, row=1)
    async def back_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.component_view.refresh(interaction)


# ---------------------------------------------------------------------------
# Embed-2 sub-editor  (standalone editor opened from the wizard's embed2 step)
# ---------------------------------------------------------------------------

class EmbedEditorView(discord.ui.View):
    def __init__(self, parent_view, embed_index: int):
        super().__init__(timeout=1800)
        self.parent_view = parent_view
        self.embed_index = embed_index
        self.config = self.parent_view.draft["embeds"][embed_index]

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return await self.parent_view.interaction_check(interaction)

    def build_embed(self) -> discord.Embed:
        current = build_embed(self.config)
        if current is not None:
            return current
        embed = discord.Embed(
            title=f"Embed {self.embed_index + 1}",
            description="This embed is currently empty. Use the buttons below to configure it.",
            color=BLANK_COLOR,
        )
        brand_footer(embed)
        return embed

    async def refresh(self, interaction: discord.Interaction):
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    @discord.ui.button(label="Basics", style=discord.ButtonStyle.primary)
    async def basics_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(EmbedBasicsModal(self))

    @discord.ui.button(label="Author", style=discord.ButtonStyle.secondary)
    async def author_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(EmbedAuthorModal(self))

    @discord.ui.button(label="Footer", style=discord.ButtonStyle.secondary)
    async def footer_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(EmbedFooterModal(self))

    @discord.ui.button(label="Media", style=discord.ButtonStyle.secondary, row=1)
    async def media_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(EmbedMediaModal(self))

    @discord.ui.button(label="Fields", style=discord.ButtonStyle.secondary, row=1)
    async def fields_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(EmbedFieldsModal(self))

    @discord.ui.button(label="Clear", style=discord.ButtonStyle.danger, row=1)
    async def clear_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.parent_view.draft["embeds"][self.embed_index] = _default_embed_config()
        self.config = self.parent_view.draft["embeds"][self.embed_index]
        await self.refresh(interaction)

    @discord.ui.button(label="← Back to Wizard", style=discord.ButtonStyle.success, row=2)
    async def back_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.parent_view.refresh(interaction)


# ---------------------------------------------------------------------------
# Component-modal adapter
# ---------------------------------------------------------------------------

class _ComponentContext:
    """Thin adapter so component modals work with the wizard view."""

    def __init__(self, wizard: "EmbedWizardView"):
        self.parent_view = wizard

    async def refresh(self, interaction: discord.Interaction):
        await self.parent_view.refresh(interaction)


# ---------------------------------------------------------------------------
# Step-by-step wizard view
# ---------------------------------------------------------------------------

class EmbedWizardView(discord.ui.View):

    def __init__(self, cog, author: discord.Member, guild: discord.Guild, draft: dict, *, start_step: int = 0):
        super().__init__(timeout=1800)
        self.cog = cog
        self.author = author
        self.guild = guild
        self.draft = draft
        self.message: Optional[discord.Message] = None
        self.current_step = start_step
        self._build_step()

    # -- properties ----------------------------------------------------------

    @property
    def step_name(self) -> str:
        return WIZARD_STEPS[self.current_step]

    @property
    def config(self) -> dict:
        return self.draft["embeds"][0]

    # -- guards / lifecycle --------------------------------------------------

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author.id:
            await interaction.response.send_message("You cannot use this wizard.", ephemeral=True)
            return False
        return True

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True
        if self.message:
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                pass

    # -- refresh -------------------------------------------------------------

    async def refresh(self, interaction: discord.Interaction):
        self._build_step()
        await interaction.response.edit_message(embed=self._build_step_embed(), view=self)

    # -- section-filled check ------------------------------------------------

    def _is_filled(self, step: str) -> bool:
        cfg = self.config
        return {
            "basics": bool(cfg.get("title") or cfg.get("description")),
            "author": bool(cfg.get("author_name")),
            "footer": bool(cfg.get("footer_text")),
            "media": bool(cfg.get("image_url") or cfg.get("thumbnail_url")),
            "fields": bool(cfg.get("fields")),
            "content": bool(self.draft.get("content")),
            "embed2": build_embed(self.draft["embeds"][1]) is not None,
            "components": bool(self.draft.get("components")),
        }.get(step, False)

    def _has_sendable_content(self) -> bool:
        return bool(
            self.draft.get("content")
            or any(build_embed(config) is not None for config in self.draft["embeds"])
        )

    # -- step embed builder --------------------------------------------------

    def _build_step_embed(self) -> discord.Embed:
        step = self.step_name
        total = len(WIZARD_STEPS)
        num = self.current_step + 1
        footer_text = f"{_progress_bar(self.current_step, total)}  •  Step {num}/{total}"

        if step == "channel":
            ch = self.guild.get_channel(self.draft["target_channel_id"])
            selected = f"\n\n> **Currently selected:** {ch.mention}" if ch else ""
            embed = discord.Embed(
                title=f"Step {num} of {total} — Select Channel",
                description=(
                    "Choose the text channel where your embed message will be sent.\n"
                    "This is the channel members will see the final message in.\n\n"
                    "Use the dropdown below to pick a channel."
                    f"{selected}"
                ),
                color=BLANK_COLOR,
            )

        elif step == "basics":
            cfg = self.config
            embed = discord.Embed(
                title=f"Step {num} of {total} — Embed Basics",
                description=(
                    "Configure the core content of your embed.\n\n"
                    "**Title** — The bold heading at the top of the embed.\n"
                    "**Description** — The main body text. Supports Discord markdown.\n"
                    "**URL** — Makes the title a clickable hyperlink.\n"
                    "**Color** — The accent bar on the left side. Use hex (`#5865F2`) or a name (`red`, `blue`).\n"
                    "**Timestamp** — Adds current date/time in the embed footer.\n"
                    "\n**━━━ Current Values ━━━**\n"
                    f"> **Title:** {cfg.get('title') or '`Not set`'}\n"
                    f"> **Description:** `{len(cfg.get('description', ''))} chars`\n"
                    f"> **URL:** {cfg.get('url') or '`Not set`'}\n"
                    f"> **Color:** `{cfg.get('color', '#2B2D31')}`\n"
                    f"> **Timestamp:** {'Yes' if cfg.get('timestamp') else 'No'}"
                ),
                color=parse_color(cfg.get("color")),
            )

        elif step == "author":
            cfg = self.config
            embed = discord.Embed(
                title=f"Step {num} of {total} — Author",
                description=(
                    "Add an author line above the embed title.\n\n"
                    "**Name** — Small text displayed above the title.\n"
                    "**URL** — Makes the author name clickable.\n"
                    "**Icon** — A small circular image next to the name. Use a direct image URL.\n"
                    "\n**━━━ Current Values ━━━**\n"
                    f"> **Name:** {cfg.get('author_name') or '`Not set`'}\n"
                    f"> **URL:** {cfg.get('author_url') or '`Not set`'}\n"
                    f"> **Icon:** {'`Set`' if cfg.get('author_icon_url') else '`Not set`'}"
                ),
                color=BLANK_COLOR,
            )

        elif step == "footer":
            cfg = self.config
            embed = discord.Embed(
                title=f"Step {num} of {total} — Footer",
                description=(
                    "Add a footer at the bottom of your embed.\n\n"
                    "**Text** — Small text at the very bottom. Leave it empty for no footer.\n"
                    "**Icon** — A small image next to the footer text. Use a direct image URL.\n"
                    "\n**━━━ Current Values ━━━**\n"
                    f"> **Text:** {cfg.get('footer_text') or '`Not set`'}\n"
                    f"> **Icon:** {'`Set`' if cfg.get('footer_icon_url') else '`Not set`'}"
                ),
                color=BLANK_COLOR,
            )

        elif step == "media":
            cfg = self.config
            embed = discord.Embed(
                title=f"Step {num} of {total} — Media",
                description=(
                    "Add images to your embed.\n\n"
                    "**Thumbnail** — A small image in the top-right corner.\n"
                    "**Image** — A large image at the bottom, spanning the full width.\n\n"
                    "Both must be direct image URLs (`.png`, `.jpg`, `.gif`).\n"
                    "\n**━━━ Current Values ━━━**\n"
                    f"> **Thumbnail:** {'`Set`' if cfg.get('thumbnail_url') else '`Not set`'}\n"
                    f"> **Image:** {'`Set`' if cfg.get('image_url') else '`Not set`'}"
                ),
                color=BLANK_COLOR,
            )

        elif step == "fields":
            cfg = self.config
            field_count = len(cfg.get("fields", []))
            lines = [
                "Add structured data fields to your embed.\n",
                "Fields appear below the description. Each has a **name** (heading) and "
                "**value** (content). They can be **inline** (side by side) or **block** (full width).\n",
                "**Format:** `Name | Value | inline`",
                "**Example:** `Rules | Follow the server rules | yes`",
                "One field per line, max 25 fields.",
                f"\n**━━━ Current Fields ({field_count}) ━━━**",
            ]
            if cfg.get("fields"):
                for i, f in enumerate(cfg["fields"][:8]):
                    inline_tag = " `inline`" if f.get("inline") else ""
                    lines.append(f"> `{i + 1}.` **{f.get('name', '?')}** — {f.get('value', '?')[:50]}{inline_tag}")
                if field_count > 8:
                    lines.append(f"> *...and {field_count - 8} more*")
            else:
                lines.append("> None configured yet")
            embed = discord.Embed(
                title=f"Step {num} of {total} — Fields",
                description="\n".join(lines),
                color=BLANK_COLOR,
            )

        elif step == "content":
            content_val = self.draft.get("content", "")
            content_len = len(content_val)
            lines = [
                "Add text content outside the embed.\n",
                "This appears as a regular message above your embed(s). "
                "Supports Discord markdown, mentions, and emoji. Max 2,000 characters.",
                f"\n**━━━ Current Value ━━━**",
                f"> **Length:** `{content_len}` characters",
            ]
            if content_val:
                preview = content_val[:200] + ("..." if content_len > 200 else "")
                lines.append(f"> {preview}")
            embed = discord.Embed(
                title=f"Step {num} of {total} — Message Content",
                description="\n".join(lines),
                color=BLANK_COLOR,
            )

        elif step == "embed2":
            has_embed2 = build_embed(self.draft["embeds"][1]) is not None
            cfg2 = self.draft["embeds"][1]
            lines = [
                "Optionally add a second embed to your message.\n",
                "The second embed appears directly below the first one. "
                "Use it for additional information or sections that don't fit in one embed.",
                f"\n**━━━ Status ━━━**",
                f"> **Embed 2:** {'`Configured`' if has_embed2 else '`Empty`'}",
            ]
            if has_embed2:
                lines.append(f"> **Title:** {cfg2.get('title') or '`Untitled`'}")
                lines.append(f"> **Description:** `{len(cfg2.get('description', ''))} chars`")
            embed = discord.Embed(
                title=f"Step {num} of {total} — Second Embed",
                description="\n".join(lines),
                color=BLANK_COLOR,
            )

        elif step == "components":
            components = self.draft.get("components", [])
            lines = [
                "Add interactive buttons and menus below your embed.\n",
                "**Link Button** — Opens a URL in the browser.",
                "**Toggle Button** — Shows a hidden message when clicked (only visible to the clicker).",
                "**Role Button** — Adds or removes a role when clicked.",
                "**Toggle Menu** — Dropdown with options, each showing a different hidden message.",
                "**Role Menu** — Dropdown for selecting roles to add or remove.",
                f"\n**━━━ Current Components ({len(components)}) ━━━**",
            ]
            if components:
                for idx, comp in enumerate(components[:8]):
                    lines.append(summarize_component(comp, idx + 1))
                if len(components) > 8:
                    lines.append(f"> *...and {len(components) - 8} more*")
            else:
                lines.append("> None configured yet")
            embed = discord.Embed(
                title=f"Step {num} of {total} — Components",
                description="\n".join(lines),
                color=BLANK_COLOR,
            )

        else:  # review
            ch = self.guild.get_channel(self.draft["target_channel_id"])
            ch_text = ch.mention if ch else f"`{self.draft['target_channel_id']}`"
            sections = [
                "Here's a summary of your embed message. Use **Preview** to see "
                "exactly how it will look, or **Send** to post it.\n",
                f"**Channel:** {ch_text}",
            ]
            if self.draft.get("content"):
                sections.append(f"**Message Content:** `{len(self.draft['content'])}` characters")

            cfg1 = self.draft["embeds"][0]
            if build_embed(cfg1):
                parts = [f"**Embed 1:** {cfg1.get('title') or 'Untitled'}"]
                if cfg1.get("description"):
                    parts.append(f"> Description: `{len(cfg1['description'])} chars`")
                if cfg1.get("author_name"):
                    parts.append(f"> Author: {cfg1['author_name'][:30]}")
                if cfg1.get("fields"):
                    parts.append(f"> Fields: `{len(cfg1['fields'])}`")
                sections.append("\n".join(parts))
            else:
                sections.append("**Embed 1:** Empty")

            cfg2 = self.draft["embeds"][1]
            if build_embed(cfg2):
                sections.append(f"**Embed 2:** {cfg2.get('title') or 'Untitled'}")

            components = self.draft.get("components", [])
            if components:
                comp_lines = [f"**Components:** `{len(components)}`"]
                for idx, comp in enumerate(components[:5]):
                    comp_lines.append(summarize_component(comp, idx + 1))
                if len(components) > 5:
                    comp_lines.append(f"> *...and {len(components) - 5} more*")
                sections.append("\n".join(comp_lines))

            if not self._has_sendable_content():
                sections.append("\n⚠️ **Nothing to send.** Go back and add content or configure an embed.")

            embed = discord.Embed(
                title=f"Step {num} of {total} — Review & Send",
                description="\n".join(sections),
                color=BLANK_COLOR,
            )

        embed.set_footer(text=footer_text)
        embed.set_author(
            name=self.guild.name,
            icon_url=self.guild.icon.url if self.guild.icon else CSRP_ICON,
        )
        return embed

    # -- step builder --------------------------------------------------------

    def _build_step(self):
        self.clear_items()
        step = self.step_name

        if step == "channel":
            self._add_channel_items()
        elif step == "basics":
            self._add_edit_button("Edit Basics", "basics", EmbedBasicsModal)
        elif step == "author":
            self._add_edit_button("Edit Author", "author", EmbedAuthorModal)
        elif step == "footer":
            self._add_edit_button("Edit Footer", "footer", EmbedFooterModal)
        elif step == "media":
            self._add_edit_button("Edit Media", "media", EmbedMediaModal)
        elif step == "fields":
            self._add_edit_button("Edit Fields", "fields", EmbedFieldsModal)
        elif step == "content":
            self._add_content_items()
        elif step == "embed2":
            self._add_embed2_items()
        elif step == "components":
            self._add_component_items()
        elif step == "review":
            self._add_review_items()

        self._add_navigation()

    # -- per-step item builders ----------------------------------------------

    def _add_channel_items(self):
        channel_select = discord.ui.ChannelSelect(
            channel_types=[discord.ChannelType.text, discord.ChannelType.news],
            placeholder="Select a channel…",
            row=0,
        )
        wizard = self

        async def on_channel(interaction: discord.Interaction):
            wizard.draft["target_channel_id"] = channel_select.values[0].id
            wizard.current_step = 1
            await wizard.refresh(interaction)

        channel_select.callback = on_channel
        self.add_item(channel_select)

    def _add_edit_button(self, label: str, section: str, modal_cls):
        filled = self._is_filled(section)
        emoji = "✅" if filled else "✏️"
        btn = discord.ui.Button(label=label, style=discord.ButtonStyle.primary, emoji=emoji, row=0)
        wizard = self

        async def on_click(interaction: discord.Interaction):
            await interaction.response.send_modal(modal_cls(wizard))

        btn.callback = on_click
        self.add_item(btn)

    def _add_content_items(self):
        filled = self._is_filled("content")
        emoji = "✅" if filled else "✏️"
        btn = discord.ui.Button(label="Edit Content", style=discord.ButtonStyle.primary, emoji=emoji, row=0)
        wizard = self

        async def on_click(interaction: discord.Interaction):
            await interaction.response.send_modal(MessageContentModal(wizard))

        btn.callback = on_click
        self.add_item(btn)

    def _add_embed2_items(self):
        has_embed2 = self._is_filled("embed2")
        label = "Edit Embed 2" if has_embed2 else "Configure Embed 2"
        emoji = "✅" if has_embed2 else "\U0001f4dd"
        btn = discord.ui.Button(label=label, style=discord.ButtonStyle.primary, emoji=emoji, row=0)
        wizard = self

        async def on_click(interaction: discord.Interaction):
            editor = EmbedEditorView(wizard, 1)
            await interaction.response.edit_message(embed=editor.build_embed(), view=editor)

        btn.callback = on_click
        self.add_item(btn)

        if has_embed2:
            clear_btn = discord.ui.Button(label="Clear Embed 2", style=discord.ButtonStyle.danger, row=0)

            async def on_clear(interaction: discord.Interaction):
                wizard.draft["embeds"][1] = _default_embed_config()
                await wizard.refresh(interaction)

            clear_btn.callback = on_clear
            self.add_item(clear_btn)

    def _add_component_items(self):
        adapter = _ComponentContext(self)

        link_btn = discord.ui.Button(label="Link Button", style=discord.ButtonStyle.primary, row=0)
        link_btn.callback = lambda i: i.response.send_modal(LinkButtonModal(adapter))
        self.add_item(link_btn)

        toggle_btn = discord.ui.Button(label="Toggle Button", style=discord.ButtonStyle.secondary, row=0)
        toggle_btn.callback = lambda i: i.response.send_modal(ToggleButtonModal(adapter))
        self.add_item(toggle_btn)

        role_btn = discord.ui.Button(label="Role Button", style=discord.ButtonStyle.secondary, row=0)
        role_btn.callback = lambda i: i.response.send_modal(RoleButtonModal(adapter))
        self.add_item(role_btn)

        toggle_menu = discord.ui.Button(label="Toggle Menu", style=discord.ButtonStyle.secondary, row=1)
        toggle_menu.callback = lambda i: i.response.send_modal(ToggleSelectModal(adapter))
        self.add_item(toggle_menu)

        role_menu = discord.ui.Button(label="Role Menu", style=discord.ButtonStyle.secondary, row=1)
        role_menu.callback = lambda i: i.response.send_modal(RoleSelectModal(adapter))
        self.add_item(role_menu)

        if self.draft.get("components"):
            remove_btn = discord.ui.Button(label="Remove", style=discord.ButtonStyle.danger, row=1)
            wizard = self

            async def on_remove(interaction: discord.Interaction):
                rm_adapter = _ComponentContext(wizard)
                await interaction.response.edit_message(
                    embed=wizard._build_step_embed(),
                    view=RemoveComponentView(rm_adapter),
                )

            remove_btn.callback = on_remove
            self.add_item(remove_btn)

    def _add_review_items(self):
        wizard = self
        can_send_or_preview = wizard._has_sendable_content()

        preview_btn = discord.ui.Button(label="Preview", style=discord.ButtonStyle.primary, row=0)
        preview_btn.disabled = not can_send_or_preview

        async def on_preview(interaction: discord.Interaction):
            if not wizard._has_sendable_content():
                await interaction.response.send_message(
                    embed=error_embed("Nothing To Preview", "Add message content or at least one embed first."),
                    ephemeral=True,
                )
                return
            embeds = [e for e in (build_embed(c) for c in wizard.draft["embeds"]) if e][:2]
            pv = BuiltMessageView(copy.deepcopy(wizard.draft), timeout=300) if wizard.draft.get("components") else None
            await interaction.response.send_message(
                content=wizard.draft.get("content") or None,
                embeds=embeds or None,
                view=pv,
                ephemeral=True,
            )

        preview_btn.callback = on_preview
        self.add_item(preview_btn)

    # -- navigation ----------------------------------------------------------

    def _add_navigation(self):
        step = self.step_name
        wizard = self
        nav_row = 4

        if self.current_step > 0:
            back = discord.ui.Button(label="← Back", style=discord.ButtonStyle.secondary, row=nav_row)

            async def go_back(interaction: discord.Interaction):
                wizard.current_step = max(0, wizard.current_step - 1)
                await wizard.refresh(interaction)

            back.callback = go_back
            self.add_item(back)

        skippable = {"basics", "author", "footer", "media", "fields", "content", "embed2"}
        if step in skippable:
            skip = discord.ui.Button(label="Skip", style=discord.ButtonStyle.secondary, row=nav_row)

            async def go_skip(interaction: discord.Interaction):
                wizard.current_step = min(len(WIZARD_STEPS) - 1, wizard.current_step + 1)
                await wizard.refresh(interaction)

            skip.callback = go_skip
            self.add_item(skip)

        if step == "review":
            send = discord.ui.Button(label="Send", style=discord.ButtonStyle.success, row=nav_row)
            send.disabled = not wizard._has_sendable_content()
            send.callback = self._do_send
            self.add_item(send)

            cancel = discord.ui.Button(label="Cancel", style=discord.ButtonStyle.danger, row=nav_row)

            async def do_cancel(interaction: discord.Interaction):
                for item in wizard.children:
                    item.disabled = True
                await interaction.response.edit_message(
                    embed=error_embed("Wizard Closed", "The embed creation wizard has been closed."),
                    view=wizard,
                )

            cancel.callback = do_cancel
            self.add_item(cancel)

        elif step == "channel":
            nxt = discord.ui.Button(label="Next →", style=discord.ButtonStyle.success, row=nav_row)
            ch = self.guild.get_channel(self.draft.get("target_channel_id", 0))
            if not ch:
                nxt.disabled = True

            async def go_next_ch(interaction: discord.Interaction):
                wizard.current_step = 1
                await wizard.refresh(interaction)

            nxt.callback = go_next_ch
            self.add_item(nxt)

        elif step != "review":
            label = "Review →" if step == "components" else "Next →"
            nxt = discord.ui.Button(label=label, style=discord.ButtonStyle.success, row=nav_row)

            async def go_next(interaction: discord.Interaction):
                wizard.current_step = min(len(WIZARD_STEPS) - 1, wizard.current_step + 1)
                await wizard.refresh(interaction)

            nxt.callback = go_next
            self.add_item(nxt)

    # -- send ----------------------------------------------------------------

    async def _do_send(self, interaction: discord.Interaction):
        if not self._has_sendable_content():
            await interaction.response.send_message(
                embed=error_embed("Nothing To Send", "Add message content or at least one embed first."),
                ephemeral=True,
            )
            return

        embeds = [e for e in (build_embed(c) for c in self.draft["embeds"]) if e][:2]

        channel = self.guild.get_channel(self.draft["target_channel_id"])
        if channel is None:
            await interaction.response.send_message(
                embed=error_embed("Channel Missing", "The target channel is no longer available."),
                ephemeral=True,
            )
            return

        outgoing_view = BuiltMessageView(copy.deepcopy(self.draft), timeout=None) if self.draft.get("components") else None
        try:
            sent_message = await channel.send(
                content=self.draft.get("content") or None,
                embeds=embeds or None,
                view=outgoing_view,
            )
        except discord.Forbidden:
            await interaction.response.send_message(
                embed=error_embed("Send Failed", "I cannot send messages in that channel."),
                ephemeral=True,
            )
            return

        if self.draft.get("components"):
            stored = load_embed_messages()
            stored[str(sent_message.id)] = {
                "message_id": sent_message.id,
                "guild_id": self.guild.id,
                "channel_id": channel.id,
                "definition": copy.deepcopy(self.draft),
            }
            save_embed_messages(stored)
            self.cog.register_persistent_definition(copy.deepcopy(self.draft))

        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(
            embed=success_embed("Embed Sent", f"Your embed message has been sent to {channel.mention}."),
            view=self,
        )


# ---------------------------------------------------------------------------
# Cog
# ---------------------------------------------------------------------------

class EmbedCreator(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self._registered_definition_ids = set()

    def register_persistent_definition(self, definition: dict):
        definition_id = definition.get("definition_id")
        if not definition_id or definition_id in self._registered_definition_ids:
            return
        self.bot.add_view(BuiltMessageView(definition, timeout=None))
        self._registered_definition_ids.add(definition_id)

    @commands.Cog.listener()
    async def on_ready(self):
        stored = load_embed_messages()
        for payload in stored.values():
            definition = payload.get("definition")
            if definition:
                self.register_persistent_definition(definition)

    @commands.hybrid_group(name="embed", description="Embed creation tools.")
    async def embed_group(self, ctx: commands.Context):
        if ctx.invoked_subcommand is None:
            await ctx.send(embed=success_embed("Embed Tools", "Use `/embed create` to open the embed creation wizard."))

    @embed_group.command(name="create", description="Open the embed creation wizard.")
    @commands.guild_only()
    @app_commands.describe(channel="Where the final embed message should be sent")
    async def create(self, ctx: commands.Context, channel: Optional[discord.TextChannel] = None):
        if not has_setting_permission(ctx.guild.id, "embed_allowed_roles", ctx.author):
            await ctx.send(embed=error_embed("Not Permitted", "You do not have permission to use this command."))
            return

        target_channel = channel or ctx.channel
        draft = _default_draft(target_channel.id)
        start_step = 1 if channel else 0
        view = EmbedWizardView(self, ctx.author, ctx.guild, draft, start_step=start_step)
        message = await ctx.send(embed=view._build_step_embed(), view=view)
        view.message = message


async def setup(bot):
    await bot.add_cog(EmbedCreator(bot))
