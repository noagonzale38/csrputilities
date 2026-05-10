import discord
from discord.ext import commands
from discord import app_commands, ui
import json
from typing import Optional

from config import active_hits, BLACKLIST_ROLE_ID
from cogs.helpers import (
    Colors, BLANK_COLOR, CHECK, CROSS, CSRP_ICON,
    success_embed, error_embed, info_embed, brand_footer, embed_description,
    PaginatorView,
)


class DenyHitModal(discord.ui.Modal, title="Deny Hit"):
    reason = ui.TextInput(label="Reason", placeholder="Reason for denying the hit", required=True)

    def __init__(self, parent_view, orig_interaction):
        super().__init__()
        self.parent_view = parent_view
        self.orig_interaction = orig_interaction

    async def on_submit(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="Hit Denied",
            description=embed_description(
                (
                    f"> **Placed By:** {self.parent_view.ctx.author.mention}\n"
                    f"> **Target:** `{self.parent_view.username}`\n"
                    f"> **Bounty:** `{self.parent_view.bounty}` in-game money\n"
                    f"> **Reason:** {self.parent_view.reason}"
                ),
                (
                    f"> **Denied By:** {interaction.user.mention}\n"
                    f"> **Denial Reason:** {self.reason.value}"
                ),
            ),
            color=BLANK_COLOR,
        )
        embed.set_author(name="CSRP Utilities", icon_url=CSRP_ICON)
        if self.parent_view.ctx.author.display_avatar:
            embed.set_thumbnail(url=self.parent_view.ctx.author.display_avatar.url)
        brand_footer(embed)
        await self.orig_interaction.message.edit(embed=embed, view=None)

        try:
            dm = await self.parent_view.ctx.author.create_dm()
            dm_embed = discord.Embed(
                title="Hit Denied",
                description=(
                    f"> **Target:** `{self.parent_view.username}`\n"
                    f"> **Bounty:** `{self.parent_view.bounty}` in-game money\n"
                    f"> **Denial Reason:** {self.reason.value}"
                ),
                color=BLANK_COLOR,
            )
            dm_embed.set_author(name="California State Roleplay", icon_url=CSRP_ICON)
            brand_footer(dm_embed)
            await dm.send(embed=dm_embed)
        except discord.Forbidden:
            pass

        log_channel = interaction.client.get_channel(1361900183016706200)
        if log_channel:
            embed_value = (
                f"> **Denied By:** {interaction.user.mention}\n"
                f"> **Denial Reason:** {self.reason.value}"
            )
            if self.parent_view.proofURL:
                embed_value += f"\n> **Proof:** [Attachment]({self.parent_view.proofURL})"
            log_embed = discord.Embed(
                title="Hit Denied",
                description=embed_description(
                    (
                        f"> **Placed By:** {self.parent_view.ctx.author.mention}\n"
                        f"> **Target:** `{self.parent_view.username}`\n"
                        f"> **Bounty:** `{self.parent_view.bounty}` in-game money\n"
                        f"> **Reason:** {self.parent_view.reason}"
                    ),
                    embed_value,
                ),
                color=BLANK_COLOR,
            )
            log_embed.set_author(name="CSRP Utilities", icon_url=CSRP_ICON)
            if self.parent_view.ctx.author.display_avatar:
                log_embed.set_thumbnail(url=self.parent_view.ctx.author.display_avatar.url)
            if self.parent_view.proofURL:
                log_embed.set_image(url=self.parent_view.proofURL)
            brand_footer(log_embed)
            await log_channel.send(embed=log_embed)

        await interaction.response.send_message(embed=success_embed("Hit Denied", "The hit has been denied."), ephemeral=True)


