import discord
from discord.ext import commands
from discord import app_commands
from discord.ui import View, Modal, TextInput
import asyncio
import random
import re
import os
import json
import tempfile
import pyttsx3
import aiohttp
from pathlib import Path

from config import afk_file, ALLOWED_ROLE_ID
from cogs.helpers import (
    Colors, BLANK_COLOR, CSRP_ICON, CHECK, CROSS,
    success_embed, error_embed, info_embed, brand_footer, embed_description,
    generalised_interaction_check_failure,
)

trivia_questions = [
    {"question": "What is the capital of France?", "answer": "paris"},
    {"question": "What is 5 + 7?", "answer": "12"},
    {"question": "Who wrote 'Hamlet'?", "answer": "shakespeare"},
    {"question": "What is the largest planet in our solar system?", "answer": "jupiter"},
    {"question": "What is the chemical symbol for water?", "answer": "h2o"},
    {"question": "What year did World War II end?", "answer": "1945"},
    {"question": "Who painted the Mona Lisa?", "answer": "da vinci"},
    {"question": "What is the tallest mountain in the world?", "answer": "everest"},
    {"question": "What is the square root of 64?", "answer": "8"},
    {"question": "What is the capital city of Japan?", "answer": "tokyo"},
    {"question": "Which planet is known as the Red Planet?", "answer": "mars"},
    {"question": "What is the largest ocean on Earth?", "answer": "pacific"},
    {"question": "Who developed the theory of relativity?", "answer": "einstein"},
    {"question": "What is the main ingredient in guacamole?", "answer": "avocado"},
    {"question": "Who wrote 'Pride and Prejudice'?", "answer": "austen"},
    {"question": "How many continents are there?", "answer": "7"},
    {"question": "What is the capital of Italy?", "answer": "rome"},
    {"question": "What is the smallest prime number?", "answer": "2"},
    {"question": "Who directed the movie 'Titanic'?", "answer": "cameron"},
    {"question": "What is the freezing point of water in Celsius?", "answer": "0"},
    {"question": "What is the national animal of Canada?", "answer": "beaver"},
    {"question": "Which element has the atomic number 1?", "answer": "hydrogen"},
    {"question": "What is the longest river in the world?", "answer": "nile"},
    {"question": "Who is the author of '1984'?", "answer": "orwell"},
    {"question": "What is the capital of Germany?", "answer": "berlin"},
    {"question": "What is the most abundant gas in Earth's atmosphere?", "answer": "nitrogen"},
    {"question": "What is the largest mammal?", "answer": "blue whale"},
    {"question": "How many sides does a hexagon have?", "answer": "6"},
    {"question": "Who was the first president of the United States?", "answer": "washington"},
    {"question": "What is the capital of Australia?", "answer": "canberra"},
    {"question": "What is 9 x 8?", "answer": "72"},
    {"question": "Who discovered penicillin?", "answer": "fleming"},
    {"question": "What is the hottest planet in the solar system?", "answer": "venus"},
    {"question": "What is the chemical symbol for gold?", "answer": "au"},
    {"question": "Who wrote 'The Odyssey'?", "answer": "homer"},
    {"question": "How many colors are in a rainbow?", "answer": "7"},
    {"question": "What is the capital of Canada?", "answer": "ottawa"},
    {"question": "What is 15 divided by 3?", "answer": "5"},
    {"question": "Who invented the telephone?", "answer": "bell"},
    {"question": "What is the largest desert in the world?", "answer": "sahara"},
    {"question": "What is the capital of Russia?", "answer": "moscow"},
    {"question": "What is the most spoken language in the world?", "answer": "english"},
    {"question": "What is the main ingredient in sushi?", "answer": "rice"},
    {"question": "Who wrote 'To Kill a Mockingbird'?", "answer": "lee"},
    {"question": "What is the capital of Egypt?", "answer": "cairo"},
    {"question": "How many days are in a leap year?", "answer": "366"},
    {"question": "What is the smallest country in the world?", "answer": "vatican city"},
    {"question": "What is the most popular sport in the world?", "answer": "soccer"},
    {"question": "What is the chemical symbol for oxygen?", "answer": "o"},
    {"question": "What is the capital of Mexico?", "answer": "mexico city"},
    {"question": "What is the boiling point of water in Celsius?", "answer": "100"},
    {"question": "Who painted 'Starry Night'?", "answer": "van gogh"},
    {"question": "What is the hardest natural substance?", "answer": "diamond"},
    {"question": "What is 20% of 50?", "answer": "10"},
    {"question": "Who was the first man to step on the moon?", "answer": "armstrong"},
    {"question": "What is the capital of Brazil?", "answer": "brasilia"},
    {"question": "What is the national sport of Japan?", "answer": "sumo"},
    {"question": "What is the smallest planet in our solar system?", "answer": "mercury"},
    {"question": "What is the capital of India?", "answer": "new delhi"},
    {"question": "What is the chemical formula for table salt?", "answer": "nacl"},
    {"question": "What is the most widely consumed drink in the world after water?", "answer": "tea"},
    {"question": "What is the capital of Spain?", "answer": "madrid"},
    {"question": "What is the heaviest naturally occurring element?", "answer": "uranium"},
    {"question": "Who invented the lightbulb?", "answer": "edison"},
    {"question": "What is the fastest land animal?", "answer": "cheetah"},
    {"question": "What is the capital of China?", "answer": "beijing"},
    {"question": "What is the process by which plants make their food?", "answer": "photosynthesis"},
    {"question": "What is the capital of South Africa?", "answer": "pretoria"},
    {"question": "What is 3 cubed?", "answer": "27"},
    {"question": "Who wrote 'The Great Gatsby'?", "answer": "fitzgerald"},
    {"question": "What is the largest bird in the world?", "answer": "ostrich"},
    {"question": "What is the capital of Argentina?", "answer": "buenos aires"},
    {"question": "What is the longest bone in the human body?", "answer": "femur"},
    {"question": "What is the name of the largest rainforest in the world?", "answer": "amazon"},
    {"question": "What is the most common blood type?", "answer": "o"},
    {"question": "What is the tallest animal in the world?", "answer": "giraffe"},
    {"question": "What is the capital of the United Kingdom?", "answer": "london"},
    {"question": "What is the first element on the periodic table?", "answer": "hydrogen"},
    {"question": "What is the name of the ship that sank in 1912?", "answer": "titanic"},
    {"question": "What is the largest organ in the human body?", "answer": "skin"},
    {"question": "What is 144 divided by 12?", "answer": "12"},
    {"question": "What is the capital of Greece?", "answer": "athens"},
    {"question": "What is the coldest continent on Earth?", "answer": "antarctica"},
    {"question": "Who wrote 'Jane Eyre'?", "answer": "bronte"},
    {"question": "What is the largest island in the world?", "answer": "greenland"},
    {"question": "What is the capital of Turkey?", "answer": "ankara"},
    {"question": "What is the primary language spoken in Brazil?", "answer": "portuguese"},
]

