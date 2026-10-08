"""Ocean Masters bracket engine: tournament setup (Single-game / Cross-game),
round-by-round advancement off the Milestone 1 seeding, and the staff
override suite for every non-standard outcome. Automatic production result
ingestion is blocked on the MANAVA playoff-result contract (not yet defined)
— every result in this milestone is staff-entered, which the client
confirmed doesn't block building/QA-testing this module while disabled.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from uuid import UUID

import asyncpg
import discord

from src import constants
from src.db.repositories import audit_logs as audit_repo
from src.db.repositories import bot_config as bot_config_repo
from src.db.repositories import ocean_masters as ocean_masters_repo
from src.db.repositories import season_history as season_history_repo
from src.db.repositories import season_qualifications as season_qualifications_repo
from src.db.repositories import seasons as seasons_repo
from src.db.repositories import squads as squads_repo
from src.discord_state.ocean_masters_setup import ResolvedOceanMastersState
from src.errors import OceanMastersStateError
from src.models.ocean_masters import (
    OVERRIDE_MATCH_STATUSES,
    CorrectionResult,
    CreateResult,
    MatchDecisionResult,
    MatchStatus,
    OceanMasters,
    OceanMastersMatch,
    OceanMastersMode,
    OceanMastersStatus,
)
from src.models.season import SeasonPhase

logger = logging.getLogger(__name__)

# Sentinel actor_id for automatic (non-staff) actions in audit_logs — a bye
# match resolves itself with no one clicking anything. Discord snowflake IDs
# are always large positive integers, so 0 never collides with a real user.
_SYSTEM_ACTOR_ID = 0


def _next_power_of_two(n: int) -> int:
    size = 1
    while size < n:
        size *= 2
    return size


def _standard_bracket_seed_order(size: int) -> list[int]:
    """Classic single-elimination seeding order (`size` must be a power of
    2): seed 1 and seed 2 are placed so they can only meet in the final. The
    round-1 pairs this produces are the same {seed, size+1-seed} pairs as
    Milestone 1's `#1 v #32 ... #16 v #17` display — this just orders the
    MATCHES correctly so sequential-adjacent winners advance correctly in
    round 2 and beyond."""
    seeds = [1, 2]
    while len(seeds) < size:
        bracket_size = len(seeds) * 2
        seeds = [value for seed in seeds for value in (seed, bracket_size + 1 - seed)]
    return seeds


async def set_min_squads(conn: asyncpg.Connection, value: int, *, actor_id: int) -> None:
    if value < 1:
        raise OceanMastersStateError("The minimum squad threshold must be at least 1.")
    old = await bot_config_repo.get_ocean_masters_min_squads(conn)
    await bot_config_repo.set_ocean_masters_min_squads(conn, value)
    await audit_repo.record(
        conn,
        actor_id=actor_id,
        action="oceanmasters.set_min_squads",
        target_type="bot_config",
        target_id=constants.BOT_CONFIG_KEY_OCEAN_MASTERS_MIN_SQUADS,
        old_value={"value": old},
        new_value={"value": value},
    )


async def set_tie_rule(conn: asyncpg.Connection, rule: str, *, actor_id: int) -> None:
    if rule not in constants.ALL_CROSS_GAME_TIE_RULES:
        raise OceanMastersStateError(f"'{rule}' isn't a recognized tie-break rule.")
    old = await bot_config_repo.get_cross_game_tie_rule(conn)
    await bot_config_repo.set_cross_game_tie_rule(conn, rule)
    await audit_repo.record(
        conn,
        actor_id=actor_id,
        action="oceanmasters.set_tie_rule",
        target_type="bot_config",
        target_id=constants.BOT_CONFIG_KEY_CROSS_GAME_TIE_RULE,
        old_value={"value": old},
        new_value={"value": rule},
    )


async def create_tournament(
    conn: asyncpg.Connection,
    *,
    mode: OceanMastersMode,
    games: list[str],
    created_by: int,
    channels: ResolvedOceanMastersState | None = None,
) -> CreateResult:
    unique_games = list(dict.fromkeys(games))
    for game in unique_games:
        if game not in constants.MANAVA_GAMES:
            raise OceanMastersStateError(f"'{game}' isn't a recognized game.")
    if mode is OceanMastersMode.SINGLE_GAME and len(unique_games) != 1:
        raise OceanMastersStateError("Single-game mode needs exactly one game.")
    if mode is OceanMastersMode.CROSS_GAME and len(unique_games) < 2:
        raise OceanMastersStateError("Cross-game mode needs at least two different games.")

    async with conn.transaction():
        if mode is OceanMastersMode.CROSS_GAME:
            tie_rule = await bot_config_repo.get_cross_game_tie_rule(conn)
            if tie_rule is None:
                raise OceanMastersStateError(
                    "Cross-game mode is blocked until a tie-break rule is configured — "
                    "run /oceanmasters set-tie-rule first, or use Single-game."
                )

        active = await seasons_repo.get_active(conn)
        if active is None or active.phase != SeasonPhase.TOP32_PLAYOFFS:
            raise OceanMastersStateError(
                "Ocean Masters needs a published Top-32 first — run /season publish-top32."
            )

        entries = await season_qualifications_repo.get_top32_window(conn, active.id)
        if not entries or entries[0].seed is None:
            raise OceanMastersStateError("The Top-32 list isn't published yet — run /season publish-top32.")

        min_squads = await bot_config_repo.get_ocean_masters_min_squads(conn)
        tournament = await ocean_masters_repo.create_tournament(
            conn,
            season_id=active.id,
            mode=mode,
            games=unique_games,
            min_squads_required=min_squads,
            created_by=created_by,
        )

        bracket_size = _next_power_of_two(len(entries))
        seed_order = _standard_bracket_seed_order(bracket_size)
        squad_by_seed = {e.seed: e.squad_id for e in entries}
        pairings: list[tuple[int, int, UUID | None, UUID | None]] = []
        for i in range(0, bracket_size, 2):
            seed_a, seed_b = seed_order[i], seed_order[i + 1]
            pairings.append((seed_a, seed_b, squad_by_seed.get(seed_a), squad_by_seed.get(seed_b)))

        matches_created = await ocean_masters_repo.insert_round(conn, tournament.id, 1, pairings)
        await _resolve_byes_and_cascade(conn, tournament.id, 1, channels=channels)

        await audit_repo.record(
            conn,
            actor_id=created_by,
            action="oceanmasters.create",
            target_type="ocean_masters",
            target_id=str(tournament.id),
            new_value={"mode": mode.value, "games": unique_games, "matches_created": matches_created},
        )
    logger.info(
        "Ocean Masters tournament %s created for season %s (%s squads, bracket size %s)",
        tournament.id,
        active.season_number,
        len(entries),
        bracket_size,
    )
    return CreateResult(tournament_id=tournament.id, matches_created=matches_created)


async def launch_tournament(
    conn: asyncpg.Connection, tournament_id: UUID, *, actor_id: int, channels: ResolvedOceanMastersState | None
) -> tuple[OceanMasters, str | None]:
    """Launch never auto-triggers off the squad threshold, and never blocks
    on it either (client confirmed reaching it only signals readiness — the
    launch decision itself always stays manual). Below-threshold just
    surfaces a warning, doesn't stop the launch."""
    async with conn.transaction():
        tournament = await ocean_masters_repo.launch(conn, tournament_id, actor_id=actor_id)
        active_count = await squads_repo.count_active(conn)
        warning: str | None = None
        if tournament.min_squads_required is not None and active_count < tournament.min_squads_required:
            warning = (
                f"Only {active_count} active squad(s) — below the configured minimum of "
                f"{tournament.min_squads_required}. Launching anyway, since that threshold "
                f"is informational only; the launch decision is always manual."
            )
        await audit_repo.record(
            conn,
            actor_id=actor_id,
            action="oceanmasters.launch",
            target_type="ocean_masters",
            target_id=str(tournament_id),
            old_value={"status": "draft"},
            new_value={"status": "launched"},
        )
    if channels is not None:
        try:
            await channels.news.send(
                f"📣 **Ocean Masters is now live!** Follow the bracket in {channels.brackets.mention}."
            )
        except discord.DiscordException:
            logger.exception("Failed posting the Ocean Masters launch announcement to #premier-news")
    return tournament, warning