class HitRequestView(discord.ui.View):
    def __init__(self, ctx, username, bounty, reason, proof):
        super().__init__(timeout=None)
        self.ctx = ctx
        self.username = username
        self.bounty = bounty
        self.reason = reason
        self.proofURL = proof

    @discord.ui.button(label="Accept", style=discord.ButtonStyle.green, custom_id="hit_accept")
    async def accept_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            with open(active_hits, "r") as file:
                hits = json.load(file)
        except (FileNotFoundError, json.JSONDecodeError):
            hits = []

        hit_entry = {
            "placed_by": self.ctx.author.id,
            "target": self.username,
            "bounty": self.bounty,
            "reason": self.reason,
            "accepted_by": interaction.user.id,
        }
        hits.append(hit_entry)
        with open(active_hits, "w") as file:
            json.dump(hits, file, indent=4)

        log_channel = interaction.client.get_channel(1361900183016706200)
        if log_channel:
            log_description = (
                f"> **Placed By:** {self.ctx.author.mention}\n"
                f"> **Target:** `{self.username}`\n"
                f"> **Bounty:** `{self.bounty}` in-game money\n"
                f"> **Accepted By:** {interaction.user.mention}\n"
                f"> **Reason:** {self.reason}"
            )
            if self.proofURL:
                log_description += f"\n\n> **Proof:** [Attachment]({self.proofURL})"
            log_embed = discord.Embed(
                title="Hit Accepted",
                description=log_description,
                color=BLANK_COLOR,
            )
            log_embed.set_author(name="CSRP Utilities", icon_url=CSRP_ICON)
            if self.ctx.author.display_avatar:
                log_embed.set_thumbnail(url=self.ctx.author.display_avatar.url)
            if self.proofURL:
                log_embed.set_image(url=self.proofURL)
            brand_footer(log_embed)
            await log_channel.send(embed=log_embed)

        embed = discord.Embed(
            title="Hit Accepted",
            description=(
                f"> **Placed By:** {self.ctx.author.mention}\n"
                f"> **Target:** `{self.username}`\n"
                f"> **Bounty:** `{self.bounty}` in-game money\n"
                f"> **Accepted By:** {interaction.user.mention}\n"
                f"> **Reason:** {self.reason}"
            ),
            color=BLANK_COLOR,
        )
        embed.set_author(name="CSRP Utilities", icon_url=CSRP_ICON)
        brand_footer(embed)
        await interaction.message.edit(embed=embed, view=None)
        await interaction.response.send_message(embed=success_embed("Hit Accepted", "The hit has been accepted."), ephemeral=True)

        try:
            dm = await self.ctx.author.create_dm()
            dm_embed = discord.Embed(
                title="Hit Accepted",
                description=(
                    f"> **Target:** `{self.username}`\n"
                    f"> **Bounty:** `{self.bounty}` in-game money\n"
                    f"> **Reason:** {self.reason}"
                ),
                color=BLANK_COLOR,
            )
            dm_embed.set_author(name="California State Roleplay", icon_url=CSRP_ICON)
            brand_footer(dm_embed)
            await dm.send(embed=dm_embed)
        except discord.Forbidden:
            pass

    @discord.ui.button(label="Deny", style=discord.ButtonStyle.danger, custom_id="hit_deny")
    async def deny_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(DenyHitModal(self, interaction))


