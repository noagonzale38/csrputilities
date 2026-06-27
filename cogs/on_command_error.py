import discord
from discord.ext import commands
import sentry_sdk
import random

from config import ERRORS_CHANNEL, CSRPUTILS_DEVS
from cogs.helpers import (
    BLANK_COLOR, CSRP_ICON, DEVELOPER,
    error_embed, brand_footer, embed_description, user_tag,
)


class CommandErrorHandler(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.sentry_errors = {}

    @commands.Cog.listener()
    async def on_command_error(self, ctx, error):
        if isinstance(error, commands.MissingRequiredArgument):
            await ctx.send(embed=error_embed("Missing Argument", f"Missing required argument: `{error.param.name}`"))
            return
        if isinstance(error, commands.NotOwner):
            await ctx.send(embed=error_embed("Not Permitted", "You do not have permission to use this command."))
            return
        if isinstance(error, commands.CommandNotFound):
            return
        if isinstance(error, commands.MissingPermissions):
            await ctx.send(embed=error_embed("Not Permitted", "You do not have permission to use this command."))
            return
        if isinstance(error, commands.BotMissingPermissions):
            await ctx.send(embed=error_embed("Missing Permissions", "I lack the required permissions to execute this command. Please try again later."))
            return
        if isinstance(error, commands.CheckFailure):
            await ctx.send(embed=error_embed("Not Permitted", "You do not have permission to use this command."))
            return
        if isinstance(error, commands.MemberNotFound):
            await ctx.send(embed=error_embed("Member Not Found", "Could not find that member."))
            return
        if isinstance(error, commands.NoPrivateMessage):
            await ctx.send(embed=error_embed("Server Only", "This command cannot be used in private messages."))
            return

        await self._handle_command_error(ctx, error)

    async def _handle_command_error(self, ctx, error):
        error_id = f"error_{random.randint(100000, 999999)}"
        sentry_url = None

        log_channel = self.bot.get_channel(ERRORS_CHANNEL)
        if log_channel:
            try:
                embed = discord.Embed(
                    title="Error Logged",
                    description=embed_description(
                        (
                            f"> **Command:** `{ctx.command}`\n"
                            f"> **User:** {user_tag(ctx.author)}\n"
                            f"> **Channel:** {ctx.channel.mention}\n"
                            f"> **Error ID:** `{error_id}`"
                        ),
                        f"```{str(error)[:1000]}```",
                    ),
                    color=BLANK_COLOR,
                    timestamp=ctx.message.created_at,
                )
                embed.set_author(name="CSRP Utilities", icon_url=CSRP_ICON)
                embed.set_thumbnail(url=CSRP_ICON)
                brand_footer(embed)
                await log_channel.send(embed=embed)
            except Exception as log_error:
                sentry_sdk.capture_exception(log_error)

        try:
            with sentry_sdk.push_scope() as scope:
                scope.set_tag("error_id", error_id)
                scope.set_context("Command Details", {
                    "user": ctx.author.id if ctx.author else "Unknown",
                    "command": ctx.command.name if ctx.command else "Unknown",
                    "channel": ctx.channel.name if ctx.channel else "DM",
                    "message": ctx.message.content if ctx.message else "Unknown",
                })
                event_id = sentry_sdk.capture_exception(error)
            sentry_url = f"https://sentry.io/organizations/csrpdevteam/issues/?query={event_id}"
        except Exception as sentry_error:
            sentry_sdk.capture_exception(sentry_error)

        self.sentry_errors[error_id] = {"user": ctx.author.name, "command": str(ctx.command), "channel": str(ctx.channel), "error": str(error)}

        if ctx.author.id in CSRPUTILS_DEVS:
            embed = discord.Embed(
                title="Command Failure",
                description=(
                    f"An error occurred. If this persists, please [join our support server](https://discord.gg/B8959ZPPpp).\n\n"
                    f"> {DEVELOPER} **{ctx.author.name}**, you are a CSRP Utilities developer."
                ),
                color=BLANK_COLOR,
            )
            embed.set_author(name="CSRP Utilities", icon_url=CSRP_ICON)
            embed.add_field(
                name="Debug Information",
                value=(
                    f"> **Error ID:** `{error_id}`\n"
                    + (f"> **Sentry:** [View Issue]({sentry_url})\n" if sentry_url else "> **Sentry:** N/A\n")
                ),
                inline=False,
            )
            brand_footer(embed)
            await ctx.send(embed=embed)
            return

        embed = discord.Embed(
            title="Command Failure",
            description=(
                "An error occurred. If this persists, please [join our support server](https://discord.gg/B8959ZPPpp).\n\n"
                f"> **Error ID:** `{error_id}`"
            ),
            color=BLANK_COLOR,
        )
        embed.set_author(name="CSRP Utilities", icon_url=CSRP_ICON)
        brand_footer(embed)
        await ctx.send(embed=embed)
        raise error


async def setup(bot):
    await bot.add_cog(CommandErrorHandler(bot))
