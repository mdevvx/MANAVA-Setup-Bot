from __future__ import annotations

from uuid import UUID

import asyncpg

from src.errors import AlreadyInSquadError, DuplicateSquadNameError, SquadNotFoundError
from src.models.squad import NewSquadDiscordObjects, Squad, SquadStatus


def _row_to_squad(row: asyncpg.Record) -> Squad:
    return Squad(
        id=row["id"],
        name=row["name"],
        status=SquadStatus(row["status"]),
        leader_user_id=row["leader_user_id"],
        category_id=row["category_id"],
        role_id=row["role_id"],
        member_text_channel_id=row["member_text_channel_id"],
        member_voice_channel_id=row["member_voice_channel_id"],
        officer_text_channel_id=row["officer_text_channel_id"],
        officer_voice_channel_id=row["officer_voice_channel_id"],
        created_at=row["created_at"],
        disbanded_at=row["disbanded_at"],
        archive_purge_after=row["archive_purge_after"],
    )


async def name_is_taken(conn: asyncpg.Connection, name: str) -> bool:
    row = await conn.fetchrow("select 1 from squads where name_lower = lower($1)", name)
    return row is not None


async def get_active_squad_counts_by_category(conn: asyncpg.Connection) -> dict[int, int]:
    rows = await conn.fetch(
        "select category_id, count(*) as cnt from squads where status = 'active' group by category_id"
    )
    return {row["category_id"]: row["cnt"] for row in rows}


async def get_squad_by_id(conn: asyncpg.Connection, squad_id: UUID) -> Squad:
    row = await conn.fetchrow("select * from squads where id = $1", squad_id)
    if row is None:
        raise SquadNotFoundError()
    return _row_to_squad(row)


async def get_active_squad_by_name(conn: asyncpg.Connection, name: str) -> Squad | None:
    row = await conn.fetchrow(
        "select * from squads where name_lower = lower($1) and status = 'active'", name
    )
    return _row_to_squad(row) if row else None


async def insert_squad(
    conn: asyncpg.Connection,
    *,
    name: str,
    leader_user_id: int,
    objects: NewSquadDiscordObjects,
) -> Squad:
    async with conn.transaction():
        try:
            row = await conn.fetchrow(
                """
                insert into squads (
                    name, leader_user_id, category_id, role_id,
                    member_text_channel_id, member_voice_channel_id,
                    officer_text_channel_id, officer_voice_channel_id
                )
                values ($1, $2, $3, $4, $5, $6, $7, $8)
                returning *
                """,
                name,
                leader_user_id,
                objects.category_id,
                objects.role_id,
                objects.member_text_channel_id,
                objects.member_voice_channel_id,
                objects.officer_text_channel_id,
                objects.officer_voice_channel_id,
            )
        except asyncpg.UniqueViolationError as exc:
            raise DuplicateSquadNameError(name) from exc
        assert row is not None
        squad = _row_to_squad(row)

        try:
            await conn.execute(
                "insert into squad_memberships (squad_id, discord_user_id, squad_role) values ($1, $2, 'leader')",
                squad.id,
                leader_user_id,
            )
        except asyncpg.UniqueViolationError as exc:
            raise AlreadyInSquadError() from exc

        return squad


async def mark_disbanded(
    conn: asyncpg.Connection,
    squad_id: UUID,
    *,
    actor_id: int,
    reason: str | None,
    archive_days: int,
) -> Squad:
    async with conn.transaction():
        row = await conn.fetchrow(
            """
            update squads
            set status = 'disbanded',
                disbanded_at = now(),
                archive_purge_after = now() + make_interval(days => $2)
            where id = $1 and status = 'active'
            returning *
            """,
            squad_id,
            archive_days,
        )
        if row is None:
            raise SquadNotFoundError()
        squad = _row_to_squad(row)
        await conn.execute(
            """
            insert into squad_status_history (squad_id, old_status, new_status, actor_id, reason)
            values ($1, 'active', 'disbanded', $2, $3)
            """,
            squad_id,
            actor_id,
            reason,
        )
        await conn.execute(
            "update squad_memberships set left_at = now() where squad_id = $1 and left_at is null",
            squad_id,
        )
        return squad


async def set_leader(conn: asyncpg.Connection, squad_id: UUID, new_leader_id: int) -> None:
    await conn.execute("update squads set leader_user_id = $2 where id = $1", squad_id, new_leader_id)


async def list_squads_ready_for_purge(conn: asyncpg.Connection) -> list[Squad]:
    rows = await conn.fetch(
        """
        select * from squads
        where status = 'disbanded'
          and archive_purge_after <= now()
          and discord_objects_purged_at is null
        """
    )
    return [_row_to_squad(r) for r in rows]


async def mark_discord_objects_purged(conn: asyncpg.Connection, squad_id: UUID) -> None:
    await conn.execute("update squads set discord_objects_purged_at = now() where id = $1", squad_id)