async def set_result(
    conn: asyncpg.Connection,
    match_id: UUID,
    *,
    winner_squad_id: UUID,
    actor_id: int,
    reason: str | None,
    channels: ResolvedOceanMastersState | None,
) -> MatchDecisionResult:
    """Direct staff entry of a match result — the standing-in-for-the-missing-
    contract path for Single-game, and the tie-break resolution path for
    Cross-game."""
    match = await ocean_masters_repo.get_match(conn, match_id)
    if match.status is not MatchStatus.PENDING:
        raise OceanMastersStateError("That match is already decided.")
    if winner_squad_id not in (match.squad_a_id, match.squad_b_id):
        raise OceanMastersStateError("That squad isn't one of the two in this match.")

    async with conn.transaction():
        decided = await ocean_masters_repo.decide_match(
            conn,
            match_id,
            winner_squad_id=winner_squad_id,
            status=MatchStatus.COMPLETED,
            decided_by=actor_id,
            reason=reason,
        )
        advanced, completed = await _try_advance_round(conn, match.tournament_id, match.round, channels=channels)
        await audit_repo.record(
            conn,
            actor_id=actor_id,
            action="oceanmasters.match.set_result",
            target_type="ocean_masters_match",
            target_id=str(match_id),
            old_value={"status": "pending"},
            new_value={"status": "completed", "winner_squad_id": str(winner_squad_id)},
            reason=reason,
        )
    return MatchDecisionResult(match=decided, round_advanced=advanced, tournament_completed=completed)


