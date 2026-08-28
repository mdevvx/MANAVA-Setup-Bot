from __future__ import annotations

import asyncpg


async def reserve(conn: asyncpg.Connection, *, event_id: str, manava_user_id: str, event_type: str) -> bool:
    """Atomically claims event_id BEFORE any XP is granted. Returns True if this
    call is the one that claimed it (proceed with processing), False if it was
    already claimed (duplicate — stop immediately, grant nothing).

    This two-phase reserve-then-finalize design (rather than granting XP and
    inserting afterward) is what makes duplicate delivery race-safe: the
    unique constraint on event_id resolves the race at the reservation step,
    before any XP has been computed or applied, not after.
    """
    row = await conn.fetchrow(
        """
        insert into processed_events (event_id, manava_user_id, event_type, xp_granted)
        values ($1, $2, $3, 0)
        on conflict (event_id) do nothing
        returning event_id
        """,
        event_id,
        manava_user_id,
        event_type,
    )
    return row is not None


async def finalize(conn: asyncpg.Connection, *, event_id: str, discord_user_id: int | None, xp_granted: int) -> None:
    await conn.execute(
        "update processed_events set discord_user_id = $2, xp_granted = $3 where event_id = $1",
        event_id,
        discord_user_id,
        xp_granted,
    )
