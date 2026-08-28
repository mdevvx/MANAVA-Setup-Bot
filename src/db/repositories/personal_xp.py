from __future__ import annotations

import asyncpg

from src.models.xp import PersonalXp


def _row_to_personal_xp(row: asyncpg.Record) -> PersonalXp:
    return PersonalXp(
        discord_user_id=row["discord_user_id"],
        verified_player=row["verified_player"],
        manava_user_id=row["manava_user_id"],
        lifetime_xp=row["lifetime_xp"],
        season_xp=row["season_xp"],
    )


async def ensure_row(conn: asyncpg.Connection, discord_user_id: int) -> None:
    await conn.execute(
        "insert into personal_xp (discord_user_id) values ($1) on conflict (discord_user_id) do nothing",
        discord_user_id,
    )


async def get(conn: asyncpg.Connection, discord_user_id: int) -> PersonalXp:
    row = await conn.fetchrow("select * from personal_xp where discord_user_id = $1", discord_user_id)
    if row is None:
        return PersonalXp(
            discord_user_id=discord_user_id, verified_player=False, manava_user_id=None, lifetime_xp=0, season_xp=0
        )
    return _row_to_personal_xp(row)


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


async def add_xp(conn: asyncpg.Connection, discord_user_id: int, amount: int) -> PersonalXp:
    """The real Unified Personal XP accumulator: every XP gain increments
    lifetime_xp and season_xp together, from either source (Discord activity
    or MANAVA events) — there is exactly one counter pair, never two
    unsynchronized ones."""
    await ensure_row(conn, discord_user_id)
    row = await conn.fetchrow(
        """
        update personal_xp
        set lifetime_xp = lifetime_xp + $2, season_xp = season_xp + $2, updated_at = now()
        where discord_user_id = $1
        returning *
        """,
        discord_user_id,
        amount,
    )
    assert row is not None
    return _row_to_personal_xp(row)


async def set_manava_user_id(conn: asyncpg.Connection, discord_user_id: int, manava_user_id: str) -> None:
    """STUB manual account-linking override: replaced by the real MANAVA
    account-linking integration in Phase 3. Stays available as an admin/support
    utility even after that lands, same pattern as verified_player."""
    await ensure_row(conn, discord_user_id)
    await conn.execute(
        "update personal_xp set manava_user_id = $2, updated_at = now() where discord_user_id = $1",
        discord_user_id,
        manava_user_id,
    )


async def get_discord_user_id_by_manava_id(conn: asyncpg.Connection, manava_user_id: str) -> int | None:
    row = await conn.fetchrow(
        "select discord_user_id from personal_xp where manava_user_id = $1", manava_user_id
    )
    return int(row["discord_user_id"]) if row else None
