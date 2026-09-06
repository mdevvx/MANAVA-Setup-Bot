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


async def get_application_review_channels(conn: asyncpg.Connection) -> dict[str, int]:
    """{app_type value -> channel id} overrides for where each application type's
    review embed is posted. Missing key -> use the default #applications-review."""
    raw = await get_value(conn, constants.BOT_CONFIG_KEY_APP_REVIEW_CHANNELS, {})
    return {str(k): int(v) for k, v in raw.items() if v}


async def set_application_review_channel(
    conn: asyncpg.Connection, app_type_value: str, channel_id: int | None
) -> None:
    current = await get_application_review_channels(conn)
    if channel_id is None:
        current.pop(app_type_value, None)
    else:
        current[app_type_value] = channel_id
    await set_value(conn, constants.BOT_CONFIG_KEY_APP_REVIEW_CHANNELS, current)
