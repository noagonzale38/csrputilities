import discord
from discord.ext import commands
from discord import app_commands

from config import (
    ROLE_TRAINING_INSTRUCTOR, ROLE_TRIAL_MODERATOR, ROLE_PHASE_3,
    ROLE_JUNIOR_MODERATOR, ROLE_MODERATOR, ROLE_STAFF_TEAM,
    SERVER_KEY, is_training_instructor,
)
from cogs.helpers import (
    Colors, BLANK_COLOR, CSRP_ICON, CSRP_EMOJI, CHECK, CROSS, PENDING,
    success_embed, error_embed, info_embed, brand_footer, embed_description,
    api_get, ConfirmView, generalised_interaction_check_failure,
)


class Training(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.hybrid_command(name="pass", description="Pass a user's Phase 3 Training.")
    @is_training_instructor()
    async def pass_cmd(self, ctx, member: discord.Member):
        required = {ROLE_PHASE_3, ROLE_TRIAL_MODERATOR}
        member_role_ids = {r.id for r in member.roles}
        if not required.issubset(member_role_ids):
            await ctx.send(embed=error_embed("Missing Roles", "The specified member does not have both the Phase 3 and Trial Moderator roles."))
            return

        try:
            reason = f"Passed Phase 3 by {ctx.author} via /pass"
            await member.remove_roles(discord.Object(id=ROLE_TRIAL_MODERATOR), discord.Object(id=ROLE_PHASE_3), reason=reason)
            await member.add_roles(discord.Object(id=ROLE_JUNIOR_MODERATOR), discord.Object(id=ROLE_MODERATOR), discord.Object(id=ROLE_STAFF_TEAM), reason=reason)

            embed = discord.Embed(
                title="User Passed",
                description=embed_description(
                    (
                        f"> **User:** {member.mention}\n"
                        f"> **Result:** Passed\n"
                        f"> **Promotion:** Junior Moderator"
                    ),
                    f"> **Evaluated By:** {ctx.author.mention}",
                ),
                color=BLANK_COLOR,
            )
            embed.set_author(name=ctx.guild.name, icon_url=ctx.guild.icon.url if ctx.guild.icon else "")
            embed.set_thumbnail(url=member.display_avatar.url)
            brand_footer(embed)
            await ctx.send(embed=embed)
        except discord.Forbidden:
            await ctx.send(embed=error_embed("Missing Permissions", "I do not have permission to modify roles."))
        except discord.HTTPException as e:
            await ctx.send(embed=error_embed("Role Update Failed", f"An error occurred while modifying roles. (`{e.status}`)"))

    @commands.hybrid_command(name="fail", description="Fail a user's Phase 3 Training.")
    @is_training_instructor()
    async def fail(self, ctx, member: discord.Member):
        author = ctx.author
        has_phase3 = discord.utils.get(member.roles, id=ROLE_PHASE_3) is not None
        has_trial = discord.utils.get(member.roles, id=ROLE_TRIAL_MODERATOR) is not None
        if not (has_phase3 and has_trial):
            await ctx.reply(embed=error_embed("Missing Roles", "The specified member does not have both the Phase 3 and Trial Moderator roles."))
            return

        class ConfirmFailView(discord.ui.View):
            def __init__(self_view, *, timeout=60):
                super().__init__(timeout=timeout)
                self_view.msg = None

            async def interaction_check(self_view, interaction):
                if interaction.user.id != author.id:
                    await generalised_interaction_check_failure(interaction)
                    return False
                return True

            async def disable_all(self_view, interaction):
                for child in self_view.children:
                    if isinstance(child, discord.ui.Button):
                        child.disabled = True
                try:
                    if self_view.msg:
                        await self_view.msg.edit(view=self_view)
                except Exception:
                    pass

            @discord.ui.button(label="First Failure", style=discord.ButtonStyle.primary)
            async def no_button(self_view, interaction, button):
                await interaction.response.defer()
                embed = discord.Embed(
                    title="Failure Recorded",
                    description=embed_description(
                        (
                            f"> **User:** {member.mention}\n"
                            f"> **Result:** Failed (First Attempt)\n"
                            f"> **Roles Removed:** None"
                        ),
                        f"> **Evaluated By:** {author.mention}",
                    ),
                    color=BLANK_COLOR,
                )
                embed.set_author(name=ctx.guild.name, icon_url=ctx.guild.icon.url if ctx.guild.icon else "")
                embed.set_thumbnail(url=member.display_avatar.url)
                brand_footer(embed)
                await ctx.channel.send(embed=embed)
                await self_view.disable_all(interaction)

            @discord.ui.button(label="Repeat Failure (Remove Roles)", style=discord.ButtonStyle.danger)
            async def yes_button(self_view, interaction, button):
                await interaction.response.defer()
                try:
                    await member.remove_roles(
                        discord.Object(id=ROLE_TRIAL_MODERATOR),
                        discord.Object(id=ROLE_PHASE_3),
                        reason=f"Failed Phase 3 by {author} ({author.id})",
                    )
                    embed = discord.Embed(
                        title="Failure Recorded",
                        description=embed_description(
                            (
                                f"> **User:** {member.mention}\n"
                                f"> **Result:** Failed (Repeat)\n"
                                f"> **Roles Removed:** Trial Moderator, Phase 3"
                            ),
                            f"> **Evaluated By:** {author.mention}",
                        ),
                        color=BLANK_COLOR,
                    )
                    embed.set_author(name=ctx.guild.name, icon_url=ctx.guild.icon.url if ctx.guild.icon else "")
                    embed.set_thumbnail(url=member.display_avatar.url)
                    brand_footer(embed)
                    await ctx.channel.send(embed=embed)
                except discord.Forbidden:
                    await ctx.channel.send(embed=error_embed("Missing Permissions", "I do not have permission to modify roles."))
                except discord.HTTPException as e:
                    await ctx.channel.send(embed=error_embed("Role Update Failed", f"Role update failed: `{e}`"))
                finally:
                    await self_view.disable_all(interaction)

            async def on_timeout(self_view):
                for child in self_view.children:
                    if isinstance(child, discord.ui.Button):
                        child.disabled = True
                if self_view.msg:
                    try:
                        await self_view.msg.edit(view=self_view)
                    except Exception:
                        pass

        confirm_embed = discord.Embed(
            title="Confirm Training Failure",
            description=(
                f"Has **{member.display_name}** failed their Phase 3 training before?\n\n"
                "> **First Failure** — Record without removing roles\n"
                "> **Repeat Failure** — Record and remove Trial Moderator roles"
            ),
            color=BLANK_COLOR,
        )
        confirm_embed.set_author(name=ctx.guild.name, icon_url=ctx.guild.icon.url if ctx.guild.icon else "")
        brand_footer(confirm_embed)
        view = ConfirmFailView()
        msg = await ctx.reply(embed=confirm_embed, view=view)
        view.msg = msg

    @commands.hybrid_command(name="training-result", description="Post a training result for a trial moderator.")
    @commands.guild_only()
    @commands.has_role("Training Instructor")
    async def training_result(self, ctx, user: discord.Member, result: str, quiz_score: int, notes: str):
        TRAINING_CHANNEL_ID = 1208190864623665152
        TRIALMOD_ROLE_ID = 1142431349622452334
        STAFF_TEAM_ROLE_ID = 968852438922715176
        MODERATOR_BASE_ROLE_ID = 981595679505940490
        JUNIOR_MOD_ROLE_ID = 1307101011126648902

        if ctx.channel.id != TRAINING_CHANNEL_ID:
            await ctx.send(embed=error_embed("Wrong Channel", "This command can only be used in the designated channel."), ephemeral=True)
            return

        if ROLE_TRAINING_INSTRUCTOR not in [role.id for role in ctx.author.roles]:
            await ctx.send(embed=error_embed("Missing Role", "You must be a training instructor to use this command."), ephemeral=True)
            return

        if TRIALMOD_ROLE_ID not in [role.id for role in user.roles]:
            await ctx.send(embed=error_embed("Invalid User", "The selected user must have the **Trial Moderator** role."), ephemeral=True)
            return

        result = result.lower()
        if result not in ["passed", "failed"]:
            await ctx.send(embed=error_embed("Invalid Result", "Invalid result. Use `passed` or `failed`."), ephemeral=True)
            return

        is_passed = result == "passed"
        embed = discord.Embed(
            title="Training Result",
            description=embed_description(
                (
                    f"> **User:** {user.mention}\n"
                    f"> **Result:** {'Passed' if is_passed else 'Failed'}\n"
                    f"> **Quiz Score:** `{quiz_score}/10`"
                ),
                f"> **Notes:** {notes}",
                f"> **Evaluated By:** {ctx.author.mention}",
            ),
            color=BLANK_COLOR,
        )
        embed.set_author(name=ctx.guild.name, icon_url=ctx.guild.icon.url if ctx.guild.icon else "")
        embed.set_thumbnail(url=user.display_avatar.url)
        brand_footer(embed)

        if is_passed:
            staff_team_role = ctx.guild.get_role(STAFF_TEAM_ROLE_ID)
            moderator_base_role = ctx.guild.get_role(MODERATOR_BASE_ROLE_ID)
            junior_mod_role = ctx.guild.get_role(JUNIOR_MOD_ROLE_ID)
            trial_mod_role = ctx.guild.get_role(TRIALMOD_ROLE_ID)
            try:
                await user.add_roles(staff_team_role, moderator_base_role, junior_mod_role)
                await user.remove_roles(trial_mod_role)
            except discord.Forbidden:
                await ctx.send(embed=error_embed("Missing Permissions", "I do not have permission to edit this user's roles."))

        await ctx.send(f"{user.mention}", embed=embed)

    @commands.hybrid_group(name="training", description="Training Server Integration")
    async def training_group(self, ctx: commands.Context):
        if ctx.invoked_subcommand is None:
            embed = discord.Embed(
                title="Training Commands",
                description=(
                    "> `/training info` — Get training server info\n"
                    "> `/pass` — Pass a user's Phase 3 Training\n"
                    "> `/fail` — Fail a user's Phase 3 Training\n"
                    "> `/training-result` — Post a training result"
                ),
                color=BLANK_COLOR,
            )
            embed.set_author(name=ctx.guild.name, icon_url=ctx.guild.icon.url if ctx.guild.icon else "")
            embed.set_thumbnail(url=CSRP_ICON)
            brand_footer(embed)
            await ctx.send(embed=embed)

    @training_group.command(name="info", description="Get information about the training server.")
    async def info(self, ctx: commands.Context):
        await ctx.defer()
        try:
            status, data = await api_get(
                "https://api.policeroleplay.community/v1/server",
                headers={"Server-Key": SERVER_KEY},
            )
            if status != 200 or not data:
                await ctx.send(embed=error_embed("Fetch Failed", f"Failed to fetch server info. Status: `{status}`"))
                return

            embed = discord.Embed(
                title="Training Server Info",
                description=(
                    f"> **Server Name:** `{data.get('Name', 'N/A')}`\n"
                    f"> **Players:** `{data.get('CurrentPlayers', 0)}/{data.get('MaxPlayers', 0)}`\n"
                    f"> **Join Key:** `{data.get('JoinKey', 'N/A')}`"
                ),
                color=BLANK_COLOR,
            )
            embed.set_author(name=ctx.guild.name, icon_url=ctx.guild.icon.url if ctx.guild.icon else "")
            embed.set_thumbnail(url=CSRP_ICON)
            brand_footer(embed)
            await ctx.send(embed=embed)
        except Exception as e:
            await ctx.send(embed=error_embed("Connection Error", f"Connection error: `{e}`"))


async def setup(bot):
    await bot.add_cog(Training(bot))
