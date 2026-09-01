from __future__ import annotations

from uuid import UUID

import asyncpg

from src.models.xp import SquadXp


def _row_to_squad_xp(row: asyncpg.Record) -> SquadXp:
    return SquadXp(squad_id=row["squad_id"], lifetime_xp=row["lifetime_xp"], season_xp=row["season_xp"])


async def ensure_row(conn: asyncpg.Connection, squad_id: UUID) -> None:
    await conn.execute(
        "insert into squad_xp (squad_id) values ($1) on conflict (squad_id) do nothing", squad_id
    )


async def get(conn: asyncpg.Connection, squad_id: UUID) -> SquadXp:
    row = await conn.fetchrow("select * from squad_xp where squad_id = $1", squad_id)
    if row is None:
        return SquadXp(squad_id=squad_id, lifetime_xp=0, season_xp=0)
    return _row_to_squad_xp(row)


async def add_xp(conn: asyncpg.Connection, squad_id: UUID, amount: int) -> SquadXp:
    await ensure_row(conn, squad_id)
    row = await conn.fetchrow(
        """
        update squad_xp
        set lifetime_xp = lifetime_xp + $2, season_xp = season_xp + $2, updated_at = now()
        where squad_id = $1
        returning *
        """,
        squad_id,
        amount,
    )
    assert row is not None
    return _row_to_squad_xp(row)


async def reset_all_season_xp(conn: asyncpg.Connection) -> int:
    """Start New Season: zero every squad's Season Squad XP. Lifetime Squad XP
    is never touched, and per-member contributed_xp is deliberately left alone
    (it's a per-stint lifetime figure, not seasonal). Returns rows changed."""
    result = await conn.execute("update squad_xp set season_xp = 0, updated_at = now() where season_xp <> 0")
    return int(result.split()[-1]) if result else 0


async def get_global_leaderboard(conn: asyncpg.Connection, limit: int = 100) -> list[asyncpg.Record]:
    """Active squads ranked by Season Squad XP, most efficient single query
    (no N+1) — safe at ~70 squads."""
    return list(
        await conn.fetch(
            """
            select
                s.id as squad_id,
                s.name as squad_name,
                coalesce(sx.season_xp, 0) as season_xp,
                coalesce(sx.lifetime_xp, 0) as lifetime_xp,
                row_number() over (order by coalesce(sx.season_xp, 0) desc, s.created_at asc) as rank
            from squads s
            left join squad_xp sx on sx.squad_id = s.id
            where s.status = 'active'
            order by coalesce(sx.season_xp, 0) desc, s.created_at asc
            limit $1
            """,
            limit,
        )
    )
