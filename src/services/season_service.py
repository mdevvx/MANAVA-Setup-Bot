"""Season lifecycle: Start Season, End Season, Start New Season.

Start New Season is the only one with side effects beyond season_state: it
zeroes every Personal Season XP and Season Squad XP counter in a single
transaction. Lifetime counters (Personal Lifetime XP, Lifetime Squad XP) and
per-member contributed_xp are never touched by a season reset.
"""

from __future__ import annotations

import logging

import asyncpg

from src.db.repositories import audit_logs as audit_repo
from src.db.repositories import personal_xp as personal_xp_repo
from src.db.repositories import season_history as season_history_repo
from src.db.repositories import season_qualifications as season_qualifications_repo
from src.db.repositories import seasons as seasons_repo
from src.db.repositories import squad_xp as squad_xp_repo
from src.errors import SeasonStateError
from src.models.season import (
    CompleteResult,
    LockResult,
    PublishResult,
    Season,
    SeasonPhase,
    SeasonResetResult,
)

logger = logging.getLogger(__name__)

_PAST_QUALIFICATION_MESSAGE = (
    "This season is past Qualification — use `/season complete` to close it out properly "
    "(it also records the final standings), then open the next one with `/season new`."
)


def _require_endable(active: Season | None, *, command: str) -> Season:
    """Shared guard for /season end and /season new: both close out the
    active season via the plain (no-history-snapshot) path, which is only
    allowed while a season hasn't gone through Qualification Lock yet.
    Client decision (2026-09-23): once locked/published, staff must use
    /season complete instead, so an official season can never be closed
    without its history snapshot."""
    if active is None:
        raise SeasonStateError(f"There's no active season to {command}.")
    if active.phase != SeasonPhase.QUALIFICATION:
        raise SeasonStateError(_PAST_QUALIFICATION_MESSAGE)
    return active


async def get_current(conn: asyncpg.Connection) -> Season | None:
    return await seasons_repo.get_current(conn)


async def start_season(conn: asyncpg.Connection, *, actor_id: int) -> Season:
    async with conn.transaction():
        season = await seasons_repo.start(conn, actor_id=actor_id)
        await audit_repo.record(
            conn,
            actor_id=actor_id,
            action="season.start",
            target_type="season",
            target_id=str(season.id),
            new_value={"season_number": season.season_number},
        )
    logger.info("Season %s started by %s", season.season_number, actor_id)
    return season


async def end_season(conn: asyncpg.Connection, *, actor_id: int) -> Season:
    async with conn.transaction():
        active = await seasons_repo.get_active(conn)
        _require_endable(active, command="end")
        season = await seasons_repo.end_active(conn, actor_id=actor_id)
        await audit_repo.record(
            conn,
            actor_id=actor_id,
            action="season.end",
            target_type="season",
            target_id=str(season.id),
            old_value={"status": "active"},
            new_value={"status": "ended", "season_number": season.season_number},
        )
    logger.info("Season %s ended by %s", season.season_number, actor_id)
    return season


async def start_new_season(conn: asyncpg.Connection, *, actor_id: int) -> SeasonResetResult:
    """End the current active season (if any), zero all season XP, open a fresh
    season — atomically. Safe to run whether or not a season is currently
    active. Blocked (same as /season end) once the active season is past
    Qualification — run /season complete first."""
    async with conn.transaction():
        active = await seasons_repo.get_active(conn)
        ended_number: int | None = None
        if active is not None:
            _require_endable(active, command="start a new season")
            ended = await seasons_repo.end_active(conn, actor_id=actor_id)
            ended_number = ended.season_number

        personal_reset = await personal_xp_repo.reset_all_season_xp(conn)
        squad_reset = await squad_xp_repo.reset_all_season_xp(conn)

        new_season = await seasons_repo.start(conn, actor_id=actor_id)

        result = SeasonResetResult(
            ended_season_number=ended_number,
            new_season_number=new_season.season_number,
            personal_rows_reset=personal_reset,
            squad_rows_reset=squad_reset,
        )
        await audit_repo.record(
            conn,
            actor_id=actor_id,
            action="season.start_new",
            target_type="season",
            target_id=str(new_season.id),
            old_value={"ended_season_number": ended_number},
            new_value={
                "new_season_number": result.new_season_number,
                "personal_rows_reset": result.personal_rows_reset,
                "squad_rows_reset": result.squad_rows_reset,
            },
        )
    logger.info(
        "Start New Season by %s: ended season %s, opened season %s, reset %s personal + %s squad rows",
        actor_id,
        ended_number,
        result.new_season_number,
        result.personal_rows_reset,
        result.squad_rows_reset,
    )
    return result


