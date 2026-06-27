import discord
from discord.ext import commands
import sentry_sdk
import asyncio
import contextlib
import os
import json
import logging
import pty
import re
import shlex
import signal
import sys
import time
from typing import Optional

from config import (
    TOKEN, SENTRY_DSN, LOG_FILE, afk_file, BASE_DIR,
    IS_TESTING, BOT_OWNER_ID, is_testing_allowed,
    load_testing_users, save_testing_users,
)
from cogs.helpers import install_components_v2_transport
from lib.claude_runner import run_claude_prompt

TARGET_GUILD_ID = 965829463512330260

sentry_sdk.init(
    dsn=SENTRY_DSN,
    traces_sample_rate=1.0,
    environment="production",
    release="csrputils@2.0.0",
)

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler(),
    ],
)

if not os.path.exists(afk_file):
    with open(afk_file, "w") as f:
        json.dump({}, f)

intents = discord.Intents.all()

install_components_v2_transport()
bot = commands.Bot(command_prefix="-", help_command=None, intents=intents)
console_task = None
active_console_sessions: dict[int, "JskConsoleView"] = {}
JSK_RESTART_ALLOWED_USER_ID = 654110914311618561

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


async def _can_use_jsk_restart(ctx: commands.Context) -> bool:
    if await bot.is_owner(ctx.author):
        return True
    return ctx.author.id == JSK_RESTART_ALLOWED_USER_ID


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
    def __init__(self, author: discord.abc.User):
        super().__init__(timeout=3600)
        self.author_id = author.id
        self.author_mention = author.mention
        self.process: asyncio.subprocess.Process | None = None
        self.master_fd: int | None = None
        self.message: discord.Message | None = None
        self.reader_task: asyncio.Task | None = None
        self.refresh_task: asyncio.Task | None = None
        self.output_buffer = ""
        self.base_dir = str(BASE_DIR)
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
        output = _tail_text(self.output_buffer.strip() or "Terminal started. Waiting for output...", TERMINAL_EMBED_LIMIT)
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

if IS_TESTING:
    @bot.check
    async def testing_mode_check(ctx):
        if is_testing_allowed(ctx.author.id):
            return True
        raise commands.CheckFailure("Bot is in testing mode. You are not authorized to use commands.")

    @bot.group(name="testing", invoke_without_command=True)
    async def testing_group(ctx):
        if ctx.author.id != BOT_OWNER_ID:
            return
        testers = load_testing_users()
        if not testers:
            await ctx.send("**Testing Mode** | No testers added yet.")
            return
        user_list = ", ".join(f"<@{uid}>" for uid in testers)
        await ctx.send(f"**Testing Mode** | Authorized testers: {user_list}")

    @testing_group.command(name="add")
    async def testing_add(ctx, user: discord.Member):
        if ctx.author.id != BOT_OWNER_ID:
            return
        testers = load_testing_users()
        testers.add(user.id)
        save_testing_users(testers)
        await ctx.send(f"**Testing Mode** | Added **{user.display_name}** to the testers list.")

    @testing_group.command(name="remove")
    async def testing_remove(ctx, user: discord.Member):
        if ctx.author.id != BOT_OWNER_ID:
            return
        testers = load_testing_users()
        testers.discard(user.id)
        save_testing_users(testers)
        await ctx.send(f"**Testing Mode** | Removed **{user.display_name}** from the testers list.")

    logging.info("Testing mode is ENABLED — commands restricted to owner and approved testers.")


COGS = [
    "cogs.moderation",
    "cogs.erlc",
    "cogs.sessions",
    "cogs.training",
    "cogs.fun",
    "cogs.music",
    "cogs.utility",
    "cogs.embed_creator",
    "cogs.admin",
    "cogs.hits",
    "cogs.events",
    "cogs.settings",
    "cogs.staffmgmt",
    "cogs.punishments",
    "cogs.on_command_error",
]


async def load_cogs():
    for cog in COGS:
        try:
            await bot.load_extension(cog)
            logging.info(f"Loaded {cog}")
        except Exception as e:
            logging.error(f"Failed to load {cog}: {e}")


def _clean_mention(raw_value: str) -> str:
    return raw_value.strip().strip("<@!@&>#")


async def _get_target_guild() -> Optional[discord.Guild]:
    guild = bot.get_guild(TARGET_GUILD_ID)
    if guild is None:
        try:
            guild = await bot.fetch_guild(TARGET_GUILD_ID)
        except discord.HTTPException:
            return None
    return guild


async def _resolve_member(guild: discord.Guild, raw_value: str) -> Optional[discord.Member]:
    cleaned = _clean_mention(raw_value)
    if cleaned.isdigit():
        member = guild.get_member(int(cleaned))
        if member is not None:
            return member
        try:
            return await guild.fetch_member(int(cleaned))
        except discord.HTTPException:
            return None

    lowered = raw_value.lower()
    for member in guild.members:
        if member.name.lower() == lowered or member.display_name.lower() == lowered:
            return member
    return None


def _resolve_role(guild: discord.Guild, raw_value: str) -> Optional[discord.Role]:
    cleaned = _clean_mention(raw_value)
    if cleaned.isdigit():
        return guild.get_role(int(cleaned))

    lowered = raw_value.lower()
    for role in guild.roles:
        if role.name.lower() == lowered:
            return role
    return None


async def _resolve_channel(raw_value: str):
    cleaned = _clean_mention(raw_value)
    if not cleaned.isdigit():
        return None

    channel_id = int(cleaned)
    channel = bot.get_channel(channel_id)
    if channel is not None:
        return channel

    try:
        return await bot.fetch_channel(channel_id)
    except discord.HTTPException:
        return None


