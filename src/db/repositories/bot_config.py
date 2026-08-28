from __future__ import annotations

import json
from typing import Any

import asyncpg

from src import constants


async def get_value(conn: asyncpg.Connection, key: str, default: Any) -> Any:
    row = await conn.fetchrow("select value from bot_config where key = $1", key)
    if row is None:
        return default
    return json.loads(row["value"]) if isinstance(row["value"], str) else row["value"]


async def set_value(conn: asyncpg.Connection, key: str, value: Any) -> None:
    await conn.execute(
        """
        insert into bot_config (key, value, updated_at)
        values ($1, $2::jsonb, now())
        on conflict (key) do update set value = $2::jsonb, updated_at = now()
        """,
        key,
        json.dumps(value),
    )


async def get_excluded_channel_ids(conn: asyncpg.Connection) -> set[int]:
    raw = await get_value(conn, constants.BOT_CONFIG_KEY_XP_EXCLUDED_CHANNELS, [])
    return {int(v) for v in raw}


async def set_excluded_channel_ids(conn: asyncpg.Connection, channel_ids: set[int]) -> None:
    await set_value(conn, constants.BOT_CONFIG_KEY_XP_EXCLUDED_CHANNELS, sorted(channel_ids))
