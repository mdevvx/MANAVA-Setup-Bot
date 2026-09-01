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
from src.db.repositories import seasons as seasons_repo
from src.db.repositories import squad_xp as squad_xp_repo
from src.models.season import Season, SeasonResetResult

logger = logging.getLogger(__name__)


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
    active."""
    async with conn.transaction():
        active = await seasons_repo.get_active(conn)
        ended_number: int | None = None
        if active is not None:
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
