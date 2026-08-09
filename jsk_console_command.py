import asyncio
import contextlib
import logging
import os
import pty
import re
import shlex
import signal
import time
from os import PathLike

import discord
from discord.ext import commands

from config import BOT_OWNER_ID

active_console_sessions: dict[int, "JskConsoleView"] = {}

TERMINAL_OUTPUT_LIMIT = 3200
TERMINAL_EMBED_LIMIT = 1800
ANSI_ESCAPE_RE = re.compile(r"\x1b(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")


def _strip_terminal_ansi(value: str) -> str:
    return ANSI_ESCAPE_RE.sub("", value)


def _normalize_terminal_output(value: str) -> str:
    value = value.replace("\r\n", "\n").replace("\r", "\n")
    value = value.replace("\x07", "")
    value = _strip_terminal_ansi(value)
    lines = []
    for raw_line in value.split("\n"):
        if "\b" in raw_line:
            clean_line = []
            for char in raw_line:
                if char == "\b":
                    if clean_line:
                        clean_line.pop()
                else:
                    clean_line.append(char)
            raw_line = "".join(clean_line)
        lines.append(raw_line)
    return "\n".join(lines)


def _tail_text(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    return "...\n" + value[-limit:]


# Guardrails for the console, not a sandbox: the shell inherits the bot's
# environment (including tokens), so secret access and host-destroying
# commands are refused up front. The bot owner (BOT_OWNER_ID) can override
# a match after an explicit warning; everyone else is refused outright.
# Determined bypasses are still possible.
BLOCKED_CONSOLE_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    # Secrets / credentials
    (re.compile(r"(^|[\s'\"=/])\.env(\.\w+)?\b"), ".env files are off-limits"),
    (re.compile(r"\bprintenv\b"), "dumping environment variables is blocked"),
    (re.compile(r"^(sudo\s+)?(env|set|export|declare)\s*(\||>|$)"), "dumping environment variables is blocked"),
    (re.compile(r"/proc/[\w/]*environ"), "reading process environments is blocked"),
    (
        re.compile(r"\$\{?\w*(TOKEN|SECRET|PASSWORD|PASSWD|API_?KEY|WEBHOOK)\w*\}?", re.IGNORECASE),
        "expanding secret environment variables is blocked",
    ),
    (re.compile(r"\.ssh(/|\b)"), "the .ssh directory is off-limits"),
    (re.compile(r"\bid_(rsa|ed25519|ecdsa|dsa)\b"), "SSH private keys are off-limits"),
    (re.compile(r"/etc/(shadow|sudoers|gshadow)"), "system credential files are off-limits"),
    # Destructive filesystem operations
    (re.compile(r"--no-preserve-root"), "--no-preserve-root is blocked"),
    (
        re.compile(r"\brm\b[^|;&]*\s(/|/\*|~|~/|\$HOME|\.|\.\.|\*)([\s;|&]|$)"),
        "deleting critical paths is blocked",
    ),
    (re.compile(r"\b(mkfs(\.\w+)?|wipefs|blkdiscard|shred)\b"), "disk formatting/wiping tools are blocked"),
    (re.compile(r"\bdd\b[^|;&]*\bof=/dev/"), "writing to raw devices is blocked"),
    (re.compile(r">+\s*/dev/(sd|nvme|xvd|vd|mmcblk|hd)"), "writing to raw devices is blocked"),
    (re.compile(r"\bch(mod|own)\b[^|;&]*\s(/|/\*)([\s;|&]|$)"), "recursive permission changes on / are blocked"),
    # Host / process sabotage
    (re.compile(r":\s*\(\s*\)\s*\{"), "fork bombs are blocked"),
    (re.compile(r"^(sudo\s+)?(shutdown|reboot|poweroff|halt)\b"), "shutting down the host is blocked"),
    (
        re.compile(r"\bsystemctl\s+(poweroff|reboot|halt|suspend|hibernate|emergency)\b"),
        "shutting down the host is blocked",
    ),
    (re.compile(r"\binit\s+[06]\b"), "shutting down the host is blocked"),
    (re.compile(r"\bkill\s+(-\w+\s+)*-1\b"), "killing all processes is blocked"),
    (re.compile(r"\bkillall\b"), "killall is blocked"),
    (re.compile(r"\bpm2\s+(kill|delete)\b"), "killing the bot's pm2 process is blocked"),
    (re.compile(r"\bcrontab\s+[^|;&]*-r\b"), "removing the crontab is blocked"),
    # Account / network tampering
    (
        re.compile(r"\b(useradd|userdel|usermod|adduser|deluser|passwd|visudo)\b"),
        "account management commands are blocked",
    ),
    (re.compile(r"\biptables\b[^|;&]*(\s-F\b|--flush)"), "flushing firewall rules is blocked"),
    (re.compile(r"\bufw\s+disable\b"), "disabling the firewall is blocked"),
    # Remote code execution
    (re.compile(r"\b(curl|wget)\b[^|;&]*\|[^|;&]*\b(ba|z|da)?sh\b"), "piping downloads into a shell is blocked"),
]


