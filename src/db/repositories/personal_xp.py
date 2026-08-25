from __future__ import annotations

import asyncpg


async def ensure_row(conn: asyncpg.Connection, discord_user_id: int) -> None:
    await conn.execute(
        "insert into personal_xp (discord_user_id) values ($1) on conflict (discord_user_id) do nothing",
        discord_user_id,
    )


async def get_verified_player(conn: asyncpg.Connection, discord_user_id: int) -> bool:
    row = await conn.fetchrow(
        "select verified_player from personal_xp where discord_user_id = $1", discord_user_id
    )
    return bool(row["verified_player"]) if row else False


async def set_verified_player(conn: asyncpg.Connection, discord_user_id: int, verified: bool) -> None:
    """STUB: replaced by MANAVA account-linking integration in Phase 3.
    The manual override stays available as an admin/support utility even after that lands."""
    await ensure_row(conn, discord_user_id)
    await conn.execute(
        "update personal_xp set verified_player = $2, updated_at = now() where discord_user_id = $1",
        discord_user_id,
        verified,
    )


async def get_lifetime_xp(conn: asyncpg.Connection, discord_user_id: int) -> int:
    row = await conn.fetchrow(
        "select lifetime_xp from personal_xp where discord_user_id = $1", discord_user_id
    )
    return int(row["lifetime_xp"]) if row else 0


async def add_lifetime_xp(conn: asyncpg.Connection, discord_user_id: int, amount: int) -> int:
    """STUB: Discord-only accumulator; replaced by the full Unified XP system in Phase 2."""
    await ensure_row(conn, discord_user_id)
    row = await conn.fetchrow(
        """
        update personal_xp
        set lifetime_xp = lifetime_xp + $2, updated_at = now()
        where discord_user_id = $1
        returning lifetime_xp
        """,
        discord_user_id,
        amount,
    )
    assert row is not None
    return int(row["lifetime_xp"])
