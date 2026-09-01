from __future__ import annotations

from uuid import UUID

import asyncpg

from src.models.application import ApplicationHistoryEntry, AppStatus, HistoryActorRole


def _row_to_entry(row: asyncpg.Record) -> ApplicationHistoryEntry:
    return ApplicationHistoryEntry(
        id=row["id"],
        application_id=row["application_id"],
        old_status=AppStatus(row["old_status"]) if row["old_status"] else None,
        new_status=AppStatus(row["new_status"]),
        actor_id=row["actor_id"],
        actor_role=HistoryActorRole(row["actor_role"]),
        note=row["note"],
        created_at=row["created_at"],
    )


async def record(
    conn: asyncpg.Connection,
    *,
    application_id: UUID,
    old_status: AppStatus | None,
    new_status: AppStatus,
    actor_id: int,
    actor_role: HistoryActorRole,
    note: str | None = None,
) -> None:
    """Append one entry to an application's history trail. `note` may contain
    PII (e.g. the applicant's own free-text reply) — this table is part of the
    private applications-review flow and is never surfaced elsewhere."""
    await conn.execute(
        """
        insert into application_history
            (application_id, old_status, new_status, actor_id, actor_role, note)
        values ($1, $2, $3, $4, $5, $6)
        """,
        application_id,
        old_status.value if old_status else None,
        new_status.value,
        actor_id,
        actor_role.value,
        note,
    )


async def list_for_application(
    conn: asyncpg.Connection, application_id: UUID
) -> list[ApplicationHistoryEntry]:
    rows = await conn.fetch(
        "select * from application_history where application_id = $1 order by created_at",
        application_id,
    )
    return [_row_to_entry(r) for r in rows]