def _blocked_command_reason(command: str) -> str | None:
    normalized = " ".join(command.strip().split())
    for pattern, reason in BLOCKED_CONSOLE_PATTERNS:
        if pattern.search(normalized):
            return reason
    return None


class BlockedCommandConfirmView(discord.ui.View):
    """Owner-only override prompt for input caught by the console guardrails."""

    def __init__(self, console_view: "JskConsoleView", payload: bytes, display_input: str):
        super().__init__(timeout=60)
        self.console_view = console_view
        self.payload = payload
        self.display_input = display_input

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != BOT_OWNER_ID:
            await interaction.response.send_message(
                "Only the bot owner can override console restrictions.",
                ephemeral=True,
            )
            return False
        return True

    @discord.ui.button(label="Proceed", style=discord.ButtonStyle.danger)
    async def proceed_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.stop()
        self.console_view.last_input = f"[override] {self.display_input}"
        try:
            await self.console_view._write_bytes(self.payload)
        except RuntimeError as exc:
            await interaction.response.edit_message(content=str(exc), view=None)
            return
        await interaction.response.edit_message(
            content="⚠️ Override accepted — input sent to the terminal.",
            view=None,
        )
        await self.console_view.refresh_message(force=True)

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.stop()
        await interaction.response.edit_message(
            content="Cancelled — nothing was sent to the terminal.",
            view=None,
        )


class TerminalCommandModal(discord.ui.Modal, title="Run Terminal Command"):
    command = discord.ui.TextInput(
        label="Command",
        style=discord.TextStyle.paragraph,
        placeholder="npm run build",
        max_length=1500,
    )

    def __init__(self, console_view: "JskConsoleView"):
        super().__init__()
        self.console_view = console_view

    async def on_submit(self, interaction: discord.Interaction):
        await self.console_view.send_command(interaction, self.command.value)


class TerminalKeysModal(discord.ui.Modal, title="Send Raw Input"):
    raw_input = discord.ui.TextInput(
        label="Keys / Text",
        style=discord.TextStyle.paragraph,
        placeholder="Literal text or escapes like \\n, \\t, \\x03",
        max_length=1000,
        required=False,
    )

    def __init__(self, console_view: "JskConsoleView"):
        super().__init__()
        self.console_view = console_view

    async def on_submit(self, interaction: discord.Interaction):
        await self.console_view.send_raw_input(interaction, self.raw_input.value)


