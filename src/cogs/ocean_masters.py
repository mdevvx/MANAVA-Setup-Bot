from __future__ import annotations

import logging
from typing import TYPE_CHECKING
from uuid import UUID

import discord
from discord import app_commands
from discord.ext import commands

from src import constants
from src.db.repositories import ocean_masters as ocean_masters_repo
from src.db.repositories import seasons as seasons_repo
from src.db.repositories import squads as squads_repo
from src.discord_state.staff_check import require_elevated_staff
from src.errors import BotUserError
from src.models.ocean_masters import MatchDecisionResult, MatchStatus, OceanMastersMatch, OceanMastersMode
from src.services import ocean_masters_service

if TYPE_CHECKING:
    from src.bot import ManavaBot

logger = logging.getLogger(__name__)

_GAME_CHOICES = [app_commands.Choice(name=g, value=g) for g in constants.MANAVA_GAMES]


class OceanMastersCog(commands.Cog):
    def __init__(self, bot: "ManavaBot") -> None:
        self.bot = bot

    om_group = app_commands.Group(
        name="oceanmasters",
        description="Ocean Masters tournament (Admin / MANAVA Team only)",
        default_permissions=discord.Permissions(administrator=True),
        guild_only=True,
    )

    async def _active_squad_autocomplete(
        self, interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        try:
            async with self.bot.db_pool.acquire() as conn:
                names = await squads_repo.search_squad_names(conn, active=True, name_contains=current)
        except Exception:  # noqa: BLE001 — autocomplete must never raise
            logger.exception("oceanmasters squad autocomplete failed")
            return []
        return [app_commands.Choice(name=n, value=n) for n in names]

    @om_group.command(name="create", description="Set up the Ocean Masters bracket from the published Top-32")
    @app_commands.describe(
        mode="Single-game or Cross-game",
        game1="First (or only) game",
        game2="Second game — Cross-game only",
        game3="Third game — Cross-game only",
    )
    @app_commands.choices(
        mode=[
            app_commands.Choice(name="Single-game", value=OceanMastersMode.SINGLE_GAME.value),
            app_commands.Choice(name="Cross-game", value=OceanMastersMode.CROSS_GAME.value),
        ],
        game1=_GAME_CHOICES,
        game2=_GAME_CHOICES,
        game3=_GAME_CHOICES,
    )
    async def create(
        self,
        interaction: discord.Interaction,
        mode: str,
        game1: str,
        game2: str | None = None,
        game3: str | None = None,
    ) -> None:
        await require_elevated_staff(self.bot, interaction)
        await interaction.response.defer(ephemeral=True, thinking=True)
        games = [g for g in (game1, game2, game3) if g is not None]
        async with self.bot.db_pool.acquire() as conn:
            result = await ocean_masters_service.create_tournament(
                conn,
                mode=OceanMastersMode(mode),
                games=games,
                created_by=interaction.user.id,
                channels=self.bot.ocean_masters_state,
            )
        await interaction.followup.send(
            f"Ocean Masters created in **draft** — {result.matches_created} first-round match(es). "
            f"Use `/oceanmasters bracket` to view it, `/oceanmasters launch` when ready to go live.",
            ephemeral=True,
        )

    @om_group.command(name="set-tie-rule", description="Configure the Cross-game discipline-tie rule")
    @app_commands.choices(
        rule=[app_commands.Choice(name=r, value=r) for r in constants.ALL_CROSS_GAME_TIE_RULES]
    )
    async def set_tie_rule(self, interaction: discord.Interaction, rule: str) -> None:
        await require_elevated_staff(self.bot, interaction)
        await interaction.response.defer(ephemeral=True, thinking=True)
        async with self.bot.db_pool.acquire() as conn:
            await ocean_masters_service.set_tie_rule(conn, rule, actor_id=interaction.user.id)
        await interaction.followup.send(f"Cross-game tie-break rule set to `{rule}`.", ephemeral=True)

    @om_group.command(name="set-min-squads", description="Configure the Ocean Masters minimum active-squads threshold")
    @app_commands.describe(value="Minimum active squads (informational — never auto-launches)")
    async def set_min_squads(self, interaction: discord.Interaction, value: int) -> None:
        await require_elevated_staff(self.bot, interaction)
        await interaction.response.defer(ephemeral=True, thinking=True)
        async with self.bot.db_pool.acquire() as conn:
            await ocean_masters_service.set_min_squads(conn, value, actor_id=interaction.user.id)
        await interaction.followup.send(f"Ocean Masters minimum-squad threshold set to **{value}**.", ephemeral=True)

    @om_group.command(name="launch", description="Launch the current season's Ocean Masters (manual, staff-only)")
    async def launch(self, interaction: discord.Interaction) -> None:
        await require_elevated_staff(self.bot, interaction)
        await interaction.response.defer(ephemeral=True, thinking=True)
        async with self.bot.db_pool.acquire() as conn:
            season = await seasons_repo.get_active(conn)
            if season is None:
                raise BotUserError("There's no active season.")
            tournament = await ocean_masters_repo.get_by_season(conn, season.id)
            if tournament is None:
                raise BotUserError("No Ocean Masters tournament exists for this season yet — run /oceanmasters create.")
            _, warning = await ocean_masters_service.launch_tournament(
                conn, tournament.id, actor_id=interaction.user.id, channels=self.bot.ocean_masters_state
            )
        message = "Ocean Masters is now **launched**."
        if warning:
            message += f"\n⚠️ {warning}"
        await interaction.followup.send(message, ephemeral=True)

    @om_group.command(name="bracket", description="Show the current Ocean Masters bracket")
    async def bracket(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        async with self.bot.db_pool.acquire() as conn:
            season = await seasons_repo.get_active(conn)
            if season is None:
                await interaction.followup.send("No active season.", ephemeral=True)
                return
            tournament = await ocean_masters_repo.get_by_season(conn, season.id)
            if tournament is None:
                await interaction.followup.send("No Ocean Masters tournament exists for this season yet.", ephemeral=True)
                return
            matches = await ocean_masters_repo.get_bracket(conn, tournament.id)

        lines = [f"**Ocean Masters** — {tournament.mode.value} · {tournament.status.value}"]
        current_round = None
        for m in matches:
            if m.round != current_round:
                current_round = m.round
                lines.append(f"\n**Round {current_round}**")
            a = m.squad_a_name or "(bye)"
            b = m.squad_b_name or "(bye)"
            if m.winner_squad_id is not None:
                winner = a if m.winner_squad_id == m.squad_a_id else b
                lines.append(f"#{m.seed_a} {a} v #{m.seed_b} {b} — **{winner}** ({m.status.value})")
            else:
                lines.append(f"#{m.seed_a} {a} v #{m.seed_b} {b} — pending")
        await interaction.followup.send("\n".join(lines), ephemeral=True)

    # --- Match decisions -----------------------------------------------------

    match_group = app_commands.Group(name="match", description="Ocean Masters match results", parent=om_group)

    @match_group.command(name="set-result", description="Staff-entered match result (Single-game, or to break a Cross-game tie)")
    @app_commands.describe(match_id="Match ID (from /oceanmasters bracket)", winner="Winning squad", reason="Optional")
    @app_commands.autocomplete(winner=_active_squad_autocomplete)
    async def set_result(
        self, interaction: discord.Interaction, match_id: str, winner: str, reason: str | None = None
    ) -> None:
        await require_elevated_staff(self.bot, interaction)
        await interaction.response.defer(ephemeral=True, thinking=True)
        async with self.bot.db_pool.acquire() as conn:
            squad = await squads_repo.get_active_squad_by_name(conn, winner)
            if squad is None:
                raise BotUserError(f"No active squad named **{winner}** was found.")
            result = await ocean_masters_service.set_result(
                conn,
                _parse_match_id(match_id),
                winner_squad_id=squad.id,
                actor_id=interaction.user.id,
                reason=reason,
                channels=self.bot.ocean_masters_state,
            )
        await interaction.followup.send(_decision_summary(result.match, result), ephemeral=True)

    @match_group.command(name="set-discipline-result", description="Cross-game: record one game's result for a match")
    @app_commands.describe(match_id="Match ID (from /oceanmasters bracket)", game="Which game", winner="Winning squad")
    @app_commands.choices(game=_GAME_CHOICES)
    @app_commands.autocomplete(winner=_active_squad_autocomplete)
    async def set_discipline_result(
        self, interaction: discord.Interaction, match_id: str, game: str, winner: str
    ) -> None:
        await require_elevated_staff(self.bot, interaction)
        await interaction.response.defer(ephemeral=True, thinking=True)
        async with self.bot.db_pool.acquire() as conn:
            squad = await squads_repo.get_active_squad_by_name(conn, winner)
            if squad is None:
                raise BotUserError(f"No active squad named **{winner}** was found.")
            result = await ocean_masters_service.set_discipline_result(
                conn,
                _parse_match_id(match_id),
                game=game,
                winner_squad_id=squad.id,
                actor_id=interaction.user.id,
                channels=self.bot.ocean_masters_state,
            )
        remaining = len(result.match.per_discipline_results)
        if result.match.status is MatchStatus.PENDING:
            await interaction.followup.send(
                f"Recorded **{game}** for {winner}. {remaining} discipline result(s) in so far.", ephemeral=True
            )
        else:
            await interaction.followup.send(_decision_summary(result.match, result), ephemeral=True)

    @match_group.command(name="override", description="Staff override: technical loss, no-show, disqualified, or forfeit")
    @app_commands.describe(
        match_id="Match ID (from /oceanmasters bracket)",
        outcome="What happened",
        winner="Squad that advances",
        reason="Required — recorded in the audit log",
    )
    @app_commands.choices(
        outcome=[
            app_commands.Choice(name="Technical loss", value=MatchStatus.TECHNICAL_LOSS.value),
            app_commands.Choice(name="No-show", value=MatchStatus.NO_SHOW.value),
            app_commands.Choice(name="Disqualified", value=MatchStatus.DISQUALIFIED.value),
            app_commands.Choice(name="Forfeit", value=MatchStatus.FORFEIT.value),
        ]
    )
    @app_commands.autocomplete(winner=_active_squad_autocomplete)
    async def override(
        self, interaction: discord.Interaction, match_id: str, outcome: str, winner: str, reason: str
    ) -> None:
        await require_elevated_staff(self.bot, interaction)
        if not reason.strip():
            raise BotUserError("A reason is required for an override.")
        await interaction.response.defer(ephemeral=True, thinking=True)
        async with self.bot.db_pool.acquire() as conn:
            squad = await squads_repo.get_active_squad_by_name(conn, winner)
            if squad is None:
                raise BotUserError(f"No active squad named **{winner}** was found.")
            result = await ocean_masters_service.override_match(
                conn,
                _parse_match_id(match_id),
                outcome=MatchStatus(outcome),
                winner_squad_id=squad.id,
                actor_id=interaction.user.id,
                reason=reason,
                channels=self.bot.ocean_masters_state,
            )
        await interaction.followup.send(_decision_summary(result.match, result), ephemeral=True)


def _parse_match_id(raw: str) -> UUID:
    try:
        return UUID(raw)
    except ValueError as exc:
        raise BotUserError("That doesn't look like a valid match ID — copy it from /oceanmasters bracket.") from exc


def _decision_summary(match: OceanMastersMatch, result: MatchDecisionResult) -> str:
    winner_name = match.squad_a_name if match.winner_squad_id == match.squad_a_id else match.squad_b_name
    lines = [f"Match decided ({match.status.value}): **{winner_name}** advances."]
    if result.tournament_completed:
        lines.append(f"🏆 **{winner_name}** is the Ocean Masters champion!")
    elif result.round_advanced:
        lines.append("The next round has been generated.")
    return "\n".join(lines)


async def setup(bot: "ManavaBot") -> None:
    await bot.add_cog(OceanMastersCog(bot))