async def handle_console_command(command_line: str):
    try:
        parts = shlex.split(command_line)
    except ValueError as exc:
        logging.error(f"Invalid console command syntax: {exc}")
        return

    if not parts:
        return

    command_name = parts[0].lower().lstrip("/")

    if command_name == "restart":
        logging.info("Console command received: restart")
        await bot.close()
        os.execv(sys.executable, [sys.executable] + sys.argv)

    if command_name == "claude":
        if len(parts) < 2:
            logging.error("Usage: /claude {prompt}")
            return

        prompt = " ".join(parts[1:])
        logging.info(f"Running Claude in {BASE_DIR} with prompt: {prompt}")
        try:
            return_code, stdout, stderr = await run_claude_prompt(prompt)
        except OSError as exc:
            logging.error("Unable to launch Claude: %s", exc)
            return
        if stdout.strip():
            logging.info("Claude stdout:\n%s", stdout.strip())
        if stderr.strip():
            logging.warning("Claude stderr:\n%s", stderr.strip())
        logging.info("Claude exited with code %s", return_code)
        return

    guild = await _get_target_guild()
    if guild is None:
        logging.error(f"Unable to resolve guild {TARGET_GUILD_ID} for console command execution.")
        return

    if command_name == "say":
        if len(parts) < 3:
            logging.error("Usage: say {channel_id} {message}")
            return

        channel = await _resolve_channel(parts[1])
        if channel is None:
            logging.error(f"Channel not found: {parts[1]}")
            return
        if getattr(channel, "guild", None) is None or channel.guild.id != TARGET_GUILD_ID:
            logging.error(f"Channel {parts[1]} is not in guild {TARGET_GUILD_ID}")
            return

        message = " ".join(parts[2:])
        await channel.send(message)
        logging.info(f"Sent console message to channel {getattr(channel, 'id', parts[1])}")
        return

    if command_name in {"addrole", "removerole"}:
        if len(parts) < 3:
            logging.error(f"Usage: {command_name} {{user}} {{roleName}}")
            return

        member = await _resolve_member(guild, parts[1])
        if member is None:
            logging.error(f"Member not found: {parts[1]}")
            return

        role_name = " ".join(parts[2:])
        role = _resolve_role(guild, role_name)
        if role is None:
            logging.error(f"Role not found: {role_name}")
            return

        if command_name == "addrole":
            await member.add_roles(role, reason="Console command")
            logging.info(f"Added role '{role.name}' to {member} via console command")
        else:
            await member.remove_roles(role, reason="Console command")
            logging.info(f"Removed role '{role.name}' from {member} via console command")
        return

    if command_name == "status":
        if len(parts) < 2:
            logging.error("Usage: status {newStatus}")
            return

        status_text = " ".join(parts[1:])
        activity = discord.Activity(type=discord.ActivityType.playing, name=status_text)
        await bot.change_presence(activity=activity)
        logging.info(f"Updated bot status to: {status_text}")
        return

    logging.error(f"Unknown console command: {command_name}")


async def _pm2_restart_bot(delay: float = 1.0):
    await asyncio.sleep(delay)
    try:
        process = await asyncio.create_subprocess_exec(
            "pm2",
            "restart",
            "bot",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await process.communicate()
        if stdout:
            logging.info("pm2 restart bot stdout: %s", stdout.decode().strip())
        if stderr:
            logging.warning("pm2 restart bot stderr: %s", stderr.decode().strip())
    except Exception as exc:
        logging.exception("Failed to restart bot with pm2: %s", exc)


def _register_jsk_restart_subcommand():
    jsk_command = bot.get_command("jsk")
    if jsk_command is None:
        logging.warning("Unable to register jsk subcommands: jsk command not found.")
        return

    if not (getattr(jsk_command, "get_command", None) and jsk_command.get_command("restart")):
        @commands.command(name="restart")
        @commands.check(_can_use_jsk_restart)
        async def jsk_restart(ctx):
            await ctx.send("Restarting bot with PM2...")
            asyncio.create_task(_pm2_restart_bot())

        jsk_command.add_command(jsk_restart)
        logging.info("Registered jsk restart subcommand.")

    if not (getattr(jsk_command, "get_command", None) and jsk_command.get_command("console")):
        @commands.command(name="console")
        @commands.is_owner()
        async def jsk_console(ctx):
            previous_session = active_console_sessions.get(ctx.author.id)
            if previous_session is not None:
                await previous_session.close(reason="Replaced by a new console session.")

            console_view = JskConsoleView(ctx.author)
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

        jsk_command.add_command(jsk_console)
        logging.info("Registered jsk console subcommand.")


async def console_command_loop():
    while not bot.is_closed():
        try:
            command_line = await asyncio.to_thread(input, "")
        except EOFError:
            logging.warning("Console input closed; stopping console command listener.")
            return
        except Exception as exc:
            logging.exception(f"Console listener failed while reading input: {exc}")
            await asyncio.sleep(1)
            continue

        if not command_line.strip():
            continue

        try:
            await handle_console_command(command_line.strip())
        except Exception as exc:
            logging.exception(f"Console command failed: {exc}")


@bot.event
async def setup_hook():
    await load_cogs()
    try:
        await bot.load_extension("jishaku")
        _register_jsk_restart_subcommand()
    except Exception:
        pass


@bot.event
async def on_ready():
    global console_task
    if console_task is None or console_task.done():
        console_task = asyncio.create_task(console_command_loop())
        logging.info("Console command listener started.")
    logging.info(f"Bot is ready! Logged in as {bot.user}")


def run():
    bot.run(TOKEN)