class JskConsoleView(discord.ui.View):
    def __init__(self, author: discord.abc.User, base_dir: str):
        super().__init__(timeout=3600)
        self.author_id = author.id
        self.author_mention = author.mention
        self.process: asyncio.subprocess.Process | None = None
        self.master_fd: int | None = None
        self.message: discord.Message | None = None
        self.reader_task: asyncio.Task | None = None
        self.refresh_task: asyncio.Task | None = None
        self.output_buffer = ""
        self.base_dir = base_dir
        self.cwd = self.base_dir
        self.last_input = "(none)"
        self.created_at = int(time.time())
        self.exit_code: int | None = None
        self.closed = False

    async def start(self) -> None:
        master_fd, slave_fd = pty.openpty()
        env = os.environ.copy()
        env["TERM"] = "xterm-256color"
        env["PS1"] = "jsk$ "
        env["PROMPT_COMMAND"] = ""

        self.process = await asyncio.create_subprocess_exec(
            "bash",
            "--noprofile",
            "--norc",
            "-i",
            stdin=slave_fd,
            stdout=slave_fd,
            stderr=slave_fd,
            cwd=self.base_dir,
            env=env,
            start_new_session=True,
        )
        os.close(slave_fd)
        os.set_blocking(master_fd, False)
        self.master_fd = master_fd
        self.reader_task = asyncio.create_task(self._read_output_loop())
        await self._write_bytes(f"cd {shlex.quote(self.base_dir)}\n".encode("utf-8"))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(
                "Only the user who opened this console can use these controls.",
                ephemeral=True,
            )
            return False
        return True

    async def on_timeout(self):
        await self.close(reason="Session timed out.")

    def _set_button_states(self) -> None:
        disabled = self.closed
        self.command_button.disabled = disabled
        self.keys_button.disabled = disabled
        self.enter_button.disabled = disabled
        self.ctrl_c_button.disabled = disabled
        self.tab_button.disabled = disabled
        self.up_button.disabled = disabled
        self.down_button.disabled = disabled
        self.refresh_button.disabled = disabled
        self.clear_button.disabled = disabled
        self.close_button.disabled = disabled

    def build_embed(self) -> discord.Embed:
        running = not self.closed and self.exit_code is None
        color = discord.Color.green() if running else discord.Color.red()
        status = "Running" if running else ("Closed" if self.exit_code is None else f"Exited ({self.exit_code})")
        output = _tail_text(
            self.output_buffer.strip() or "Terminal started. Waiting for output...",
            TERMINAL_EMBED_LIMIT,
        )
        embed = discord.Embed(
            title="Jishaku Console",
            description=f"```ansi\n{output}\n```",
            color=color,
        )
        embed.add_field(name="Status", value=status, inline=True)
        embed.add_field(name="Directory", value=f"`{self.cwd}`", inline=True)
        embed.add_field(name="Operator", value=self.author_mention, inline=True)
        embed.add_field(name="Last Input", value=f"`{self.last_input[:100]}`", inline=False)
        embed.add_field(
            name="Controls",
            value="`Run Command` `Send Raw Input` `Enter` `Ctrl+C` `Tab` `Up` `Down` `Refresh` `Clear View` `Close`",
            inline=False,
        )
        embed.set_footer(text=f"Started at {self.created_at} UTC timestamp")
        return embed

    async def refresh_message(self, *, force: bool = False) -> None:
        self._set_button_states()
        if not self.message:
            return
        if not force and self.refresh_task and not self.refresh_task.done():
            return
        if force:
            with contextlib.suppress(discord.HTTPException):
                await self.message.edit(embed=self.build_embed(), view=self)
            return

        async def _refresh_later():
            await asyncio.sleep(1.0)
            if self.message:
                with contextlib.suppress(discord.HTTPException):
                    await self.message.edit(embed=self.build_embed(), view=self)

        self.refresh_task = asyncio.create_task(_refresh_later())

    async def _write_bytes(self, payload: bytes) -> None:
        if self.closed or self.master_fd is None:
            raise RuntimeError("Console session is closed.")
        await asyncio.to_thread(os.write, self.master_fd, payload)

    async def _read_output_loop(self) -> None:
        try:
            while self.master_fd is not None:
                try:
                    chunk = await asyncio.to_thread(os.read, self.master_fd, 4096)
                except BlockingIOError:
                    await asyncio.sleep(0.15)
                    continue
                except OSError:
                    break

                if not chunk:
                    await asyncio.sleep(0.15)
                    if self.process and self.process.returncode is not None:
                        break
                    continue

                decoded = _normalize_terminal_output(chunk.decode("utf-8", errors="replace"))
                self.output_buffer = _tail_text(self.output_buffer + decoded, TERMINAL_OUTPUT_LIMIT)
                await self.refresh_message()
        finally:
            if self.process and self.exit_code is None:
                self.exit_code = await self.process.wait()
            if self.master_fd is not None:
                with contextlib.suppress(OSError):
                    os.close(self.master_fd)
                self.master_fd = None
            if active_console_sessions.get(self.author_id) is self:
                active_console_sessions.pop(self.author_id, None)
            if not self.closed:
                self.closed = True
                await self.refresh_message(force=True)

    async def send_command(self, interaction: discord.Interaction, command: str) -> None:
        command = command.strip()
        if not command:
            await interaction.response.send_message("Command cannot be empty.", ephemeral=True)
            return

        blocked_reason = _blocked_command_reason(command)
        if blocked_reason:
            if interaction.user.id != BOT_OWNER_ID:
                self.last_input = f"[blocked] {command}"
                await interaction.response.send_message(f"⛔ Command blocked: {blocked_reason}.", ephemeral=True)
                await self.refresh_message(force=True)
                return
            await interaction.response.send_message(
                f"⚠️ **Restricted command** — {blocked_reason}.\n"
                f"```\n{command[:500]}\n```\n"
                "Running this can expose secrets or damage the host. Proceed anyway?",
                view=BlockedCommandConfirmView(self, (command + "\n").encode("utf-8"), command[:80]),
                ephemeral=True,
            )
            return

        self.last_input = command
        try:
            await self._write_bytes((command + "\n").encode("utf-8"))
        except RuntimeError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return

        await interaction.response.defer()
        await self.refresh_message(force=True)

    async def send_raw_input(self, interaction: discord.Interaction, raw_input: str) -> None:
        payload_text = raw_input or "\n"
        try:
            payload = bytes(payload_text, "utf-8").decode("unicode_escape").encode("utf-8")
        except UnicodeDecodeError:
            await interaction.response.send_message("Invalid escape sequence in raw input.", ephemeral=True)
            return

        blocked_reason = _blocked_command_reason(payload.decode("utf-8", errors="replace"))
        if blocked_reason:
            display_input = payload_text.replace("\n", "\\n")
            if interaction.user.id != BOT_OWNER_ID:
                self.last_input = f"[blocked] {display_input[:80]}"
                await interaction.response.send_message(f"⛔ Input blocked: {blocked_reason}.", ephemeral=True)
                await self.refresh_message(force=True)
                return
            await interaction.response.send_message(
                f"⚠️ **Restricted input** — {blocked_reason}.\n"
                f"```\n{display_input[:500]}\n```\n"
                "Sending this can expose secrets or damage the host. Proceed anyway?",
                view=BlockedCommandConfirmView(self, payload, display_input[:80]),
                ephemeral=True,
            )
            return

        self.last_input = payload_text.replace("\n", "\\n")
        try:
            await self._write_bytes(payload)
        except RuntimeError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return

        await interaction.response.defer()
        await self.refresh_message(force=True)

    async def send_keybind(self, interaction: discord.Interaction, payload: bytes, label: str) -> None:
        self.last_input = label
        try:
            await self._write_bytes(payload)
        except RuntimeError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return
        await interaction.response.defer()
        await self.refresh_message(force=True)

    async def close(self, *, reason: str | None = None) -> None:
        if self.closed:
            return
        self.closed = True
        active_console_sessions.pop(self.author_id, None)

        if self.process and self.process.returncode is None:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(self.process.pid, signal.SIGTERM)
            try:
                await asyncio.wait_for(self.process.wait(), timeout=3)
            except asyncio.TimeoutError:
                with contextlib.suppress(ProcessLookupError):
                    os.killpg(self.process.pid, signal.SIGKILL)
                self.exit_code = await self.process.wait()
            else:
                self.exit_code = self.process.returncode
        elif self.process:
            self.exit_code = self.process.returncode

        if self.reader_task and self.reader_task is not asyncio.current_task():
            self.reader_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self.reader_task

        if self.master_fd is not None:
            with contextlib.suppress(OSError):
                os.close(self.master_fd)
            self.master_fd = None

        if reason:
            self.output_buffer = _tail_text(f"{self.output_buffer}\n\n[console] {reason}\n", TERMINAL_OUTPUT_LIMIT)

        await self.refresh_message(force=True)

    @discord.ui.button(label="Run Command", style=discord.ButtonStyle.primary, row=0)
    async def command_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(TerminalCommandModal(self))

    @discord.ui.button(label="Send Raw Input", style=discord.ButtonStyle.secondary, row=0)
    async def keys_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(TerminalKeysModal(self))

    @discord.ui.button(label="Enter", style=discord.ButtonStyle.success, row=0)
    async def enter_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.send_keybind(interaction, b"\n", "Enter")

    @discord.ui.button(label="Ctrl+C", style=discord.ButtonStyle.danger, row=0)
    async def ctrl_c_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.send_keybind(interaction, b"\x03", "Ctrl+C")

    @discord.ui.button(label="Tab", style=discord.ButtonStyle.secondary, row=1)
    async def tab_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.send_keybind(interaction, b"\t", "Tab")

    @discord.ui.button(label="Up", style=discord.ButtonStyle.secondary, row=1)
    async def up_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.send_keybind(interaction, b"\x1b[A", "Up")

    @discord.ui.button(label="Down", style=discord.ButtonStyle.secondary, row=1)
    async def down_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.send_keybind(interaction, b"\x1b[B", "Down")

    @discord.ui.button(label="Refresh", style=discord.ButtonStyle.primary, row=1)
    async def refresh_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        await self.refresh_message(force=True)

    @discord.ui.button(label="Clear View", style=discord.ButtonStyle.secondary, row=2)
    async def clear_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.output_buffer = ""
        self.last_input = "clear-view"
        await interaction.response.defer()
        await self.refresh_message(force=True)

    @discord.ui.button(label="Close", style=discord.ButtonStyle.danger, row=2)
    async def close_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        await self.close(reason="Console closed by operator.")


