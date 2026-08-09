import json
import os
import re
import time

import discord
from discord.ext import commands, tasks
from discord import app_commands

from config import (
    ROLE_TRAINING_INSTRUCTOR, ROLE_TRIAL_MODERATOR, ROLE_PHASE_3,
    ROLE_JUNIOR_MODERATOR, ROLE_MODERATOR, ROLE_STAFF_TEAM,
    KEY_HEADERS, BASE_DIR, is_training_instructor,
)
from cogs.helpers import (
    Colors, BLANK_COLOR, CSRP_ICON, CSRP_EMOJI, CHECK, CROSS, PENDING,
    success_embed, error_embed, info_embed, brand_footer, embed_description,
    api_get, ConfirmView, generalised_interaction_check_failure,
)


ROLE_TRAINING_PURGE = 1337050526503931987
ROLE_PURGE_TRAINEE_MOD = 1512533364257587291
ROLE_PURGE_PHASE_3 = 1451267283954700428

MESSAGE_LINK_RE = re.compile(
    r"https?://(?:ptb\.|canary\.)?discord(?:app)?\.com/channels/(\d+)/(\d+)/(\d+)"
)

CSRP_GUILD_ID = 965829463512330260
TRAINEE_WELCOME_CHANNEL = 965844307250651137
TRAINEE_DATA_FILE = os.path.join(str(BASE_DIR), "trainee_tracking.json")

TRAINEE_REMIND_AFTER = 7 * 86400    # halfway reminder
TRAINEE_REMOVE_AFTER = 14 * 86400   # removal deadline
TRAINEE_ROLE_GRACE = 86400          # time allowed for trainee roles to be assigned after the ping

REAPPLY_CHANNEL_LINK = "https://discord.com/channels/965829463512330260/1489997682645663936"


def _load_trainees() -> dict:
    try:
        with open(TRAINEE_DATA_FILE, "r") as f:
            data = json.load(f)
    except (FileNotFoundError, ValueError):
        data = {}
    return data if isinstance(data, dict) else {}


def _trainee_welcome_embed() -> discord.Embed:
    embed = discord.Embed(
        title="CSRP | Training Welcome",
        description=(
            "Welcome to the CSRP Staff Team! Below is all the information you'll need to know during your training phase.\n"
            "## Training Phases\n"
            "- `Phase 1`  **- Verbal Training**\n"
            "You will be walked through everything you need to know as a staff member. This includes how to manage your shift using /shift manage, "
            "how to handle modcalls, chaotic situations like raids or mass RDM, how to use the peace timer, how to log punishments using /logs create, "
            "how to perform discord checks using .erlc check, and general rules like using 5 letter commands to avoid accidents.\n"
            "`Phase 2`  **- Driving**\n"
            "You will be evaluated on your driving skills while patrolling the map. You are expected to use Stage 1 ELS while patrolling and Stage 3 ELS "
            "when pulling someone over. You must avoid GTA driving and pull over any booster restricted vehicles to verify the driver is a booster.\n"
            "`Phase 3`  **- Moderation**\n"
            "You will handle live modcalls independently for 20-30 minutes while your instructor observes. You are graded on your professionalism, "
            "spelling and grammar (SPaG), and moderation skills. The passing grade is 25 out of 30.\n"
            "\n"
            "⚠️ You'll have **2 weeks** to complete your training. If not completed by then, you'll be removed from the training program. "
            "We'll remind you halfway through the 2 weeks.\n"
            "\n"
            "If you need assistance, contact any member of the training oversight team. Good luck!"
        ),
        color=BLANK_COLOR,
    )
    embed.add_field(
        name="Helpful Commands & Channels",
        value=(
            "https://discord.com/channels/965829463512330260/1455336489423736872\n"
            "https://discord.com/channels/965829463512330260/1454215586094645415\n"
            "`/training request`"
        ),
        inline=False,
    )
    embed.set_thumbnail(url=CSRP_ICON)
    brand_footer(embed)
    return embed


def _trainee_reminder_embed(deadline_ts: int) -> discord.Embed:
    embed = discord.Embed(
        title="CSRP | Training Reminder",
        description=(
            "You're halfway through your training window! You have **1 week** remaining to complete your training.\n"
            "\n"
            f"If your training is not completed by <t:{deadline_ts}:F> (<t:{deadline_ts}:R>), you'll be removed from the training program.\n"
            "\n"
            "If you need assistance, contact any member of the training oversight team."
        ),
        color=BLANK_COLOR,
    )
    embed.set_thumbnail(url=CSRP_ICON)
    brand_footer(embed)
    return embed


