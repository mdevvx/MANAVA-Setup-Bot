from __future__ import annotations

from uuid import UUID

import asyncpg

from src.models.squad import SquadMembership, SquadRole


def _row_to_membership(row: asyncpg.Record) -> SquadMembership:
    return SquadMembership(
        id=row["id"],
        squad_id=row["squad_id"],
        discord_user_id=row["discord_user_id"],
        squad_role=SquadRole(row["squad_role"]),
        joined_at=row["joined_at"],
        left_at=row["left_at"],
    )


async def get_active_membership(conn: asyncpg.Connection, discord_user_id: int) -> SquadMembership | None:
    row = await conn.fetchrow(
        "select * from squad_memberships where discord_user_id = $1 and left_at is null",
        discord_user_id,
    )
    return _row_to_membership(row) if row else None


async def get_membership_in_squad(
    conn: asyncpg.Connection, squad_id: UUID, discord_user_id: int
) -> SquadMembership | None:
    row = await conn.fetchrow(
        "select * from squad_memberships where squad_id = $1 and discord_user_id = $2 and left_at is null",
        squad_id,
        discord_user_id,
    )
    return _row_to_membership(row) if row else None


async def list_active_members(conn: asyncpg.Connection, squad_id: UUID) -> list[SquadMembership]:
    rows = await conn.fetch(
        "select * from squad_memberships where squad_id = $1 and left_at is null order by joined_at",
        squad_id,
    )
    return [_row_to_membership(r) for r in rows]


async def count_officers(conn: asyncpg.Connection, squad_id: UUID) -> int:
    row = await conn.fetchrow(
        """
        select count(*) as cnt from squad_memberships
        where squad_id = $1 and left_at is null and squad_role = 'officer'
        """,
        squad_id,
    )
    assert row is not None
    return int(row["cnt"])


async def add_member(
    conn: asyncpg.Connection,
    squad_id: UUID,
    discord_user_id: int,
    *,
    squad_role: SquadRole = SquadRole.MEMBER,
) -> SquadMembership:
    row = await conn.fetchrow(
        """
        insert into squad_memberships (squad_id, discord_user_id, squad_role)
        values ($1, $2, $3)
        returning *
        """,
        squad_id,
        discord_user_id,
        squad_role.value,
    )
    assert row is not None
    return _row_to_membership(row)


async def remove_member(conn: asyncpg.Connection, squad_id: UUID, discord_user_id: int) -> None:
    await conn.execute(
        """
        update squad_memberships set left_at = now()
        where squad_id = $1 and discord_user_id = $2 and left_at is null
        """,
        squad_id,
        discord_user_id,
    )


async def set_squad_role(
    conn: asyncpg.Connection, squad_id: UUID, discord_user_id: int, squad_role: SquadRole
) -> None:
    await conn.execute(
        """
        update squad_memberships set squad_role = $3
        where squad_id = $1 and discord_user_id = $2 and left_at is null
        """,
        squad_id,
        discord_user_id,
        squad_role.value,
    )