async def lock_qualification(conn: asyncpg.Connection, *, actor_id: int) -> LockResult:
    """/season lock: Qualification -> Qualification Lock. Snapshots every
    active squad's current ranking (not only the top 32) into
    season_qualifications, freezing Season + Lifetime Squad XP as of now."""
    async with conn.transaction():
        active = await seasons_repo.get_active(conn)
        if active is None:
            raise SeasonStateError("There's no active season to lock.")
        season = await seasons_repo.lock(conn, active.id, actor_id=actor_id)
        squads_ranked = await season_qualifications_repo.snapshot_at_lock(conn, season.id)
        result = LockResult(season_id=season.id, season_number=season.season_number, squads_ranked=squads_ranked)
        await audit_repo.record(
            conn,
            actor_id=actor_id,
            action="season.lock",
            target_type="season",
            target_id=str(season.id),
            old_value={"phase": "qualification"},
            new_value={"phase": "qualification_lock", "squads_ranked": squads_ranked},
        )
    logger.info("Season %s locked by %s: %s squads ranked", season.season_number, actor_id, squads_ranked)
    return result


async def publish_top32(conn: asyncpg.Connection, *, actor_id: int) -> PublishResult:
    """/season publish-top32: Qualification Lock -> Top-32 Playoffs. Assigns
    fresh seeds 1..N over whichever squads are still `qualified` (in rank
    order) and freezes the list as official — the Confirm/Publish step."""
    async with conn.transaction():
        active = await seasons_repo.get_active(conn)
        if active is None:
            raise SeasonStateError("There's no active season to publish.")
        season = await seasons_repo.advance_to_playoffs(conn, active.id, actor_id=actor_id)
        seeds_assigned = await season_qualifications_repo.assign_seeds_at_publish(conn, season.id)
        result = PublishResult(
            season_id=season.id, season_number=season.season_number, seeds_assigned=seeds_assigned
        )
        await audit_repo.record(
            conn,
            actor_id=actor_id,
            action="season.publish_top32",
            target_type="season",
            target_id=str(season.id),
            old_value={"phase": "qualification_lock"},
            new_value={"phase": "top32_playoffs", "seeds_assigned": seeds_assigned},
        )
    logger.info("Season %s Top-32 published by %s: %s seeds assigned", season.season_number, actor_id, seeds_assigned)
    return result


async def complete_season(conn: asyncpg.Connection, *, actor_id: int) -> CompleteResult:
    """/season complete: persists the final Squad Leaderboard snapshot into
    season_history and closes the season out properly. Allowed from any
    non-terminal phase — a season that never locked (no Top-32/Ocean Masters
    this cycle) can still be completed, it just records everyone as
    not-qualified. Does NOT reset XP or open a new season — that stays
    /season new's job, unchanged."""
    async with conn.transaction():
        active = await seasons_repo.get_active(conn)
        if active is None:
            raise SeasonStateError("There's no active season to complete.")
        season = await seasons_repo.mark_complete(conn, active.id, actor_id=actor_id)
        squads_recorded = await season_history_repo.snapshot_all_active_squads(conn, season.id)
        result = CompleteResult(
            season_id=season.id, season_number=season.season_number, squads_recorded=squads_recorded
        )
        await audit_repo.record(
            conn,
            actor_id=actor_id,
            action="season.complete",
            target_type="season",
            target_id=str(season.id),
            old_value={"status": "active"},
            new_value={"status": "ended", "phase": "season_complete", "squads_recorded": squads_recorded},
        )
    logger.info("Season %s completed by %s: %s squads recorded", season.season_number, actor_id, squads_recorded)
    return result
