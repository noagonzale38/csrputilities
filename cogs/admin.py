import discord
from discord.ext import commands
from discord import app_commands

from config import (
    blacklisted_command, report_blacklists, SECRET_USER_ID,
    is_bot_dev, is_noah_or_directive,
    get_api_mode, set_api_mode,
)
from cogs.helpers import (
    Colors, BLANK_COLOR, CROSS, PENDING, CSRP_ICON,
    success_embed, error_embed, info_embed, brand_footer,
    ConfirmView,
)


class Admin(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.sentry_errors = {}

    @commands.command(name="generate_error_embed", description="Generate an error embed.")
    @is_noah_or_directive()
    async def generate_error_embed(self, ctx, errorType: str, errorid: str, customuser: str, customcommand: str, customchannel: str):
        embed = discord.Embed(
            title="Command Error",
            description=(
                f"An error occurred while processing your command. "
                f"If this issue persists, please [join our support server](https://discord.gg/B8959ZPPpp).\n\n"
                f"> **Error ID:** `{errorid}`"
            ),
            color=BLANK_COLOR,
        )
        embed.set_author(name="CSRP Utilities", icon_url=CSRP_ICON)
        brand_footer(embed)
        self.sentry_errors[errorid] = {"user": str(customuser), "command": str(customcommand), "channel": str(customchannel), "error": str(errorType)}
        await ctx.send(embed=embed)

    @commands.command()
    async def execute_secret_command(self, ctx):
        if ctx.author.id != SECRET_USER_ID:
            await ctx.reply(embed=error_embed("Not Authorized", "You are not authorized to use this command."), mention_author=False)
            return
        try:
            await ctx.author.send("test")
            await ctx.reply(embed=success_embed("Command Executed", "Command executed successfully."), mention_author=False)
        except discord.Forbidden:
            await ctx.reply(embed=error_embed("DM Failed", "Could not send a DM."), mention_author=False)

    @commands.command(name="switchapi", description="Switch the PRC API key between prod and test.")
    @is_bot_dev()
    async def switchapi(self, ctx, mode: str = None):
        if mode is None or mode.lower() not in ("prod", "test"):
            await ctx.reply(
                embed=error_embed(
                    "Invalid Mode",
                    f"Usage: `-switchapi <prod|test>`\n\n> **Current Mode:** `{get_api_mode()}`",
                ),
                mention_author=False,
            )
            return

        mode = mode.lower()
        if mode == get_api_mode():
            await ctx.reply(
                embed=info_embed("No Change", f"The PRC API is already using the **{mode}** key."),
                mention_author=False,
            )
            return

        try:
            set_api_mode(mode)
        except ValueError as e:
            await ctx.reply(embed=error_embed("Switch Failed", str(e)), mention_author=False)
            return

        await ctx.reply(
            embed=success_embed("API Key Switched", f"The PRC API is now using the **{mode}** key."),
            mention_author=False,
        )

    @commands.hybrid_command(name="command_blacklist", description="Blacklists a user from using ERLC commands.")
    @is_bot_dev()
    async def command_blacklist(self, ctx, user: discord.Member):
        view = ConfirmView(ctx.author, timeout=15)
        embed = discord.Embed(
            title="Confirm Blacklist",
            description=(
                f"Are you sure you want to blacklist **{user.display_name}** from ERLC commands?\n\n"
                f"> **Requested By:** {ctx.author.mention}\n"
                f"> **Target:** {user.mention}"
            ),
            color=BLANK_COLOR,
        )
        embed.set_author(name=ctx.guild.name, icon_url=ctx.guild.icon.url if ctx.guild.icon else "")
        brand_footer(embed)
        msg = await ctx.send(embed=embed, view=view)
        view.message = msg
        await view.wait()

        if view.value:
            with open(blacklisted_command, "a") as file:
                file.write(f"{{userid: {user.id}}}\n")
            await msg.edit(embed=success_embed("User Blacklisted", f"**{user.name}** has been blacklisted from using ERLC commands."), view=None)
        elif view.value is False:
            await msg.edit(embed=discord.Embed(title="Action Cancelled", description="The action has been cancelled.", color=BLANK_COLOR), view=None)
        else:
            await msg.edit(embed=discord.Embed(title="Action Timed Out", description="The action has timed out.", color=BLANK_COLOR), view=None)

    @commands.hybrid_command(name="remove_blacklist", description="Removes a user from the ERLC command blacklist.")
    @is_bot_dev()
    async def remove_blacklist(self, ctx, user: discord.Member):
        view = ConfirmView(ctx.author, timeout=15)
        embed = discord.Embed(
            title="Confirm Removal",
            description=(
                f"Are you sure you want to remove **{user.display_name}** from the blacklist?\n\n"
                f"> **Requested By:** {ctx.author.mention}\n"
                f"> **Target:** {user.mention}"
            ),
            color=BLANK_COLOR,
        )
        embed.set_author(name=ctx.guild.name, icon_url=ctx.guild.icon.url if ctx.guild.icon else "")
        brand_footer(embed)
        msg = await ctx.send(embed=embed, view=view)
        view.message = msg
        await view.wait()

        if view.value:
            try:
                with open(blacklisted_command, "r") as file:
                    lines = file.readlines()
                with open(blacklisted_command, "w") as file:
                    for line in lines:
                        if f"{{userid: {user.id}}}" not in line:
                            file.write(line)
            except FileNotFoundError:
                pass
            await msg.edit(embed=success_embed("User Removed", f"**{user.name}** has been removed from the command blacklist."), view=None)
        elif view.value is False:
            await msg.edit(embed=discord.Embed(title="Action Cancelled", description="The action has been cancelled.", color=BLANK_COLOR), view=None)
        else:
            await msg.edit(embed=discord.Embed(title="Action Timed Out", description="The action has timed out.", color=BLANK_COLOR), view=None)

    @commands.hybrid_command(name="report_blacklist", description="Blacklists a user from using the report feature.")
    @is_bot_dev()
    async def report_blacklist(self, ctx, user: discord.Member):
        view = ConfirmView(ctx.author, timeout=15)
        embed = discord.Embed(
            title="Confirm Blacklist",
            description=(
                f"Are you sure you want to blacklist **{user.display_name}** from Reporting?\n\n"
                f"> **Requested By:** {ctx.author.mention}\n"
                f"> **Target:** {user.mention}"
            ),
            color=BLANK_COLOR,
        )
        embed.set_author(name=ctx.guild.name, icon_url=ctx.guild.icon.url if ctx.guild.icon else "")
        brand_footer(embed)
        msg = await ctx.send(embed=embed, view=view)
        view.message = msg
        await view.wait()

        if view.value:
            with open(report_blacklists, "a") as file:
                file.write(f"{{userid: {user.id}}}\n")
            await msg.edit(embed=success_embed("User Blacklisted", f"**{user.name}** has been blacklisted from reporting."), view=None)
        elif view.value is False:
            await msg.edit(embed=discord.Embed(title="Action Cancelled", description="The action has been cancelled.", color=BLANK_COLOR), view=None)
        else:
            await msg.edit(embed=discord.Embed(title="Action Timed Out", description="The action has timed out.", color=BLANK_COLOR), view=None)

    @commands.hybrid_command(name="remove_reportblacklist", description="Removes a user from the report blacklist.")
    @is_bot_dev()
    async def remove_reportblacklist(self, ctx, user: discord.Member):
        view = ConfirmView(ctx.author, timeout=15)
        embed = discord.Embed(
            title="Confirm Removal",
            description=(
                f"Are you sure you want to remove **{user.display_name}** from the report blacklist?\n\n"
                f"> **Requested By:** {ctx.author.mention}\n"
                f"> **Target:** {user.mention}"
            ),
            color=BLANK_COLOR,
        )
        embed.set_author(name=ctx.guild.name, icon_url=ctx.guild.icon.url if ctx.guild.icon else "")
        brand_footer(embed)
        msg = await ctx.send(embed=embed, view=view)
        view.message = msg
        await view.wait()

        if view.value:
            try:
                with open(report_blacklists, "r") as file:
                    lines = file.readlines()
                with open(report_blacklists, "w") as file:
                    for line in lines:
                        if f"{{userid: {user.id}}}" not in line:
                            file.write(line)
            except FileNotFoundError:
                pass
            await msg.edit(embed=success_embed("User Removed", f"**{user.name}** has been removed from the report blacklist."), view=None)
        elif view.value is False:
            await msg.edit(embed=discord.Embed(title="Action Cancelled", description="The action has been cancelled.", color=BLANK_COLOR), view=None)
        else:
            await msg.edit(embed=discord.Embed(title="Action Timed Out", description="The action has timed out.", color=BLANK_COLOR), view=None)


async def setup(bot):
    await bot.add_cog(Admin(bot))
