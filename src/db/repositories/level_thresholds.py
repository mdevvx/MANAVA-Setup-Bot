from __future__ import annotations

import asyncpg

from src.errors import BotUserError


async def get_all(conn: asyncpg.Connection) -> dict[int, int]:
    """Returns {level: lifetime_squad_xp_required} for levels 2-7."""
    rows = await conn.fetch("select level, lifetime_squad_xp_required from level_thresholds order by level")
    return {row["level"]: row["lifetime_squad_xp_required"] for row in rows}


async def set_threshold(conn: asyncpg.Connection, level: int, xp_required: int, *, updated_by: int) -> None:
    if not (2 <= level <= 7):
        raise BotUserError("Level must be between 2 and 7 (level 1 has no threshold).")
    if xp_required < 0:
        raise BotUserError("XP threshold can't be negative.")
    await conn.execute(
        """
        insert into level_thresholds (level, lifetime_squad_xp_required, updated_by, updated_at)
        values ($1, $2, $3, now())
        on conflict (level) do update set lifetime_squad_xp_required = $2, updated_by = $3, updated_at = now()
        """,
        level,
        xp_required,
        updated_by,
    )
