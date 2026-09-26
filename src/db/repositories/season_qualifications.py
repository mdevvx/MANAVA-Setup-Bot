from __future__ import annotations

from uuid import UUID

import asyncpg

from src.errors import Top32EntryNotFoundError
from src.models.season import QualificationEntry, QualificationEntryStatus

_TOP32_LIMIT = 32


def _row_to_entry(row: asyncpg.Record) -> QualificationEntry:
    return QualificationEntry(
        season_id=row["season_id"],
        squad_id=row["squad_id"],
        squad_name=row["squad_name"],
        rank=row["rank"],
        season_xp_snapshot=row["season_xp_snapshot"],
        lifetime_xp_snapshot=row["lifetime_xp_snapshot"],
        status=QualificationEntryStatus(row["status"]),
        seed=row["seed"],
        decided_by=row["decided_by"],
        decided_at=row["decided_at"],
        decided_reason=row["decided_reason"],
    )


async def snapshot_at_lock(conn: asyncpg.Connection, season_id: UUID) -> int:
    """Ranks every currently active squad (not only the top 32) by Season
    Squad XP desc, Lifetime Squad XP desc as the tie-break, `created_at` asc
    as a final deterministic tiebreak — and freezes both XP figures into the
    snapshot. Returns the number of squads ranked."""
    rows = await conn.fetch(
        """
        insert into season_qualifications (season_id, squad_id, rank, season_xp_snapshot, lifetime_xp_snapshot)
        select
            $1,
            s.id,
            row_number() over (
                order by coalesce(sx.season_xp, 0) desc, coalesce(sx.lifetime_xp, 0) desc, s.created_at asc
            ),
            coalesce(sx.season_xp, 0),
            coalesce(sx.lifetime_xp, 0)
        from squads s
        left join squad_xp sx on sx.squad_id = s.id
        where s.status = 'active'
        returning squad_id
        """,
        season_id,
    )
    return len(rows)


async def get_top32_window(conn: asyncpg.Connection, season_id: UUID) -> list[QualificationEntry]:
    """The CURRENT Top-32: rows still `qualified`, ordered by rank, first 32.
    A withdrawal/disqualification is simply excluded here, so whoever was
    next in rank order slides into the window automatically."""
    rows = await conn.fetch(
        """
        select sq.*, s.name as squad_name
        from season_qualifications sq
        join squads s on s.id = sq.squad_id
        where sq.season_id = $1 and sq.status = 'qualified'
        order by sq.rank
        limit $2
        """,
        season_id,
        _TOP32_LIMIT,
    )
    return [_row_to_entry(r) for r in rows]


async def get_by_squad_name(conn: asyncpg.Connection, season_id: UUID, squad_name: str) -> QualificationEntry:
    row = await conn.fetchrow(
        """
        select sq.*, s.name as squad_name
        from season_qualifications sq
        join squads s on s.id = sq.squad_id
        where sq.season_id = $1 and s.name_lower = lower($2)
        """,
        season_id,
        squad_name,
    )
    if row is None:
        raise Top32EntryNotFoundError(squad_name)
    return _row_to_entry(row)


async def search_qualified_squad_names(
    conn: asyncpg.Connection, season_id: UUID, *, name_contains: str, limit: int = 25
) -> list[str]:
    """Backs the `/season top32 withdraw|disqualify` autocomplete — only
    squads actually on this season's locked list, not every active squad."""
    rows = await conn.fetch(
        """
        select s.name
        from season_qualifications sq
        join squads s on s.id = sq.squad_id
        where sq.season_id = $1 and s.name ilike $2
        order by sq.rank
        limit $3
        """,
        season_id,
        f"%{name_contains}%",
        limit,
    )
    return [r["name"] for r in rows]


async def set_status(
    conn: asyncpg.Connection,
    season_id: UUID,
    squad_name: str,
    *,
    new_status: QualificationEntryStatus,
    decided_by: int,
    reason: str | None,
) -> QualificationEntry:
    """Withdraw or disqualify — only ever moves a row OFF 'qualified'. The
    caller (top32_service) is responsible for checking whether the current
    phase allows this action at all."""
    row = await conn.fetchrow(
        """
        update season_qualifications sq
        set status = $3, decided_by = $4, decided_at = now(), decided_reason = $5
        from squads s
        where sq.season_id = $1 and s.id = sq.squad_id and s.name_lower = lower($2)
          and sq.status = 'qualified'
        returning sq.*, s.name as squad_name
        """,
        season_id,
        squad_name,
        new_status.value,
        decided_by,
        reason,
    )
    if row is None:
        raise Top32EntryNotFoundError(squad_name)
    return _row_to_entry(row)


async def assign_seeds_at_publish(conn: asyncpg.Connection, season_id: UUID) -> int:
    """Assigns fresh seeds 1..N over the current Top-32 window, in rank order
    — NOT pinned to each squad's original rank (client-confirmed 2026-09-23).
    Returns how many seeds were assigned."""
    rows = await conn.fetch(
        """
        with window as (
            select squad_id, row_number() over (order by rank) as seed
            from season_qualifications
            where season_id = $1 and status = 'qualified'
            order by rank
            limit $2
        )
        update season_qualifications sq
        set seed = w.seed
        from window w
        where sq.season_id = $1 and sq.squad_id = w.squad_id
        returning w.seed
        """,
        season_id,
        _TOP32_LIMIT,
    )
    return len(rows)
