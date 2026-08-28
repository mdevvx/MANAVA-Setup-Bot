from __future__ import annotations

import asyncpg

from src import constants
from src.errors import BotUserError


async def get_all(conn: asyncpg.Connection) -> dict[str, int]:
    rows = await conn.fetch("select key, value from xp_config")
    return {row["key"]: row["value"] for row in rows}


async def get_value(conn: asyncpg.Connection, key: str) -> int:
    row = await conn.fetchrow("select value from xp_config where key = $1", key)
    return int(row["value"]) if row else 0


async def set_value(conn: asyncpg.Connection, key: str, value: int, *, updated_by: int) -> None:
    if key not in constants.ALL_XP_CONFIG_KEYS:
        raise BotUserError(f"Unknown XP config key '{key}'. Valid keys: {', '.join(constants.ALL_XP_CONFIG_KEYS)}")
    await conn.execute(
        """
        insert into xp_config (key, value, updated_by, updated_at)
        values ($1, $2, $3, now())
        on conflict (key) do update set value = $2, updated_by = $3, updated_at = now()
        """,
        key,
        value,
        updated_by,
    )