DOG_API_URL = "https://api.thedogapi.com/v1/images/search"
CAT_API_URL = "https://api.thecatapi.com/v1/images/search"

EIGHT_BALL_RESPONSES = [
    "It is certain.", "Without a doubt.", "Yes, definitely.", "You may rely on it.",
    "As I see it, yes.", "Most likely.", "Outlook good.", "Yes.",
    "Signs point to yes.", "Reply hazy, try again.", "Ask again later.",
    "Better not tell you now.", "Cannot predict now.", "Concentrate and ask again.",
    "Don't count on it.", "My reply is no.", "My sources say no.",
    "Outlook not so good.", "Very doubtful.",
]

blacklisted_users = [740324586234708028, 736978544869113927]
SHIP_STATS_FILE = Path(__file__).resolve().parent.parent / "ship_stats.json"


def load_afk():
    with open(afk_file, "r") as f:
        return json.load(f)


def save_afk(data):
    with open(afk_file, "w") as f:
        json.dump(data, f, indent=4)


def load_ship_stats() -> dict:
    try:
        with open(SHIP_STATS_FILE, "r") as f:
            data = json.load(f)
            if isinstance(data, dict):
                return data
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    return {}


def save_ship_stats(data: dict):
    with open(SHIP_STATS_FILE, "w") as f:
        json.dump(data, f, indent=4)