async def set_discipline_result(
    conn: asyncpg.Connection,
    match_id: UUID,
    *,
    game: str,
    winner_squad_id: UUID,
    actor_id: int,
    channels: ResolvedOceanMastersState | None,
) -> MatchDecisionResult:
    """Cross-game only: records one discipline's result. Once every
    configured game has a result, the match auto-resolves — one point per
    discipline win, higher total wins the matchup (client-approved base
    model). On a tie, the only implemented rule (`staff_manual`) leaves the
    match pending for /oceanmasters match set-result to break it."""
    match = await ocean_masters_repo.get_match(conn, match_id)
    if match.status is not MatchStatus.PENDING:
        raise OceanMastersStateError("That match is already decided.")
    if winner_squad_id not in (match.squad_a_id, match.squad_b_id):
        raise OceanMastersStateError("That squad isn't one of the two in this match.")
    tournament = await ocean_masters_repo.get_by_id(conn, match.tournament_id)
    if tournament.mode is not OceanMastersMode.CROSS_GAME:
        raise OceanMastersStateError("Discipline results only apply to Cross-game tournaments.")
    if game not in tournament.games:
        raise OceanMastersStateError(f"'{game}' isn't one of this tournament's games: {', '.join(tournament.games)}.")

    async with conn.transaction():
        updated = await ocean_masters_repo.set_discipline_result(conn, match_id, game, winner_squad_id)
        await audit_repo.record(
            conn,
            actor_id=actor_id,
            action="oceanmasters.match.set_discipline_result",
            target_type="ocean_masters_match",
            target_id=str(match_id),
            new_value={"game": game, "winner_squad_id": str(winner_squad_id)},
        )

        if len(updated.per_discipline_results) < len(tournament.games):
            return MatchDecisionResult(match=updated, round_advanced=False, tournament_completed=False)

        tally: dict[str, int] = {}
        for winner in updated.per_discipline_results.values():
            tally[winner] = tally.get(winner, 0) + 1
        ranked = sorted(tally.items(), key=lambda kv: kv[1], reverse=True)
        if len(ranked) > 1 and ranked[0][1] == ranked[1][1]:
            return MatchDecisionResult(match=updated, round_advanced=False, tournament_completed=False)

        overall_winner = UUID(ranked[0][0])
        decided = await ocean_masters_repo.decide_match(
            conn,
            match_id,
            winner_squad_id=overall_winner,
            status=MatchStatus.COMPLETED,
            decided_by=actor_id,
            reason="Cross-game: resolved from per-discipline results",
        )
        advanced, completed = await _try_advance_round(conn, match.tournament_id, match.round, channels=channels)
    return MatchDecisionResult(match=decided, round_advanced=advanced, tournament_completed=completed)


async def override_match(
    conn: asyncpg.Connection,
    match_id: UUID,
    *,
    outcome: MatchStatus,
    winner_squad_id: UUID,
    actor_id: int,
    reason: str,
    channels: ResolvedOceanMastersState | None,
) -> MatchDecisionResult:
    """The staff override suite: technical loss, no-show, disqualified,
    forfeit — every one of them still names who advances, and every one is
    audit-logged with actor/timestamp/old/new/reason."""
    if outcome not in OVERRIDE_MATCH_STATUSES:
        raise OceanMastersStateError("Not a valid override outcome.")
    match = await ocean_masters_repo.get_match(conn, match_id)
    if match.status is not MatchStatus.PENDING:
        raise OceanMastersStateError("That match is already decided.")
    if winner_squad_id not in (match.squad_a_id, match.squad_b_id):
        raise OceanMastersStateError("That squad isn't one of the two in this match.")

    async with conn.transaction():
        decided = await ocean_masters_repo.decide_match(
            conn, match_id, winner_squad_id=winner_squad_id, status=outcome, decided_by=actor_id, reason=reason
        )
        advanced, completed = await _try_advance_round(conn, match.tournament_id, match.round, channels=channels)
        await audit_repo.record(
            conn,
            actor_id=actor_id,
            action="oceanmasters.match.override",
            target_type="ocean_masters_match",
            target_id=str(match_id),
            old_value={"status": "pending"},
            new_value={"status": outcome.value, "winner_squad_id": str(winner_squad_id)},
            reason=reason,
        )
    return MatchDecisionResult(match=decided, round_advanced=advanced, tournament_completed=completed)


