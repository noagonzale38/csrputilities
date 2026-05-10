import discord
from discord.ext import commands
import sentry_sdk
import asyncio
import os
import json
import logging
import shlex
import sys
from typing import Optional

from config import (
    TOKEN, SENTRY_DSN, LOG_FILE, afk_file,
    IS_TESTING, BOT_OWNER_ID, is_testing_allowed,
    load_testing_users, save_testing_users,
)

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

bot = commands.Bot(command_prefix="-", help_command=None, intents=intents)
console_task = None

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

    command_name = parts[0].lower()

    if command_name == "restart":
        logging.info("Console command received: restart")
        await bot.close()
        os.execv(sys.executable, [sys.executable] + sys.argv)

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