class Hits(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.hybrid_group(name="hit", description="Hit related commands.")
    async def hit(self, ctx: commands.Context):
        if ctx.invoked_subcommand is None:
            embed = discord.Embed(
                title="Hit Commands",
                description=(
                    "> `/hit place` — Place a bounty on someone\n"
                    "> `/hit active` — View all active hits\n"
                    "> `/hit complete` — Mark a hit as completed"
                ),
                color=BLANK_COLOR,
            )
            embed.set_author(name=ctx.guild.name, icon_url=ctx.guild.icon.url if ctx.guild.icon else "")
            embed.set_thumbnail(url=CSRP_ICON)
            brand_footer(embed)
            await ctx.send(embed=embed)

    @hit.command(name="place", description="Place a hit on someone in-game.")
    @app_commands.describe(username="The target's ROBLOX username", bounty="The bounty amount", proof="Optional proof attachment", reason="Reason for the hit")
    async def place(self, ctx, username: str, bounty: str, proof: Optional[discord.Attachment] = None, *, reason: str):
        if BLACKLIST_ROLE_ID in [role.id for role in ctx.author.roles]:
            await ctx.send(embed=error_embed("Blacklisted", "You are blacklisted from placing hits."))
            return

        if not bounty.isdigit() or int(bounty) <= 0:
            await ctx.send(embed=error_embed("Invalid Bounty", "Bounty must be a positive number."))
            return

        bounty = int(bounty)
        if username.startswith("<@"):
            await ctx.send(embed=error_embed("Invalid Username", "You must enter the user's ROBLOX username, not a Discord mention."))
            return

        channel = self.bot.get_channel(1361904750051856645)
        description = (
            f"> **Placed By:** {ctx.author.mention}\n"
            f"> **Target:** `{username}`\n"
            f"> **Bounty:** `{bounty}` in-game money\n"
            f"> **Reason:** {reason}"
        )
        if proof:
            description += f"\n\n> **Proof:** [Attachment]({proof.url})"
        embed = discord.Embed(title="Hit Request", description=description, color=BLANK_COLOR)
        embed.set_author(name=ctx.guild.name, icon_url=ctx.guild.icon.url if ctx.guild.icon else "")
        if ctx.author.display_avatar:
            embed.set_thumbnail(url=ctx.author.display_avatar.url)
        if proof:
            embed.set_image(url=proof.url)
        brand_footer(embed)

        view = HitRequestView(ctx, username, bounty, reason, proof.url if proof else None)
        await channel.send(embed=embed, view=view)
        await ctx.send(embed=success_embed("Hit Submitted", "Hit request sent. You will be notified when it's reviewed."))

    @hit.command(name="active", description="Shows all active hits.")
    async def active(self, ctx):
        try:
            with open(active_hits, "r") as file:
                hits = json.load(file)
        except (FileNotFoundError, json.JSONDecodeError):
            hits = []

        if not hits:
            embed = discord.Embed(
                title="Active Hits",
                description="No active hits at the moment.",
                color=BLANK_COLOR,
            )
            embed.set_author(name=ctx.guild.name, icon_url=ctx.guild.icon.url if ctx.guild.icon else "")
            brand_footer(embed)
            await ctx.send(embed=embed)
            return

        per_page = 5
        pages = []
        for i in range(0, len(hits), per_page):
            chunk = hits[i:i + per_page]
            embed = discord.Embed(
                title="Active Hits",
                description="\n\n".join(
                    (
                        f"**Hit #{idx}**\n"
                        f"> **Target:** `{hit_data['target']}`\n"
                        f"> **Bounty:** `{hit_data['bounty']}`\n"
                        f"> **Reason:** {hit_data['reason']}\n"
                        f"> **Placed By:** <@{hit_data['placed_by']}>"
                    )
                    for idx, hit_data in enumerate(chunk, start=i + 1)
                ),
                color=BLANK_COLOR,
            )
            embed.set_author(name=ctx.guild.name, icon_url=ctx.guild.icon.url if ctx.guild.icon else "")
            brand_footer(embed)
            pages.append(embed)

        if len(pages) == 1:
            await ctx.send(embed=pages[0])
        else:
            view = PaginatorView(pages, ctx.author)
            msg = await ctx.send(embed=pages[0], view=view)
            view.message = msg

    @hit.command(name="complete", description="Mark a hit as completed.")
    @app_commands.describe(target="The target's in-game name")
    async def complete(self, ctx, target: str):
        try:
            with open(active_hits, "r") as file:
                hits = json.load(file)
        except (FileNotFoundError, json.JSONDecodeError):
            hits = []

        hit_data = next((hit for hit in hits if hit["target"].lower() == target.lower()), None)

        if not hit_data:
            await ctx.send(embed=error_embed("Hit Not Found", f"No active hit found for **{target}**."))
            return

        updated_hits = [hit for hit in hits if hit != hit_data]
        with open(active_hits, "w") as file:
            json.dump(updated_hits, file, indent=4)

        await ctx.send(embed=success_embed("Hit Completed", f"Hit on **{target}** has been completed."))

        log_channel = self.bot.get_channel(1361900183016706200)
        if log_channel:
            log_embed = discord.Embed(
                title="Hit Completed",
                description=(
                    f"> **Placed By:** <@{hit_data['placed_by']}>\n"
                    f"> **Target:** `{hit_data['target']}`\n"
                    f"> **Bounty:** `{hit_data['bounty']}` in-game money\n"
                    f"> **Reason:** {hit_data['reason']}\n"
                    f"> **Completed By:** {ctx.author.mention}"
                ),
                color=BLANK_COLOR,
            )
            log_embed.set_author(name="CSRP Utilities", icon_url=CSRP_ICON)
            if ctx.author.display_avatar:
                log_embed.set_thumbnail(url=ctx.author.display_avatar.url)
            brand_footer(log_embed)
            await log_channel.send(embed=log_embed)

        try:
            user = await self.bot.fetch_user(hit_data['placed_by'])
            dm_embed = discord.Embed(
                title="Hit Completed",
                description=(
                    f"> **Target:** `{hit_data['target']}`\n"
                    f"> **Bounty:** `{hit_data['bounty']}` in-game money\n"
                    f"> **Completed By:** {ctx.author.mention}\n"
                    f"> **Reason:** {hit_data['reason']}"
                ),
                color=BLANK_COLOR,
            )
            dm_embed.set_author(name="California State Roleplay", icon_url=CSRP_ICON)
            brand_footer(dm_embed)
            await user.send(embed=dm_embed)
        except Exception:
            pass


async def setup(bot):
    await bot.add_cog(Hits(bot))
