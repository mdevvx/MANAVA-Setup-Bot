from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands

from src.db.repositories import season_qualifications as season_qualifications_repo
from src.db.repositories import seasons as seasons_repo
from src.discord_state.staff_check import require_elevated_staff
from src.errors import BotUserError
from src.services import season_service, top32_service
from src.ui.confirm_view import ConfirmView

if TYPE_CHECKING:
    from src.bot import ManavaBot

logger = logging.getLogger(__name__)


class SeasonsCog(commands.Cog):
    def __init__(self, bot: "ManavaBot") -> None:
        self.bot = bot

    # Hidden from anyone without the Discord Administrator permission; the
    # require_elevated_staff() checks remain the real gate.
    season_group = app_commands.Group(
        name="season",
        description="Season controls (Admin / MANAVA Team only)",
        default_permissions=discord.Permissions(administrator=True),
        guild_only=True,
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
            f"**Season {season.season_number}** — {season.status.value} · phase: **{season.phase.value}**",
            f"Started: {discord.utils.format_dt(season.started_at, 'R')} by <@{season.started_by}>",
        ]
        if season.locked_at is not None:
            lines.append(f"Locked: {discord.utils.format_dt(season.locked_at, 'R')} by <@{season.locked_by}>")
        if season.published_at is not None:
            lines.append(
                f"Top-32 published: {discord.utils.format_dt(season.published_at, 'R')} by <@{season.published_by}>"
            )
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

    @season_group.command(name="lock", description="Qualification Lock: freeze the qualification ranking snapshot")
    async def lock(self, interaction: discord.Interaction) -> None:
        await require_elevated_staff(self.bot, interaction)

        async def do_lock(confirm_interaction: discord.Interaction) -> None:
            async with self.bot.db_pool.acquire() as conn:
                result = await season_service.lock_qualification(conn, actor_id=interaction.user.id)
            await confirm_interaction.followup.send(
                f"**Season {result.season_number}** is locked. Ranked {result.squads_ranked} active squad(s) "
                f"into the qualification list. Use `/season top32 list` to view it.",
                ephemeral=True,
            )

        view = ConfirmView(invoker_id=interaction.user.id, on_confirm=do_lock)
        await interaction.response.send_message(
            "**Lock qualification?** This freezes the current ranking (Season Squad XP, tie-broken by "
            "Lifetime Squad XP) as the official qualification list. New XP keeps accruing afterward, but it "
            "won't change this snapshot.",
            view=view,
            ephemeral=True,
        )

    @season_group.command(
        name="publish-top32", description="Confirm / Publish: assign seeds and make the Top-32 bracket official"
    )
    async def publish_top32(self, interaction: discord.Interaction) -> None:
        await require_elevated_staff(self.bot, interaction)

        async def do_publish(confirm_interaction: discord.Interaction) -> None:
            async with self.bot.db_pool.acquire() as conn:
                result = await season_service.publish_top32(conn, actor_id=interaction.user.id)
            await confirm_interaction.followup.send(
                f"**Season {result.season_number}** Top-32 is published. {result.seeds_assigned} seed(s) "
                f"assigned. This is now the official bracket list — further changes go through "
                f"`/season top32 disqualify`.",
                ephemeral=True,
            )

        view = ConfirmView(invoker_id=interaction.user.id, on_confirm=do_publish)
        await interaction.response.send_message(
            "**Publish the Top-32 bracket?** This assigns seeds 1-32 over whichever squads are still "
            "qualified and freezes the list as official. Once published, replacements are no longer "
            "automatic — only staff DQ/forfeit/override.",
            view=view,
            ephemeral=True,
        )

    @season_group.command(
        name="complete", description="Season Complete: persist the final standings and close the season"
    )
    async def complete(self, interaction: discord.Interaction) -> None:
        await require_elevated_staff(self.bot, interaction)

        async def do_complete(confirm_interaction: discord.Interaction) -> None:
            async with self.bot.db_pool.acquire() as conn:
                result = await season_service.complete_season(conn, actor_id=interaction.user.id)
            await confirm_interaction.followup.send(
                f"**Season {result.season_number}** is complete. Recorded final standings for "
                f"{result.squads_recorded} squad(s). Season XP is untouched — run `/season new` when you're "
                f"ready to open the next season.",
                ephemeral=True,
            )

        view = ConfirmView(invoker_id=interaction.user.id, on_confirm=do_complete)
        await interaction.response.send_message(
            "**Complete this season?** This persists the final Squad Leaderboard into the season's permanent "
            "history and closes it out. It does NOT reset XP or open a new season — use `/season new` "
            "separately for that.",
            view=view,
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

    # --- Top-32 qualification list -----------------------------------------

    top32_group = app_commands.Group(name="top32", description="Top-32 qualification list", parent=season_group)

    async def _qualified_squad_autocomplete(
        self, interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        try:
            async with self.bot.db_pool.acquire() as conn:
                active = await seasons_repo.get_active(conn)
                if active is None:
                    return []
                names = await season_qualifications_repo.search_qualified_squad_names(
                    conn, active.id, name_contains=current
                )
        except Exception:  # noqa: BLE001 — autocomplete must never raise
            logger.exception("top32 squad autocomplete failed")
            return []
        return [app_commands.Choice(name=n, value=n) for n in names]

    @top32_group.command(name="list", description="Show the locked qualification list / current Top-32 window")
    async def top32_list(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        async with self.bot.db_pool.acquire() as conn:
            active = await seasons_repo.get_active(conn)
            if active is None:
                await interaction.followup.send("No active season.", ephemeral=True)
                return
            entries = await season_qualifications_repo.get_top32_window(conn, active.id)

        if not entries:
            await interaction.followup.send(
                "No qualification list yet for this season — run `/season lock` first.", ephemeral=True
            )
            return

        published = entries[0].seed is not None
        lines = [f"**Season {active.season_number} — Top-32** ({'published' if published else 'not yet published'})"]
        if published:
            names_by_squad = {e.squad_id: e.squad_name for e in entries}
            for pairing in top32_service.generate_seed_pairings(entries):
                lines.append(
                    f"#{pairing.seed_a} {names_by_squad[pairing.squad_a_id]} "
                    f"v #{pairing.seed_b} {names_by_squad[pairing.squad_b_id]}"
                )
        else:
            for e in entries:
                lines.append(f"**rank #{e.rank}** — {e.squad_name} ({e.season_xp_snapshot} season XP)")
        await interaction.followup.send("\n".join(lines), ephemeral=True)

    @top32_group.command(name="withdraw", description="Pre-publish: staff-confirmed withdrawal from the Top-32 list")
    @app_commands.describe(squad_name="Squad to withdraw", reason="Optional reason, recorded in the audit log")
    @app_commands.autocomplete(squad_name=_qualified_squad_autocomplete)
    async def top32_withdraw(
        self, interaction: discord.Interaction, squad_name: str, reason: str | None = None
    ) -> None:
        await require_elevated_staff(self.bot, interaction)
        await interaction.response.defer(ephemeral=True, thinking=True)
        async with self.bot.db_pool.acquire() as conn:
            entry = await top32_service.withdraw(
                conn, squad_name, actor_id=interaction.user.id, reason=reason
            )
        await interaction.followup.send(f"**{entry.squad_name}** withdrawn from the Top-32 list.", ephemeral=True)

    @top32_group.command(
        name="disqualify", description="Pre- or post-publish: flag a squad as disqualified"
    )
    @app_commands.describe(squad_name="Squad to disqualify", reason="Required, recorded in the audit log")
    @app_commands.autocomplete(squad_name=_qualified_squad_autocomplete)
    async def top32_disqualify(self, interaction: discord.Interaction, squad_name: str, reason: str) -> None:
        await require_elevated_staff(self.bot, interaction)
        if not reason.strip():
            raise BotUserError("A reason is required to disqualify a squad.")
        await interaction.response.defer(ephemeral=True, thinking=True)
        async with self.bot.db_pool.acquire() as conn:
            entry = await top32_service.disqualify(
                conn, squad_name, actor_id=interaction.user.id, reason=reason
            )
        await interaction.followup.send(f"**{entry.squad_name}** marked disqualified.", ephemeral=True)


async def setup(bot: "ManavaBot") -> None:
    await bot.add_cog(SeasonsCog(bot))
