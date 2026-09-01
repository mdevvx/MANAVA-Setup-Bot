from __future__ import annotations

import json
from uuid import UUID

import asyncpg

from src.errors import DuplicateApplicationError
from src.models.application import Application, AppStatus, AppType


def _row_to_application(row: asyncpg.Record) -> Application:
    raw_fields = row["fields"]
    fields = json.loads(raw_fields) if isinstance(raw_fields, str) else dict(raw_fields)
    return Application(
        id=row["id"],
        applicant_id=row["applicant_id"],
        applicant_username=row["applicant_username"],
        app_type=AppType(row["app_type"]),
        status=AppStatus(row["status"]),
        fields=fields,
        review_channel_id=row["review_channel_id"],
        review_message_id=row["review_message_id"],
        submitted_at=row["submitted_at"],
        decided_at=row["decided_at"],
        decided_by=row["decided_by"],
    )


async def insert(
    conn: asyncpg.Connection,
    *,
    applicant_id: int,
    applicant_username: str,
    app_type: AppType,
    fields: dict[str, str],
) -> Application:
    """Inserts a new pending application. Raises DuplicateApplicationError if
    the applicant already has an active one of this type (enforced by the
    partial unique index, so this is race-safe, not just a pre-check)."""
    try:
        row = await conn.fetchrow(
            """
            insert into applications (applicant_id, applicant_username, app_type, fields)
            values ($1, $2, $3, $4::jsonb)
            returning *
            """,
            applicant_id,
            applicant_username,
            app_type.value,
            json.dumps(fields),
        )
    except asyncpg.UniqueViolationError as exc:
        raise DuplicateApplicationError(app_type.label) from exc
    assert row is not None
    return _row_to_application(row)


async def get(conn: asyncpg.Connection, application_id: UUID) -> Application | None:
    row = await conn.fetchrow("select * from applications where id = $1", application_id)
    return _row_to_application(row) if row else None


async def get_by_review_message(conn: asyncpg.Connection, review_message_id: int) -> Application | None:
    """Resolve an application from the review-channel message its buttons live
    on — lets the persistent review view work with static custom_ids and no
    per-application state."""
    row = await conn.fetchrow(
        "select * from applications where review_message_id = $1", review_message_id
    )
    return _row_to_application(row) if row else None


async def get_active_for_user(
    conn: asyncpg.Connection, applicant_id: int, app_type: AppType
) -> Application | None:
    row = await conn.fetchrow(
        """
        select * from applications
        where applicant_id = $1 and app_type = $2
          and status in ('pending', 'more_info_requested')
        """,
        applicant_id,
        app_type.value,
    )
    return _row_to_application(row) if row else None


async def last_rejection(
    conn: asyncpg.Connection, applicant_id: int, app_type: AppType
) -> Application | None:
    """Most recent rejected application of this type for this user — feeds the
    30-day reapplication cooldown check."""
    row = await conn.fetchrow(
        """
        select * from applications
        where applicant_id = $1 and app_type = $2 and status = 'rejected'
        order by decided_at desc
        limit 1
        """,
        applicant_id,
        app_type.value,
    )
    return _row_to_application(row) if row else None


async def set_status(
    conn: asyncpg.Connection,
    application_id: UUID,
    *,
    new_status: AppStatus,
    decided_by: int | None = None,
) -> Application:
    """Updates status. For terminal statuses (approved/rejected) also stamps
    decided_at/decided_by; for pending/more_info_requested those are cleared
    back to NULL so a re-opened application looks undecided again."""
    decided = new_status.is_decided
    row = await conn.fetchrow(
        """
        update applications
        set status = $2,
            decided_at = case when $3 then now() else null end,
            decided_by = case when $3 then $4::bigint else null end
        where id = $1
        returning *
        """,
        application_id,
        new_status.value,
        decided,
        decided_by,
    )
    assert row is not None
    return _row_to_application(row)


async def set_review_message(
    conn: asyncpg.Connection, application_id: UUID, *, channel_id: int, message_id: int
) -> None:
    await conn.execute(
        "update applications set review_channel_id = $2, review_message_id = $3 where id = $1",
        application_id,
        channel_id,
        message_id,
    )