def _ship_pair_key(user1_id: int, user2_id: int) -> str:
    smaller, larger = sorted((str(user1_id), str(user2_id)))
    return f"{smaller}:{larger}"


def _get_ship_pair_entry(data: dict, guild_id: int, user1: discord.abc.User, user2: discord.abc.User) -> dict:
    guild_key = str(guild_id)
    pair_key = _ship_pair_key(user1.id, user2.id)
    guild_stats = data.setdefault(guild_key, {})
    pair_stats = guild_stats.setdefault(pair_key, {
        "users": {
            str(user1.id): user1.display_name,
            str(user2.id): user2.display_name,
        },
        "count": 0,
        "total_score": 0,
    })

    users = pair_stats.setdefault("users", {})
    users[str(user1.id)] = user1.display_name
    users[str(user2.id)] = user2.display_name
    return pair_stats


def get_ship_override(guild_id: int, user1_id: int, user2_id: int) -> int | None:
    data = load_ship_stats()
    guild_key = str(guild_id)
    pair_key = _ship_pair_key(user1_id, user2_id)
    pair_stats = data.get(guild_key, {}).get(pair_key, {})
    override_score = pair_stats.get("override_score")
    if override_score is None:
        return None
    return int(override_score)


def set_ship_override(guild_id: int, user1: discord.Member, user2: discord.Member, score: int) -> None:
    data = load_ship_stats()
    pair_stats = _get_ship_pair_entry(data, guild_id, user1, user2)
    pair_stats["override_score"] = score
    save_ship_stats(data)


def get_ship_pair_stats(guild_id: int, user1_id: int, user2_id: int) -> dict:
    data = load_ship_stats()
    guild_key = str(guild_id)
    pair_key = _ship_pair_key(user1_id, user2_id)
    guild_stats = data.get(guild_key, {})
    pair_stats = guild_stats.get(pair_key, {})

    count = int(pair_stats.get("count", 0))
    total_score = int(pair_stats.get("total_score", 0))
    average_score = round(total_score / count) if count else 0

    return {
        "count": count,
        "total_score": total_score,
        "average_score": average_score,
    }


def record_ship_pair(guild_id: int, user1: discord.Member, user2: discord.Member, score: int) -> dict:
    data = load_ship_stats()
    pair_stats = _get_ship_pair_entry(data, guild_id, user1, user2)
    pair_stats["count"] = int(pair_stats.get("count", 0)) + 1
    pair_stats["total_score"] = int(pair_stats.get("total_score", 0)) + score

    save_ship_stats(data)

    count = pair_stats["count"]
    average_score = round(pair_stats["total_score"] / count)
    return {
        "count": count,
        "total_score": pair_stats["total_score"],
        "average_score": average_score,
    }


class TriviaAnswerModal(Modal):
    def __init__(self, question, callback):
        super().__init__(title="Answer Trivia Question")
        self.question = question
        self._callback = callback
        self.add_item(TextInput(label="Your Answer", placeholder="Type your answer here"))

    async def on_submit(self, interaction: discord.Interaction):
        answer = self.children[0].value.lower().strip()
        await self._callback(interaction, self.question, answer)