def _trainee_removal_embed() -> discord.Embed:
    embed = discord.Embed(
        title="CSRP | Training Removal",
        description=(
            "You've been removed from the training program because your training was not completed within **2 weeks**.\n"
            "\n"
            f"If you wish to apply again, you can do so in {REAPPLY_CHANNEL_LINK}."
        ),
        color=BLANK_COLOR,
    )
    embed.set_thumbnail(url=CSRP_ICON)
    brand_footer(embed)
    return embed


class Training(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.trainees = _load_trainees()
        # trainees: {user_id_str: {"started": ts, "reminder_sent": bool, "guild_id": int}}

    async def cog_load(self):
        self.trainee_deadline_loop.start()

    async def cog_unload(self):
        self.trainee_deadline_loop.cancel()

    def _save_trainees(self):
        try:
            with open(TRAINEE_DATA_FILE, "w") as f:
                json.dump(self.trainees, f, indent=4)
        except OSError:
            pass

    @commands.Cog.listener("on_message")
    async def trainee_welcome_listener(self, message: discord.Message):
        if message.author.bot or message.channel.id != TRAINEE_WELCOME_CHANNEL:
            return

        changed = False
        for user in message.mentions:
            if user.bot or str(user.id) in self.trainees:
                continue
            try:
                await user.send(embed=_trainee_welcome_embed())
            except discord.HTTPException:
                pass  # DMs closed; still track them so the deadline applies
            self.trainees[str(user.id)] = {
                "started": time.time(),
                "reminder_sent": False,
                "guild_id": message.guild.id if message.guild else CSRP_GUILD_ID,
            }
            changed = True
        if changed:
            self._save_trainees()

    @tasks.loop(minutes=30)
    async def trainee_deadline_loop(self):
        now = time.time()
        changed = False
        for user_id, entry in list(self.trainees.items()):
            elapsed = now - entry.get("started", now)
            guild = self.bot.get_guild(entry.get("guild_id", CSRP_GUILD_ID))
            if guild is None:
                continue

            member = guild.get_member(int(user_id))
            if member is None:
                try:
                    member = await guild.fetch_member(int(user_id))
                except discord.NotFound:
                    member = None
                except discord.HTTPException:
                    continue  # transient error, retry next cycle
            if member is None:
                self.trainees.pop(user_id, None)  # left the server
                changed = True
                continue

            member_role_ids = {r.id for r in member.roles}
            trainee_roles_held = member_role_ids & {ROLE_PURGE_PHASE_3, ROLE_PURGE_TRAINEE_MOD}
            if not trainee_roles_held and elapsed > TRAINEE_ROLE_GRACE:
                self.trainees.pop(user_id, None)  # passed training or removed manually
                changed = True
                continue

            if elapsed >= TRAINEE_REMOVE_AFTER:
                try:
                    await member.remove_roles(
                        *(discord.Object(id=rid) for rid in trainee_roles_held),
                        reason="Automatic trainee purge: training not completed within 2 weeks",
                    )
                except discord.HTTPException:
                    continue  # retry next cycle
                try:
                    await member.send(embed=_trainee_removal_embed())
                except discord.HTTPException:
                    pass
                self.trainees.pop(user_id, None)
                changed = True
            elif elapsed >= TRAINEE_REMIND_AFTER and not entry.get("reminder_sent"):
                deadline_ts = int(entry.get("started", now) + TRAINEE_REMOVE_AFTER)
                try:
                    await member.send(embed=_trainee_reminder_embed(deadline_ts))
                except discord.HTTPException:
                    pass
                entry["reminder_sent"] = True
                changed = True
        if changed:
            self._save_trainees()

    @trainee_deadline_loop.before_loop
    async def before_trainee_deadline_loop(self):
        await self.bot.wait_until_ready()

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
                    "> `/training purge` — Purge Trainee Mod & Phase 3 roles\n"
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

    @training_group.command(name="purge", description="Remove Trainee Mod and Phase 3 roles from everyone except exempted users.")
    @commands.guild_only()
    @commands.has_role(ROLE_TRAINING_PURGE)
    @app_commands.describe(purge_message_link="Link to a message containing mentions/IDs of users exempt from the purge.")
    async def purge(self, ctx: commands.Context, purge_message_link: str):
        await ctx.defer()

        match = MESSAGE_LINK_RE.search(purge_message_link)
        if not match:
            await ctx.send(embed=error_embed("Invalid Link", "That does not look like a valid Discord message link."))
            return

        _, channel_id, message_id = (int(g) for g in match.groups())
        channel = self.bot.get_channel(channel_id)
        if channel is None:
            try:
                channel = await self.bot.fetch_channel(channel_id)
            except discord.HTTPException:
                channel = None
        if channel is None:
            await ctx.send(embed=error_embed("Channel Not Found", "I cannot access the channel in that message link."))
            return

        try:
            purge_message = await channel.fetch_message(message_id)
        except discord.NotFound:
            await ctx.send(embed=error_embed("Message Not Found", "I could not find the message in that link."))
            return
        except discord.HTTPException as e:
            await ctx.send(embed=error_embed("Fetch Failed", f"Failed to fetch the purge message. (`{e.status}`)"))
            return

        exempt_ids = {int(uid) for uid in re.findall(r"\d{15,20}", purge_message.content)}
        exempt_ids.update(u.id for u in purge_message.mentions)

        trainee_role = ctx.guild.get_role(ROLE_PURGE_TRAINEE_MOD)
        phase3_role = ctx.guild.get_role(ROLE_PURGE_PHASE_3)
        if trainee_role is None and phase3_role is None:
            await ctx.send(embed=error_embed("Roles Not Found", "Neither the Trainee Mod nor the Phase 3 role exists in this server."))
            return

        targets: dict[int, discord.Member] = {}
        for role in (trainee_role, phase3_role):
            if role is None:
                continue
            for member in role.members:
                if member.id not in exempt_ids:
                    targets[member.id] = member

        exempt_mentions = ", ".join(f"<@{uid}>" for uid in exempt_ids) or "None"
        if not targets:
            await ctx.send(embed=info_embed("Nothing To Purge", f"No members hold the Trainee Mod or Phase 3 roles outside the exemptions.\n\n> **Exempt:** {exempt_mentions}"))
            return

        confirm_embed = discord.Embed(
            title="Confirm Training Purge",
            description=embed_description(
                (
                    f"> **Members Affected:** `{len(targets)}`\n"
                    f"> **Roles Removed:** Trainee Mod, Phase 3"
                ),
                f"> **Exempt:** {exempt_mentions}",
            ),
            color=BLANK_COLOR,
        )
        confirm_embed.set_author(name=ctx.guild.name, icon_url=ctx.guild.icon.url if ctx.guild.icon else "")
        brand_footer(confirm_embed)
        view = ConfirmView(ctx.author)
        view.message = await ctx.send(embed=confirm_embed, view=view)
        await view.wait()
        if not view.value:
            await ctx.send(embed=info_embed("Purge Cancelled", "No roles were removed."))
            return

        purged, failed = 0, 0
        reason = f"Training purge by {ctx.author} ({ctx.author.id})"
        for member in targets.values():
            roles_to_remove = [r for r in (trainee_role, phase3_role) if r is not None and r in member.roles]
            if not roles_to_remove:
                continue
            try:
                await member.remove_roles(*roles_to_remove, reason=reason)
                purged += 1
            except discord.HTTPException:
                failed += 1

        result_embed = discord.Embed(
            title="Training Purge Complete",
            description=embed_description(
                (
                    f"> **Members Purged:** `{purged}`\n"
                    f"> **Failed:** `{failed}`\n"
                    f"> **Roles Removed:** Trainee Mod, Phase 3"
                ),
                f"> **Exempt:** {exempt_mentions}",
                f"> **Purged By:** {ctx.author.mention}",
            ),
            color=BLANK_COLOR,
        )
        result_embed.set_author(name=ctx.guild.name, icon_url=ctx.guild.icon.url if ctx.guild.icon else "")
        brand_footer(result_embed)
        await ctx.send(embed=result_embed)

    @training_group.command(name="info", description="Get information about the training server.")
    async def info(self, ctx: commands.Context):
        await ctx.defer()
        try:
            status, data = await api_get(
                "https://api.erlc.gg/v1/server",
                headers=KEY_HEADERS,
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
