from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands

from src.discord_state.staff_check import require_elevated_staff
from src.services import season_service
from src.ui.confirm_view import ConfirmView

if TYPE_CHECKING:
    from src.bot import ManavaBot

logger = logging.getLogger(__name__)


class SeasonsCog(commands.Cog):
    def __init__(self, bot: "ManavaBot") -> None:
        self.bot = bot

    season_group = app_commands.Group(
        name="season", description="Season controls (Admin / MANAVA Team only)"
    )

    @season_group.command(name="status", description="Show the current season")
    async def status(self, interaction: discord.Interaction) -> None:
        await require_elevated_staff(self.bot, interaction)
        await interaction.response.defer(ephemeral=True, thinking=True)
        async with self.bot.db_pool.acquire() as conn:
            season = await season_service.get_current(conn)
        if season is None:
            await interaction.followup.send(
                "No season has been started yet. Use `/season start` to open the first one.", ephemeral=True
            )
            return
        lines = [
            f"**Season {season.season_number}** — {season.status.value}",
            f"Started: {discord.utils.format_dt(season.started_at, 'R')} by <@{season.started_by}>",
        ]
        if season.ended_at is not None:
            lines.append(
                f"Ended: {discord.utils.format_dt(season.ended_at, 'R')} by <@{season.ended_by}>"
            )
        await interaction.followup.send("\n".join(lines), ephemeral=True)

    @season_group.command(name="start", description="Start a new season (fails if one is already active)")
    async def start(self, interaction: discord.Interaction) -> None:
        await require_elevated_staff(self.bot, interaction)
        await interaction.response.defer(ephemeral=True, thinking=True)
        async with self.bot.db_pool.acquire() as conn:
            season = await season_service.start_season(conn, actor_id=interaction.user.id)
        await interaction.followup.send(f"**Season {season.season_number}** is now active.", ephemeral=True)

    @season_group.command(name="end", description="End the currently active season")
    async def end(self, interaction: discord.Interaction) -> None:
        await require_elevated_staff(self.bot, interaction)
        await interaction.response.defer(ephemeral=True, thinking=True)
        async with self.bot.db_pool.acquire() as conn:
            season = await season_service.end_season(conn, actor_id=interaction.user.id)
        await interaction.followup.send(
            f"**Season {season.season_number}** has ended. Season XP is frozen until the next season starts.",
            ephemeral=True,
        )

    @season_group.command(
        name="new",
        description="Start New Season: end the current one and RESET all Season XP to 0 (Lifetime XP is kept)",
    )
    async def new(self, interaction: discord.Interaction) -> None:
        await require_elevated_staff(self.bot, interaction)

        async def do_reset(confirm_interaction: discord.Interaction) -> None:
            async with self.bot.db_pool.acquire() as conn:
                result = await season_service.start_new_season(conn, actor_id=interaction.user.id)
            ended = (
                f"Ended Season {result.ended_season_number}. "
                if result.ended_season_number is not None
                else ""
            )
            await confirm_interaction.followup.send(
                f"{ended}**Season {result.new_season_number}** is now active.\n"
                f"Reset Personal Season XP for {result.personal_rows_reset} user(s) and "
                f"Season Squad XP for {result.squad_rows_reset} squad(s). "
                f"Lifetime XP was not touched.",
                ephemeral=True,
            )

        view = ConfirmView(invoker_id=interaction.user.id, on_confirm=do_reset)
        await interaction.response.send_message(
            "**Start New Season?** This zeroes every Personal Season XP and Season Squad XP counter. "
            "Lifetime XP and Lifetime Squad XP are kept. This cannot be undone.",
            view=view,
            ephemeral=True,
        )


async def setup(bot: "ManavaBot") -> None:
    await bot.add_cog(SeasonsCog(bot))