class Fun(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.hybrid_command(name="afk", description="Set your AFK status.")
    @app_commands.describe(reason="The reason you're going AFK")
    async def afk(self, ctx, *, reason: str = "AFK"):
        afk_data = load_afk()
        user_id = str(ctx.author.id)
        afk_data[user_id] = {"reason": reason, "name": ctx.author.display_name}
        save_afk(afk_data)
        try:
            await ctx.author.edit(nick=f"[AFK] {ctx.author.display_name}")
        except discord.Forbidden:
            pass
        embed = discord.Embed(
            title="Now AFK",
            description=f"{ctx.author.mention} is now AFK: `{reason}`",
            color=BLANK_COLOR,
        )
        embed.set_author(name=ctx.guild.name, icon_url=ctx.guild.icon.url if ctx.guild.icon else "")
        brand_footer(embed)
        await ctx.send(embed=embed)

    @commands.hybrid_command(name="trivia", description="Starts a mini trivia game!")
    async def trivia(self, ctx):
        if ctx.author.bot:
            await ctx.send(embed=error_embed("Not Allowed", "Bots cannot participate in trivia games."))
            return
        if ctx.author.id in blacklisted_users:
            await ctx.send(embed=error_embed("Blacklisted", "You are blacklisted from using trivia!"))
            return

        question = random.choice(trivia_questions)
        embed = discord.Embed(
            title="Trivia Time!",
            description=f"**{question['question']}**\n\n> Reply to this message with your answer! You have 60 seconds.",
            color=BLANK_COLOR,
        )
        embed.set_author(name=ctx.guild.name, icon_url=ctx.guild.icon.url if ctx.guild.icon else "")
        brand_footer(embed)
        trivia_message = await ctx.send(embed=embed)

        def check(msg):
            return msg.reference and msg.reference.message_id == trivia_message.id and msg.author == ctx.author

        try:
            reply = await ctx.bot.wait_for("message", timeout=60.0, check=check)
            correct_answer = question["answer"].lower()
            user_answer = reply.content.lower().strip()
            if re.search(rf'\b{re.escape(correct_answer)}\b', user_answer):
                await ctx.send(embed=success_embed("Correct!", f"**{reply.author.display_name}** is a trivia champion!"))
            else:
                await ctx.send(embed=error_embed("Incorrect", f"Sorry, **{reply.author.display_name}**. The answer was **{question['answer']}**."))
        except asyncio.TimeoutError:
            embed = discord.Embed(
                title="Time's Up",
                description=f"The correct answer was: **{question['answer']}**",
                color=BLANK_COLOR,
            )
            brand_footer(embed)
            await ctx.send(embed=embed)

    @commands.hybrid_command(name="1v1trivia", description="Challenge another player to a 1v1 trivia match!")
    @app_commands.describe(player2="The player to challenge.")
    async def trivia1v1(self, ctx, player2: discord.Member):
        player1 = ctx.author
        for player in [player1, player2]:
            if player.id in blacklisted_users:
                await ctx.send(embed=error_embed("Blacklisted", f"**{player.name}** is blacklisted from trivia!"))
                return

        embed = discord.Embed(
            title="Trivia Challenge",
            description=(
                f"**{player1.mention}** has challenged **{player2.mention}** to a trivia match!\n\n"
                f"> First to **10 rounds** wins!\n\n"
                f"Do you accept this challenge?"
            ),
            color=BLANK_COLOR,
        )
        embed.set_author(name=ctx.guild.name, icon_url=ctx.guild.icon.url if ctx.guild.icon else "")
        brand_footer(embed)
        msg = await ctx.send(embed=embed)

        class AcceptDenyView(View):
            def __init__(self_view):
                super().__init__(timeout=60)

            async def interaction_check(self_view, interaction):
                if interaction.user.id != player2.id:
                    await generalised_interaction_check_failure(interaction)
                    return False
                return True

            @discord.ui.button(label="Accept", style=discord.ButtonStyle.green)
            async def accept_button(self_view, interaction, button):
                await interaction.response.edit_message(embed=success_embed("Challenge Accepted", "The game will start shortly."), view=None)
                self_view.stop()
                await start_game()

            @discord.ui.button(label="Deny", style=discord.ButtonStyle.danger)
            async def deny_button(self_view, interaction, button):
                await interaction.response.edit_message(embed=error_embed("Challenge Denied", f"Challenge denied by {player2.mention}."), view=None)
                self_view.stop()

        async def start_game():
            scores = {player1.id: 0, player2.id: 0}
            current_round = 1
            max_rounds = 10
            game_active = True

            class TriviaQuestionView(View):
                def __init__(self_view, question, callback):
                    super().__init__(timeout=30)
                    self_view._callback = callback
                    self_view.question = question

                async def interaction_check(self_view, interaction):
                    if interaction.user.id not in [player1.id, player2.id]:
                        await generalised_interaction_check_failure(interaction)
                        return False
                    return True

                @discord.ui.button(label="Answer", style=discord.ButtonStyle.primary)
                async def answer_button(self_view, interaction, button):
                    if not game_active:
                        await interaction.response.send_message(embed=error_embed("Game Over", "The game has ended!"), ephemeral=True)
                        return
                    await interaction.response.send_modal(TriviaAnswerModal(self_view.question, self_view._callback))

            async def handle_answer(interaction, question, answer):
                nonlocal current_round, game_active
                if not game_active or current_round > max_rounds:
                    return
                player_id = interaction.user.id
                if answer == question["answer"].lower():
                    scores[player_id] += 1
                    await interaction.response.send_message(embed=success_embed("Correct!", f"{interaction.user.mention} earns 1 point."), ephemeral=True)
                else:
                    await interaction.response.send_message(embed=error_embed("Incorrect", f"The correct answer was **{question['answer']}**."), ephemeral=True)

                if current_round == max_rounds:
                    game_active = False
                    await announce_winner()
                else:
                    current_round += 1
                    new_question = random.choice(trivia_questions)
                    new_embed = discord.Embed(
                        title=f"Round {current_round}",
                        description=f"**{new_question['question']}**\n\n> Click the button below to answer.",
                        color=BLANK_COLOR,
                    )
                    new_embed.set_footer(text=f"{player1.display_name}: {scores[player1.id]} • {player2.display_name}: {scores[player2.id]}")
                    await ctx.send(embed=new_embed, view=TriviaQuestionView(new_question, handle_answer))

            async def announce_winner():
                if scores[player1.id] > scores[player2.id]:
                    winner = player1
                elif scores[player1.id] < scores[player2.id]:
                    winner = player2
                else:
                    winner = None

                if winner:
                    result_text = f"Congratulations to {winner.mention}!"
                else:
                    result_text = "It's a tie!"

                embed = discord.Embed(
                    title="Trivia Game Over!",
                    description=(
                        f"{result_text}\n\n"
                        f"**Final Scores:**\n"
                        f"> {player1.mention}: **{scores[player1.id]}**\n"
                        f"> {player2.mention}: **{scores[player2.id]}**"
                    ),
                    color=BLANK_COLOR,
                )
                embed.set_author(name=ctx.guild.name, icon_url=ctx.guild.icon.url if ctx.guild.icon else "")
                brand_footer(embed)
                await ctx.send(embed=embed)

            first_question = random.choice(trivia_questions)
            first_embed = discord.Embed(
                title=f"Round {current_round}",
                description=f"**{first_question['question']}**\n\n> Click the button below to answer.",
                color=BLANK_COLOR,
            )
            first_embed.set_footer(text=f"{player1.display_name}: 0 • {player2.display_name}: 0")
            await ctx.send(embed=first_embed, view=TriviaQuestionView(first_question, handle_answer))

        await msg.edit(view=AcceptDenyView())

    @commands.hybrid_command(name="remindme", description="Set a reminder.")
    @app_commands.describe(time="Time (e.g. 2h, 1d, 1w, 1m)", reminder_message="What to remind you about.")
    async def remindme(self, ctx, time: str, *, reminder_message: str):
        time_units = {"h": 3600, "d": 86400, "w": 604800, "m": 2592000}
        match = re.match(r"(\d+)([hdwm])", time.lower())
        if not match:
            await ctx.send(embed=error_embed("Invalid Time Format", "Use `h` (hours), `d` (days), `w` (weeks), or `m` (months)."))
            return

        value, unit = match.groups()
        seconds = int(value) * time_units[unit]

        await ctx.send(embed=success_embed("Reminder Set", f"Reminder set for **{time}**: {reminder_message}\n\nI will DM you when the time is up!"))
        await asyncio.sleep(seconds)

        try:
            embed = discord.Embed(
                title="Reminder",
                description=f"> {reminder_message}",
                color=BLANK_COLOR,
            )
            embed.set_author(name="CSRP Utilities", icon_url=CSRP_ICON)
            brand_footer(embed)
            await ctx.author.send(embed=embed)
        except discord.Forbidden:
            await ctx.send(embed=error_embed("DM Failed", f"I was unable to DM you the reminder, {ctx.author.mention}."))

    @commands.hybrid_command(name="ship", description="Ships 2 users!")
    @app_commands.describe(user1="The first user", user2="The second user")
    async def ship(self, ctx, user1: discord.Member = None, user2: discord.Member = None):
        if not user1 or not user2:
            await ctx.send(embed=error_embed("Invalid Users", "Please mention two valid users to ship!"))
            return
        if user1 == user2:
            await ctx.send(embed=error_embed("Invalid Users", "You can't ship someone with themselves!"))
            return

        override_score = get_ship_override(ctx.guild.id, user1.id, user2.id)
        chance = override_score if override_score is not None else random.randint(0, 100)
        previous_stats = get_ship_pair_stats(ctx.guild.id, user1.id, user2.id)
        updated_stats = record_ship_pair(ctx.guild.id, user1, user2, chance)
        if chance <= 25:
            verdict = "NOT meant to be together. RUN!"
        elif chance <= 50:
            verdict = "Hmm... questionable."
        elif chance <= 75:
            verdict = "This could work out!"
        else:
            verdict = "Meant to be together!"

        bar_fill = chance // 10
        bar = "█" * bar_fill + "░" * (10 - bar_fill)

        embed = discord.Embed(
            title=f"Ship — {user1.display_name} & {user2.display_name}",
            description=(
                f"> **Verdict:** {verdict}\n"
                f"> **Compatibility:** `{bar}` **{chance}%**\n"
                f"> **Times Shipped:** **{updated_stats['count']}**\n"
                f"> **Average Compatibility:** **{updated_stats['average_score']}%**"
            ),
            color=BLANK_COLOR,
            )
        if previous_stats["count"]:
            embed.add_field(
                name="Previous Stats",
                value=(
                    f"> **Previous Ships:** **{previous_stats['count']}**\n"
                    f"> **Previous Average:** **{previous_stats['average_score']}%**"
                ),
                inline=False,
            )
        if override_score is not None:
            embed.add_field(
                name="Override Active",
                value=f"> This pair has a forced compatibility of **{override_score}%**.",
                inline=False,
            )
        embed.set_author(name=ctx.guild.name, icon_url=ctx.guild.icon.url if ctx.guild.icon else "")
        brand_footer(embed)
        await ctx.send(embed=embed)

    @commands.command(name="shipoverride")
    @commands.guild_only()
    @commands.is_owner()
    async def shipoverride(self, ctx: commands.Context, user1: discord.Member, user2: discord.Member, percent: int):
        if user1 == user2:
            await ctx.send(embed=error_embed("Invalid Users", "You can't ship someone with themselves!"))
            return
        if percent < 0 or percent > 100:
            await ctx.send(embed=error_embed("Invalid Percentage", "Ship override percent must be between `0` and `100`."))
            return

        set_ship_override(ctx.guild.id, user1, user2, percent)
        await ctx.send(
            embed=success_embed(
                "Ship Override Set",
                f"Forced **{user1.display_name}** and **{user2.display_name}** to ship at **{percent}%**.",
            )
        )

    @commands.hybrid_command(name="coinflip", description="Flip a coin!")
    async def coinflip(self, ctx):
        result = random.choice(["Heads", "Tails"])
        embed = discord.Embed(
            title="Coin Flip",
            description=f"The coin landed on **{result}**!",
            color=BLANK_COLOR,
        )
        embed.set_author(name=ctx.guild.name, icon_url=ctx.guild.icon.url if ctx.guild.icon else "")
        brand_footer(embed)
        await ctx.send(embed=embed)

    @commands.hybrid_command(name="8ball", description="Ask the magic 8-ball a question.")
    @app_commands.describe(question="Your question for the 8-ball")
    async def eight_ball(self, ctx, *, question: str):
        response = random.choice(EIGHT_BALL_RESPONSES)
        embed = discord.Embed(
            title="Magic 8-Ball",
            description=(
                f"> **Question:** {question}\n"
                f"> **Answer:** *{response}*"
            ),
            color=BLANK_COLOR,
        )
        embed.set_author(name=ctx.guild.name, icon_url=ctx.guild.icon.url if ctx.guild.icon else "")
        brand_footer(embed)
        await ctx.send(embed=embed)

    @commands.hybrid_command(name="avatar", description="View a user's avatar.")
    @app_commands.describe(user="The user whose avatar to view")
    async def avatar(self, ctx, user: discord.Member = None):
        user = user or ctx.author
        embed = discord.Embed(title=f"{user.display_name}'s Avatar", color=BLANK_COLOR)
        embed.set_author(name=ctx.guild.name, icon_url=ctx.guild.icon.url if ctx.guild.icon else "")
        embed.set_image(url=user.display_avatar.url)
        brand_footer(embed)

        view = discord.ui.View()
        view.add_item(discord.ui.Button(label="Open in Browser", url=user.display_avatar.url))
        await ctx.send(embed=embed, view=view)

    @commands.hybrid_command(name="who_is_cool", description="Who is cool?")
    async def who_is_cool(self, ctx):
        role = discord.utils.get(ctx.author.roles, id=ALLOWED_ROLE_ID)
        if role:
            await ctx.send(embed=info_embed("Who Is Cool?", "<@614895781832556585> is cool!"))
        else:
            await ctx.send(embed=error_embed("Missing Role", "You don't have the required role to use this command."))

    @commands.hybrid_command(name="vctts", description="Speak a message in a voice channel using text-to-speech.")
    @app_commands.describe(message="The message to speak.")
    async def vctts(self, ctx: commands.Context, *, message: str):
        if ctx.author.voice is None:
            await ctx.reply(embed=error_embed("Not in Voice Channel", "You need to be in a voice channel to use this command."), ephemeral=True)
            return

        voice_channel = ctx.author.voice.channel
        vc = await voice_channel.connect()

        tts_engine = pyttsx3.init()
        tts_engine.setProperty('rate', 150)
        tts_engine.setProperty('volume', 1.0)

        with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as temp_audio:
            temp_audio_path = temp_audio.name
            tts_engine.save_to_file(message, temp_audio_path)
            tts_engine.runAndWait()

        audio_source = discord.FFmpegPCMAudio(temp_audio_path)
        vc.play(audio_source, after=lambda e: print(f"Finished playing: {e}"))

        while vc.is_playing():
            await asyncio.sleep(1)

        await vc.disconnect()
        os.remove(temp_audio_path)
        await ctx.reply(embed=success_embed("Message Spoken", "Message spoken successfully."))

    @commands.hybrid_command(name="dog", description="Gets a random dog image.")
    async def dog(self, ctx):
        async with aiohttp.ClientSession() as session:
            async with session.get(DOG_API_URL) as response:
                if response.status == 200:
                    data = await response.json()
                    embed = discord.Embed(title="Random Dog", color=BLANK_COLOR)
                    embed.set_author(name=ctx.guild.name, icon_url=ctx.guild.icon.url if ctx.guild.icon else "")
                    embed.set_image(url=data[0]['url'])
                    brand_footer(embed)
                    await ctx.send(embed=embed)
                else:
                    await ctx.send(embed=error_embed("Fetch Failed", "Couldn't fetch a dog image, try again later!"))

    @commands.hybrid_command(name="cat", description="Gets a random cat image.")
    async def cat(self, ctx):
        async with aiohttp.ClientSession() as session:
            async with session.get(CAT_API_URL) as response:
                if response.status == 200:
                    data = await response.json()
                    embed = discord.Embed(title="Random Cat", color=BLANK_COLOR)
                    embed.set_author(name=ctx.guild.name, icon_url=ctx.guild.icon.url if ctx.guild.icon else "")
                    embed.set_image(url=data[0]['url'])
                    brand_footer(embed)
                    await ctx.send(embed=embed)
                else:
                    await ctx.send(embed=error_embed("Fetch Failed", "Couldn't fetch a cat image, try again later!"))


async def setup(bot):
    await bot.add_cog(Fun(bot))
