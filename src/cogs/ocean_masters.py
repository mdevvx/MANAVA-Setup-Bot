from __future__ import annotations

import logging
from typing import TYPE_CHECKING
from collections.abc import Sequence
from uuid import UUID

import asyncpg
import discord
from discord import app_commands
from discord.ext import commands

from src import constants
from src.db.repositories import ocean_masters as ocean_masters_repo
from src.db.repositories import seasons as seasons_repo
from src.db.repositories import squads as squads_repo
from src.discord_state.staff_check import require_elevated_staff
from src.errors import BotUserError
from src.models.ocean_masters import (
    CorrectionResult,
    MatchDecisionResult,
    MatchStatus,
    OceanMasters,
    OceanMastersMatch,
    OceanMastersMode,
)
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

    async def _match_choices(self, current: str, *, decided: bool) -> list[app_commands.Choice[str]]:
        try:
            async with self.bot.db_pool.acquire() as conn:
                tournament = await _current_tournament(conn)
                if tournament is None:
                    return [_placeholder("No Ocean Masters tournament this season yet — run /oceanmasters create")]
                matches = await ocean_masters_repo.get_bracket(conn, tournament.id)
        except Exception:  # noqa: BLE001 — autocomplete must never raise
            logger.exception("oceanmasters match autocomplete failed")
            return []
        return match_choices(matches, current, decided=decided)

    async def _pending_match_autocomplete(
        self, interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        return await self._match_choices(current, decided=False)

    async def _decided_match_autocomplete(
        self, interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        return await self._match_choices(current, decided=True)

    async def _match_winner_autocomplete(
        self, interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        """Once match_id is filled in, only offer that match's two squads;
        otherwise fall back to every active squad."""
        raw_match = getattr(interaction.namespace, "match_id", None)
        if raw_match:
            match: OceanMastersMatch | None
            try:
                async with self.bot.db_pool.acquire() as conn:
                    match = await ocean_masters_repo.get_match(conn, await _resolve_match_id(conn, str(raw_match)))
            except Exception:  # noqa: BLE001 — autocomplete must never raise
                match = None
            if match is not None:
                names = [n for n in (match.squad_a_name, match.squad_b_name) if n]
                needle = current.casefold()
                return [app_commands.Choice(name=n, value=n) for n in names if needle in n.casefold()]
        return await self._active_squad_autocomplete(interaction, current)

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

        lines = [
            f"**Ocean Masters** — {tournament.mode.value} · {tournament.status.value}",
            "-# Pick a match from the `match_id` dropdown of any `/oceanmasters match` command, "
            "or type the code shown in `backticks`.",
        ]
        current_round = None
        for m in _bracket_display_order(matches):
            if m.round != current_round:
                current_round = m.round
                lines.append(f"\n**Round {current_round}**")
            a = m.squad_a_name or "(bye)"
            b = m.squad_b_name or "(bye)"
            code = f"`{match_short_code(m)}` "
            if m.winner_squad_id is not None:
                winner = a if m.winner_squad_id == m.squad_a_id else b
                lines.append(f"{code}#{m.seed_a} {a} v #{m.seed_b} {b} — **{winner}** ({m.status.value})")
            else:
                lines.append(f"{code}#{m.seed_a} {a} v #{m.seed_b} {b} — pending")
        for chunk in chunk_lines(lines):
            await interaction.followup.send(chunk, ephemeral=True)

    # --- Match decisions -----------------------------------------------------

    match_group = app_commands.Group(name="match", description="Ocean Masters match results", parent=om_group)

    @match_group.command(name="set-result", description="Staff-entered match result (Single-game, or to break a Cross-game tie)")
    @app_commands.describe(match_id="Pick a pending match", winner="Winning squad", reason="Optional")
    @app_commands.autocomplete(match_id=_pending_match_autocomplete, winner=_match_winner_autocomplete)
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
                await _resolve_match_id(conn, match_id),
                winner_squad_id=squad.id,
                actor_id=interaction.user.id,
                reason=reason,
                channels=self.bot.ocean_masters_state,
            )
        await interaction.followup.send(_decision_summary(result.match, result), ephemeral=True)

    @match_group.command(
        name="correct-result",
        description="Fix an already-decided match (result correction / integration-failure override)",
    )
    @app_commands.describe(
        match_id="Pick an already-decided match",
        winner="The correct winning squad",
        reason="Required — recorded in the audit log",
    )
    @app_commands.autocomplete(match_id=_decided_match_autocomplete, winner=_match_winner_autocomplete)
    async def correct_result(
        self, interaction: discord.Interaction, match_id: str, winner: str, reason: str
    ) -> None:
        await require_elevated_staff(self.bot, interaction)
        if not reason.strip():
            raise BotUserError("A reason is required to correct a result.")
        await interaction.response.defer(ephemeral=True, thinking=True)
        async with self.bot.db_pool.acquire() as conn:
            squad = await squads_repo.get_active_squad_by_name(conn, winner)
            if squad is None:
                raise BotUserError(f"No active squad named **{winner}** was found.")
            result = await ocean_masters_service.correct_result(
                conn,
                await _resolve_match_id(conn, match_id),
                winner_squad_id=squad.id,
                actor_id=interaction.user.id,
                reason=reason,
                channels=self.bot.ocean_masters_state,
            )
        await interaction.followup.send(_correction_summary(result), ephemeral=True)

    @match_group.command(name="set-discipline-result", description="Cross-game: record one game's result for a match")
    @app_commands.describe(match_id="Pick a pending match", game="Which game", winner="Winning squad")
    @app_commands.choices(game=_GAME_CHOICES)
    @app_commands.autocomplete(match_id=_pending_match_autocomplete, winner=_match_winner_autocomplete)
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
                await _resolve_match_id(conn, match_id),
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
        match_id="Pick a pending match",
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
    @app_commands.autocomplete(match_id=_pending_match_autocomplete, winner=_match_winner_autocomplete)
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
                await _resolve_match_id(conn, match_id),
                outcome=MatchStatus(outcome),
                winner_squad_id=squad.id,
                actor_id=interaction.user.id,
                reason=reason,
                channels=self.bot.ocean_masters_state,
            )
        await interaction.followup.send(_decision_summary(result.match, result), ephemeral=True)


_MATCH_CODE_LEN = 8
_AUTOCOMPLETE_LIMIT = 25
_MESSAGE_LIMIT = 2000
_NO_MATCH = "none"


def match_short_code(match: OceanMastersMatch) -> str:
    """The code shown in /oceanmasters bracket: the first characters of the
    match UUID, unique enough within one tournament (at most 31 matches)."""
    return match.id.hex[:_MATCH_CODE_LEN]


def match_label(match: OceanMastersMatch) -> str:
    a = match.squad_a_name or "(bye)"
    b = match.squad_b_name or "(bye)"
    label = f"R{match.round} · #{match.seed_a} {a} v #{match.seed_b} {b}"
    if match.status is not MatchStatus.PENDING:
        label += f" — {match.status.value}"
    suffix = f" [{match_short_code(match)}]"
    return label[: 100 - len(suffix)] + suffix


def _placeholder(text: str) -> app_commands.Choice[str]:
    """A single explanatory dropdown entry for when there's nothing to pick,
    instead of Discord's bare "No options match your search"."""
    return app_commands.Choice(name=text[:100], value=_NO_MATCH)


def _bracket_display_order(matches: Sequence[OceanMastersMatch]) -> list[OceanMastersMatch]:
    ordered: list[OceanMastersMatch] = []
    for round_number in sorted({m.round for m in matches}):
        ordered += ocean_masters_service.in_bracket_order([m for m in matches if m.round == round_number], round_number)
    return ordered


def match_choices(
    matches: Sequence[OceanMastersMatch], current: str, *, decided: bool
) -> list[app_commands.Choice[str]]:
    """Autocomplete options for match_id. Byes never show up: they're decided
    automatically and there's no opponent to pick a winner from. The decided
    list (correct-result) only offers matches correct_result will accept —
    the same correction_blocker rule the service enforces."""
    needle = current.strip().strip("`").casefold()
    choices: list[app_commands.Choice[str]] = []
    for m in _bracket_display_order(matches):
        if m.squad_a_id is None or m.squad_b_id is None:
            continue
        if (m.status is not MatchStatus.PENDING) != decided:
            continue
        if decided:
            next_round = [n for n in matches if n.round == m.round + 1]
            if ocean_masters_service.correction_blocker(m, next_round) is not None:
                continue
        label = match_label(m)
        if needle and needle not in label.casefold():
            continue
        choices.append(app_commands.Choice(name=label, value=str(m.id)))
        if len(choices) == _AUTOCOMPLETE_LIMIT:
            break
    if not choices and not needle:
        if not decided:
            return [_placeholder("No pending matches — every match in this bracket has a result")]
        return [_placeholder("Nothing to correct — a result can be fixed until its next match has been played")]
    return choices


async def _current_tournament(conn: asyncpg.Connection) -> OceanMasters | None:
    season = await seasons_repo.get_active(conn)
    if season is None:
        return None
    return await ocean_masters_repo.get_by_season(conn, season.id)


async def _resolve_match_id(conn: asyncpg.Connection, raw: str) -> UUID:
    """Accepts the full match UUID (what the dropdown fills in) or the short
    code shown in /oceanmasters bracket."""
    raw = raw.strip()
    if raw == _NO_MATCH:
        raise BotUserError("There's no match to pick for this command right now — check /oceanmasters bracket.")
    try:
        return UUID(raw)
    except ValueError:
        pass
    code = raw.strip("`").lower()
    if len(code) < 4 or any(ch not in "0123456789abcdef" for ch in code):
        raise BotUserError("Pick the match from the `match_id` dropdown, or type its code from /oceanmasters bracket.")
    tournament = await _current_tournament(conn)
    if tournament is None:
        raise BotUserError("No Ocean Masters tournament exists for this season yet.")
    ids = await ocean_masters_repo.find_match_ids_by_prefix(conn, tournament.id, code)
    if not ids:
        raise BotUserError(f"No match with code `{code}` in this season's Ocean Masters.")
    if len(ids) > 1:
        raise BotUserError(f"Match code `{code}` matches more than one match — pick it from the dropdown instead.")
    return ids[0]


def chunk_lines(lines: Sequence[str]) -> list[str]:
    """Splits the bracket across messages so a full 32-squad bracket never
    hits Discord's 2000-character limit."""
    chunks: list[str] = []
    current = ""
    for line in lines:
        candidate = f"{current}\n{line}" if current else line
        if len(candidate) > _MESSAGE_LIMIT and current:
            chunks.append(current)
            candidate = line.lstrip("\n")
        current = candidate
    if current:
        chunks.append(current)
    return chunks


def _correction_summary(result: CorrectionResult) -> str:
    m = result.match
    winner_name = m.squad_a_name if m.winner_squad_id == m.squad_a_id else m.squad_b_name
    lines = [f"Result corrected: **{winner_name}** is now the winner of this match."]
    if result.champion_changed:
        lines.append(f"🏆 **{winner_name}** is now the Ocean Masters champion. No public notice was posted.")
    elif result.next_match is not None:
        lines.append(f"They've replaced the other squad in their Round {result.next_match.round} match.")
    return "\n".join(lines)


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
