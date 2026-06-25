import os
import sqlite3
import threading
import time
from pathlib import Path
from typing import Optional

import discord
from discord.ext import commands
from discord import app_commands

from config import BASE_DIR
from cogs.helpers import (
    BLANK_COLOR, CSRP_ICON, CHECK, CROSS,
    success_embed, error_embed, brand_footer,
)

PUNISHMENTS_DB_FILE = BASE_DIR / "punishments.sqlite3"
_DB_LOCK = threading.RLock()

STAFF_TEAM_ROLE_ID = 968852438922715176
DEV_ROLE_IDS = {1340433106217205903, 1321363819519283220, 1323534294257500162, 1374173264330625155}


def _logging_down() -> bool:
    return os.getenv("LOGGING_DOWN", "").upper() == "TRUE"


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(PUNISHMENTS_DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn


def _initialize_db() -> None:
    with _DB_LOCK:
        conn = _connect()
        try:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS punishments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT NOT NULL,
                    punishment TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    description TEXT,
                    logged_by INTEGER NOT NULL,
                    timestamp INTEGER NOT NULL
                )
                """
            )
            conn.commit()
        finally:
            conn.close()


def _save_punishment(username: str, punishment: str, reason: str, description: Optional[str], logged_by: int) -> int:
    _initialize_db()
    with _DB_LOCK:
        conn = _connect()
        try:
            cursor = conn.execute(
                """
                INSERT INTO punishments (username, punishment, reason, description, logged_by, timestamp)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (username, punishment, reason, description, logged_by, int(time.time())),
            )
            conn.commit()
            return cursor.lastrowid
        finally:
            conn.close()


def _get_all_punishments() -> list[dict]:
    _initialize_db()
    with _DB_LOCK:
        conn = _connect()
        try:
            rows = conn.execute(
                "SELECT id, username, punishment, reason, description, logged_by, timestamp FROM punishments ORDER BY id ASC"
            ).fetchall()
            return [dict(row) for row in rows]
        finally:
            conn.close()


class Punishments(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    def _has_staff_team(self, interaction: discord.Interaction) -> bool:
        return any(role.id == STAFF_TEAM_ROLE_ID for role in interaction.user.roles)

    def _has_dev_role(self, interaction: discord.Interaction) -> bool:
        return any(role.id in DEV_ROLE_IDS for role in interaction.user.roles)

    @app_commands.command(name="plog", description="Log a punishment (available when logging is down)")
    @app_commands.describe(
        username="The username of the punished user",
        punishment="The punishment given",
        reason="Reason for the punishment",
        description="Optional additional details",
    )
    async def plog(
        self,
        interaction: discord.Interaction,
        username: str,
        punishment: str,
        reason: str,
        description: Optional[str] = None,
    ):
        if not _logging_down():
            return await interaction.response.send_message(
                embed=error_embed("Unavailable", f"{CROSS} This command is only available when logging is down."),
                ephemeral=True,
            )

        if not self._has_staff_team(interaction):
            return await interaction.response.send_message(
                embed=error_embed("No Permission", f"{CROSS} You must have the Staff Team role to use this command."),
                ephemeral=True,
            )

        row_id = _save_punishment(username, punishment, reason, description, interaction.user.id)

        embed = discord.Embed(
            title="Punishment Logged",
            color=BLANK_COLOR,
            timestamp=discord.utils.utcnow(),
        )
        embed.add_field(name="Username", value=username, inline=True)
        embed.add_field(name="Punishment", value=punishment, inline=True)
        embed.add_field(name="Reason", value=reason, inline=False)
        if description:
            embed.add_field(name="Description", value=description, inline=False)
        embed.set_footer(text=f"Logged by {interaction.user.display_name} • ID: {row_id}", icon_url=CSRP_ICON)

        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="pexport", description="Export all logged punishments to DMs (developers only)")
    async def pexport(self, interaction: discord.Interaction):
        if not self._has_dev_role(interaction):
            return await interaction.response.send_message(
                embed=error_embed("No Permission", f"{CROSS} This command is restricted to developers."),
                ephemeral=True,
            )

        punishments = _get_all_punishments()
        if not punishments:
            return await interaction.response.send_message(
                embed=error_embed("No Data", f"{CROSS} There are no punishments logged."),
                ephemeral=True,
            )

        lines = ["Username | Punishment | Reason"]
        lines.append("-" * 40)
        for p in punishments:
            lines.append(f"{p['username']} | {p['punishment']} | {p['reason']}")

        content = "\n".join(lines)

        await interaction.response.defer(ephemeral=True)

        try:
            if len(content) <= 1990:
                await interaction.user.send(f"```\n{content}\n```")
            else:
                chunks = []
                current_chunk = "```\n"
                for line in lines:
                    if len(current_chunk) + len(line) + 5 > 1990:
                        current_chunk += "\n```"
                        chunks.append(current_chunk)
                        current_chunk = "```\n"
                    current_chunk += line + "\n"
                if current_chunk != "```\n":
                    current_chunk += "```"
                    chunks.append(current_chunk)

                for chunk in chunks:
                    await interaction.user.send(chunk)

            await interaction.followup.send(
                embed=success_embed("Exported", f"{CHECK} Punishment logs have been sent to your DMs."),
                ephemeral=True,
            )
        except discord.Forbidden:
            await interaction.followup.send(
                embed=error_embed("DMs Closed", f"{CROSS} Unable to send DMs. Please enable DMs from server members."),
                ephemeral=True,
            )


async def setup(bot: commands.Bot):
    await bot.add_cog(Punishments(bot))
