from __future__ import annotations

import json
from typing import Any

import asyncpg


async def record(
    conn: asyncpg.Connection,
    *,
    actor_id: int,
    action: str,
    target_type: str,
    target_id: str,
    old_value: dict[str, Any] | None = None,
    new_value: dict[str, Any] | None = None,
    reason: str | None = None,
) -> None:
    await conn.execute(
        """
        insert into audit_logs (actor_id, action, target_type, target_id, old_value, new_value, reason)
        values ($1, $2, $3, $4, $5, $6, $7)
        """,
        actor_id,
        action,
        target_type,
        target_id,
        json.dumps(old_value) if old_value is not None else None,
        json.dumps(new_value) if new_value is not None else None,
        reason,
    )
