import logging
import re

import discord
from discord.ext import commands


APPLICATION_RESULT_CHANNEL = 1532878932297388092
APPLICATION_ACCEPTED_ROLE = 1532191224109338675
APPLICATION_PROCESSED_ROLE = 1532905469922775060

USER_ID_RE = re.compile(r"\d{15,20}")
ACCEPTED_RE = re.compile(r"\byes\b", re.IGNORECASE)
DENIED_RE = re.compile(r"\bno\b", re.IGNORECASE)


def _normalize_field_name(name: str) -> str:
    """Lowercase a field name and drop markdown/punctuation so titles like
    '**Discord User ID:**' still match."""
    return re.sub(r"[^a-z0-9]", "", (name or "").lower())


def _parse_application_embed(embed: discord.Embed) -> tuple[bool, bool, int | None]:
    accepted = False
    decided = False
    user_id = None

    for field in embed.fields:
        norm = _normalize_field_name(field.name)
        value = field.value or ""

        if "result" in norm:
            if ACCEPTED_RE.search(value):
                accepted = True
                decided = True
            elif DENIED_RE.search(value):
                decided = True
        elif "discorduserid" in norm:
            match = USER_ID_RE.search(value)
            if match:
                user_id = int(match.group())

    return accepted, decided, user_id


class Applications(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener("on_message")
    async def application_result_listener(self, message: discord.Message):
        if (
            message.webhook_id is None
            or message.channel.id != APPLICATION_RESULT_CHANNEL
            or message.guild is None
            or not message.embeds
        ):
            return

        for embed in message.embeds:
            accepted, decided, user_id = _parse_application_embed(embed)
            if not decided or user_id is None:
                continue
            await self._grant_roles(message.guild, user_id, accepted)
            break

    async def _grant_roles(self, guild: discord.Guild, user_id: int, accepted: bool):
        member = guild.get_member(user_id)
        if member is None:
            try:
                member = await guild.fetch_member(user_id)
            except discord.NotFound:
                logging.info(f"Application result for {user_id}, but they aren't in the server.")
                return
            except discord.HTTPException as e:
                logging.error(f"Failed to fetch member {user_id} for application role: {e}")
                return

        wanted = [APPLICATION_PROCESSED_ROLE]
        if accepted:
            wanted.append(APPLICATION_ACCEPTED_ROLE)

        have = {role.id for role in member.roles}
        missing = [discord.Object(id=rid) for rid in wanted if rid not in have]
        if not missing:
            return

        result = "YES" if accepted else "NO"
        try:
            await member.add_roles(*missing, reason=f"Application result: {result}")
        except (discord.Forbidden, discord.HTTPException) as e:
            logging.error(f"Failed to add application role(s) to {user_id}: {e}")


async def setup(bot):
    await bot.add_cog(Applications(bot))
