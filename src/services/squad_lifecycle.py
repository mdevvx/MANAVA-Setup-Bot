from __future__ import annotations

import logging

import asyncpg
import discord

from src.db.repositories import audit_logs as audit_repo
from src.db.repositories import squads as squads_repo
from src.discord_state import provisioning
from src.discord_state.capacity import find_available_category
from src.discord_state.role_resolver import ResolvedGuildState
from src.models.squad import Squad

logger = logging.getLogger(__name__)


async def create_squad(
    conn: asyncpg.Connection,
    *,
    state: ResolvedGuildState,
    leader: discord.Member,
    squad_name: str,
) -> Squad:
    name = squad_name.strip()
    counts = await squads_repo.get_active_squad_counts_by_category(conn)
    category_id = find_available_category(state, counts)

    objects = await provisioning.create_squad_objects(
        state, squad_name=name, leader=leader, category_id=category_id
    )

    try:
        squad = await squads_repo.insert_squad(conn, name=name, leader_user_id=leader.id, objects=objects)
    except Exception:
        logger.exception("Failed inserting squad %r after Discord objects were created; rolling back", name)
        await provisioning.rollback_new_objects(state, objects)
        raise

    await audit_repo.record(
        conn,
        actor_id=leader.id,
        action="squad.create",
        target_type="squad",
        target_id=str(squad.id),
        new_value={"name": squad.name, "category_id": category_id},
    )
    return squad


async def disband_squad(
    conn: asyncpg.Connection,
    *,
    state: ResolvedGuildState,
    squad: Squad,
    actor_id: int,
    reason: str | None,
    archive_days: int,
) -> Squad:
    updated = await squads_repo.mark_disbanded(
        conn, squad.id, actor_id=actor_id, reason=reason, archive_days=archive_days
    )
    await provisioning.revoke_all_member_access(state, updated)
    await audit_repo.record(
        conn,
        actor_id=actor_id,
        action="squad.disband",
        target_type="squad",
        target_id=str(squad.id),
        old_value={"status": "active"},
        new_value={"status": "disbanded", "reason": reason},
        reason=reason,
    )
    return updated