def in_bracket_order(matches: Sequence[OceanMastersMatch], round_number: int) -> list[OceanMastersMatch]:
    """One round's matches in bracket position order (top of the bracket to
    bottom), so adjacent pairs feed the same next-round match. A match's
    position is fixed by the block of the standard seed order its seeds come
    from: round r covers blocks of 2^r seeds. NOT the same as sorting by
    seed_a — e.g. in an 8-squad bracket that would pair seed 1's and seed 2's
    winners in the semi-final."""
    if not matches:
        return []
    block = 2**round_number
    order = {seed: i for i, seed in enumerate(_standard_bracket_seed_order(len(matches) * block))}
    return sorted(matches, key=lambda m: order.get(m.seed_a, m.seed_a) // block)


def find_next_match(
    match: OceanMastersMatch, next_round_matches: Sequence[OceanMastersMatch]
) -> OceanMastersMatch | None:
    """The next-round match this match's current winner advanced into."""
    if match.winner_squad_id is None:
        return None
    for nm in next_round_matches:
        if match.winner_squad_id in (nm.squad_a_id, nm.squad_b_id):
            return nm
    return None


def correction_blocker(match: OceanMastersMatch, next_round_matches: Sequence[OceanMastersMatch]) -> str | None:
    """Why correct-result can't change this match, or None if it can. A
    result stays correctable until the match it fed into has been played;
    the final stays correctable even after the champion was announced."""
    if match.status is MatchStatus.PENDING:
        return "This match hasn't been decided yet — use /oceanmasters match set-result."
    if match.squad_a_id is None or match.squad_b_id is None:
        return "Byes are decided automatically and can't be corrected."
    if not next_round_matches:
        return None
    next_match = find_next_match(match, next_round_matches)
    if next_match is None:
        return "Couldn't find the next-round match this result fed into. Contact support for a manual fix."
    if next_match.status is not MatchStatus.PENDING:
        return (
            f"The Round {next_match.round} match this result fed into already has a result, so correcting it "
            "would mean unwinding that match too. Contact support for a manual fix."
        )
    if next_match.per_discipline_results:
        return (
            f"Discipline results have already been recorded for the Round {next_match.round} match this result "
            "fed into, so it can't be corrected here. Contact support for a manual fix."
        )
    return None


async def correct_result(
    conn: asyncpg.Connection,
    match_id: UUID,
    *,
    winner_squad_id: UUID,
    actor_id: int,
    reason: str,
    channels: ResolvedOceanMastersState | None,
) -> CorrectionResult:
    """'Result correction' / 'integration-failure override' — the Technical
    Scope lists these alongside technical loss/no-show/DQ/forfeit as part of
    the same staff override suite. Fixes a match that was already decided:
    if the next round already exists, the corrected winner replaces the
    wrongly-advanced squad in its next match (as long as that match hasn't
    been played); if it's the final, the champion is swapped and the season's
    Ocean Masters standings are refreshed. Deliberately posts nothing to the
    public tournament channels — the client hasn't asked for correction
    notices; `channels` is kept for signature parity with the other paths."""
    match = await ocean_masters_repo.get_match(conn, match_id)
    if match.status is MatchStatus.PENDING:
        raise OceanMastersStateError("This match hasn't been decided yet — use /oceanmasters match set-result.")
    if winner_squad_id not in (match.squad_a_id, match.squad_b_id):
        raise OceanMastersStateError("That squad isn't one of the two in this match.")
    next_round_matches = await ocean_masters_repo.get_round_matches(conn, match.tournament_id, match.round + 1)
    blocker = correction_blocker(match, next_round_matches)
    if blocker is not None:
        raise OceanMastersStateError(blocker)

    old_winner = match.winner_squad_id
    assert old_winner is not None
    tournament = await ocean_masters_repo.get_by_id(conn, match.tournament_id)
    winner_changed = winner_squad_id != old_winner
    next_match = find_next_match(match, next_round_matches)
    is_completed_final = not next_round_matches and tournament.status is OceanMastersStatus.COMPLETED

    async with conn.transaction():
        decided = await ocean_masters_repo.correct_match(
            conn, match_id, winner_squad_id=winner_squad_id, decided_by=actor_id, reason=reason
        )
        updated_next: OceanMastersMatch | None = None
        if next_match is not None and winner_changed:
            new_seed = match.seed_a if winner_squad_id == match.squad_a_id else match.seed_b
            updated_next = await ocean_masters_repo.replace_match_squad(
                conn, next_match.id, old_squad_id=old_winner, new_squad_id=winner_squad_id, new_seed=new_seed
            )
        champion_changed = is_completed_final and winner_changed
        if champion_changed:
            await ocean_masters_repo.set_champion(conn, tournament.id, winner_squad_id=winner_squad_id)
            await season_history_repo.refresh_ocean_masters_standings(conn, tournament.season_id)
        await audit_repo.record(
            conn,
            actor_id=actor_id,
            action="oceanmasters.match.correct_result",
            target_type="ocean_masters_match",
            target_id=str(match_id),
            old_value={"status": match.status.value, "winner_squad_id": str(old_winner)},
            new_value={
                "status": "completed",
                "winner_squad_id": str(winner_squad_id),
                "next_match_id": str(updated_next.id) if updated_next else None,
                "champion_changed": champion_changed,
            },
            reason=reason,
        )

    return CorrectionResult(match=decided, next_match=updated_next, champion_changed=champion_changed)


async def _resolve_byes_and_cascade(
    conn: asyncpg.Connection, tournament_id: UUID, round_number: int, *, channels: ResolvedOceanMastersState | None
) -> None:
    """A squad count that isn't a power of 2 means some round-1 slots are
    byes (one side empty) — the real squad advances automatically. Runs
    after every round is created so a bye cascades straight through in a
    very small bracket."""
    matches = await ocean_masters_repo.get_round_matches(conn, tournament_id, round_number)
    for m in matches:
        if m.status is MatchStatus.PENDING and (m.squad_a_id is None) != (m.squad_b_id is None):
            winner = m.squad_a_id if m.squad_a_id is not None else m.squad_b_id
            assert winner is not None
            await ocean_masters_repo.decide_match(
                conn,
                m.id,
                winner_squad_id=winner,
                status=MatchStatus.COMPLETED,
                decided_by=_SYSTEM_ACTOR_ID,
                reason="Bye — uneven bracket size",
            )
    await _try_advance_round(conn, tournament_id, round_number, channels=channels)


async def _try_advance_round(
    conn: asyncpg.Connection, tournament_id: UUID, round_number: int, *, channels: ResolvedOceanMastersState | None
) -> tuple[bool, bool]:
    """Returns (round_advanced, tournament_completed). No-ops if the round
    isn't fully decided yet."""
    matches = in_bracket_order(
        await ocean_masters_repo.get_round_matches(conn, tournament_id, round_number), round_number
    )
    if any(m.winner_squad_id is None for m in matches):
        return False, False

    if len(matches) == 1:
        final = matches[0]
        winner = final.winner_squad_id
        assert winner is not None
        await ocean_masters_repo.mark_completed(conn, tournament_id, winner_squad_id=winner)
        if channels is not None:
            winner_name = final.squad_a_name if winner == final.squad_a_id else final.squad_b_name
            try:
                await channels.history.send(f"🏆 **Ocean Masters champion: {winner_name}**")
            except discord.DiscordException:
                logger.exception("Failed posting the Ocean Masters final result to #premier-history")
        return False, True

    next_round = round_number + 1
    pairings: list[tuple[int, int, UUID | None, UUID | None]] = []
    for i in range(0, len(matches), 2):
        m1, m2 = matches[i], matches[i + 1]
        seed1 = m1.seed_a if m1.winner_squad_id == m1.squad_a_id else m1.seed_b
        seed2 = m2.seed_a if m2.winner_squad_id == m2.squad_a_id else m2.seed_b
        pairings.append((seed1, seed2, m1.winner_squad_id, m2.winner_squad_id))
    await ocean_masters_repo.insert_round(conn, tournament_id, next_round, pairings)
    if channels is not None:
        try:
            lines = [f"**Round {next_round} matchups:**"] + [f"#{p[0]} v #{p[1]}" for p in pairings]
            await channels.brackets.send("\n".join(lines))
        except discord.DiscordException:
            logger.exception("Failed posting the Ocean Masters round update to #premier-brackets")
    await _resolve_byes_and_cascade(conn, tournament_id, next_round, channels=channels)
    return True, False
