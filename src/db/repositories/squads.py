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
        discord_objects_purged_at=row["discord_objects_purged_at"],
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


async def get_squad_by_name_any_status(conn: asyncpg.Connection, name: str) -> Squad | None:
    """Name is reserved forever, so there's at most one row per name regardless
    of status — used by the disband-recovery path."""
    row = await conn.fetchrow("select * from squads where name_lower = lower($1)", name)
    return _row_to_squad(row) if row else None


async def search_squad_names(
    conn: asyncpg.Connection, *, active: bool, name_contains: str, limit: int = 25
) -> list[str]:
    """Squad names matching a substring — backs slash-command autocomplete.
    `active=True` → currently-active squads; `active=False` → disbanded squads
    still inside the archive window (restorable)."""
    where = (
        "status = 'active'"
        if active
        else "status = 'disbanded' and discord_objects_purged_at is null"
    )
    rows = await conn.fetch(
        f"select name from squads where {where} and name ilike $1 order by name limit $2",
        f"%{name_contains}%",
        limit,
    )
    return [row["name"] for row in rows]


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


async def mark_restored(
    conn: asyncpg.Connection,
    squad_id: UUID,
    *,
    actor_id: int,
    new_role_id: int,
) -> tuple[Squad, list[tuple[int, str]]]:
    """Reverse a disband: flip the squad back to active, point it at the
    freshly recreated squad role, and reopen every membership that was closed
    by the disband — EXCEPT anyone who has since joined another squad (the
    one-active-membership-per-user index would reject those). Returns the
    updated squad and the reopened `(discord_user_id, squad_role)` rows."""
    async with conn.transaction():
        pre = await conn.fetchrow("select * from squads where id = $1 for update", squad_id)
        if pre is None or pre["status"] != "disbanded" or pre["discord_objects_purged_at"] is not None:
            raise SquadNotFoundError()
        disbanded_at = pre["disbanded_at"] or pre["created_at"]

        row = await conn.fetchrow(
            """
            update squads
            set status = 'active', role_id = $2, disbanded_at = null, archive_purge_after = null
            where id = $1
            returning *
            """,
            squad_id,
            new_role_id,
        )
        assert row is not None
        squad = _row_to_squad(row)

        reopened_rows = await conn.fetch(
            """
            update squad_memberships m
            set left_at = null
            where m.squad_id = $1
              and m.left_at is not null
              and m.left_at >= $2
              and not exists (
                  select 1 from squad_memberships other
                  where other.discord_user_id = m.discord_user_id and other.left_at is null
              )
            returning m.discord_user_id, m.squad_role
            """,
            squad_id,
            disbanded_at,
        )
        await conn.execute(
            """
            insert into squad_status_history (squad_id, old_status, new_status, actor_id, reason)
            values ($1, 'disbanded', 'active', $2, 'restored')
            """,
            squad_id,
            actor_id,
        )
        return squad, [(r["discord_user_id"], r["squad_role"]) for r in reopened_rows]


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