def register_jsk_console_subcommand(
    bot: commands.Bot,
    *,
    base_dir: str | PathLike[str],
    owner_only: bool = True,
) -> None:
    """Register `jsk console` on a bot after the jishaku command tree is loaded."""
    jsk_command = bot.get_command("jsk")
    if jsk_command is None:
        logging.warning("Unable to register jsk console subcommand: jsk command not found.")
        return

    if getattr(jsk_command, "get_command", None) and jsk_command.get_command("console"):
        return

    resolved_base_dir = os.fspath(base_dir)

    async def jsk_console(ctx: commands.Context):
        previous_session = active_console_sessions.get(ctx.author.id)
        if previous_session is not None:
            await previous_session.close(reason="Replaced by a new console session.")

        console_view = JskConsoleView(ctx.author, resolved_base_dir)
        try:
            await console_view.start()
        except Exception as exc:
            logging.exception("Failed to start Discord console session: %s", exc)
            await ctx.send(f"Failed to start console session: `{exc}`")
            return

        active_console_sessions[ctx.author.id] = console_view
        message = await ctx.send(embed=console_view.build_embed(), view=console_view)
        console_view.message = message
        await console_view.refresh_message(force=True)

    wrapped_command = commands.command(name="console")(jsk_console)
    if owner_only:
        wrapped_command = commands.is_owner()(wrapped_command)

    jsk_command.add_command(wrapped_command)

