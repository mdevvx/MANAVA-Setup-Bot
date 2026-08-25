from __future__ import annotations

from uuid import UUID

import asyncpg

from src.errors import AlreadyAppliedError
from src.models.squad import JoinRequestStatus, SquadJoinRequest


def _row_to_request(row: asyncpg.Record) -> SquadJoinRequest:
    return SquadJoinRequest(
        id=row["id"],
        squad_id=row["squad_id"],
        applicant_id=row["applicant_id"],
        status=JoinRequestStatus(row["status"]),
        created_at=row["created_at"],
        decided_at=row["decided_at"],
        decided_by=row["decided_by"],
    )


async def create_request(conn: asyncpg.Connection, squad_id: UUID, applicant_id: int) -> SquadJoinRequest:
    try:
        row = await conn.fetchrow(
            "insert into squad_join_requests (squad_id, applicant_id) values ($1, $2) returning *",
            squad_id,
            applicant_id,
        )
    except asyncpg.UniqueViolationError as exc:
        raise AlreadyAppliedError() from exc
    assert row is not None
    return _row_to_request(row)


async def get_request(conn: asyncpg.Connection, request_id: UUID) -> SquadJoinRequest | None:
    row = await conn.fetchrow("select * from squad_join_requests where id = $1", request_id)
    return _row_to_request(row) if row else None


async def decide_request(
    conn: asyncpg.Connection, request_id: UUID, *, approved: bool, decided_by: int
) -> SquadJoinRequest | None:
    status = JoinRequestStatus.APPROVED.value if approved else JoinRequestStatus.REJECTED.value
    row = await conn.fetchrow(
        """
        update squad_join_requests
        set status = $2, decided_at = now(), decided_by = $3
        where id = $1 and status = 'pending'
        returning *
        """,
        request_id,
        status,
        decided_by,
    )
    return _row_to_request(row) if row else None
