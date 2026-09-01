from __future__ import annotations

import asyncpg

from src import constants
from src.errors import SeasonStateError
from src.models.season import Season, SeasonStatus


def _row_to_season(row: asyncpg.Record) -> Season:
    return Season(
        id=row["id"],
        season_number=row["season_number"],
        status=SeasonStatus(row["status"]),
        started_at=row["started_at"],
        started_by=row["started_by"],
        ended_at=row["ended_at"],
        ended_by=row["ended_by"],
    )


async def get_active(conn: asyncpg.Connection) -> Season | None:
    row = await conn.fetchrow("select * from season_state where status = 'active'")
    return _row_to_season(row) if row else None


async def get_current(conn: asyncpg.Connection) -> Season | None:
    """The active season if there is one, otherwise the most recently started
    season (so `/season status` still has something to show between seasons)."""
    row = await conn.fetchrow(
        "select * from season_state order by (status = 'active') desc, season_number desc limit 1"
    )
    return _row_to_season(row) if row else None


async def _next_number(conn: asyncpg.Connection) -> int:
    row = await conn.fetchrow("select max(season_number) as n from season_state")
    current_max = row["n"] if row and row["n"] is not None else None
    return constants.FIRST_SEASON_NUMBER if current_max is None else current_max + 1


async def start(conn: asyncpg.Connection, *, actor_id: int) -> Season:
    """Opens a new active season. Fails if one is already active — the caller
    should End it first, or use start_new (season_service) which does both."""
    try:
        row = await conn.fetchrow(
            """
            insert into season_state (season_number, status, started_by)
            values ($1, 'active', $2)
            returning *
            """,
            await _next_number(conn),
            actor_id,
        )
    except asyncpg.UniqueViolationError as exc:
        raise SeasonStateError(
            "A season is already active. End it first (or use Start New Season, which does both)."
        ) from exc
    assert row is not None
    return _row_to_season(row)


async def end_active(conn: asyncpg.Connection, *, actor_id: int) -> Season:
    row = await conn.fetchrow(
        """
        update season_state
        set status = 'ended', ended_at = now(), ended_by = $1
        where status = 'active'
        returning *
        """,
        actor_id,
    )
    if row is None:
        raise SeasonStateError("There's no active season to end.")
    return _row_to_season(row)
