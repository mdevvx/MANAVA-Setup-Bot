from __future__ import annotations

import logging

import asyncpg
import discord

from src.db.repositories import audit_logs as audit_repo
from src.db.repositories import memberships as memberships_repo
from src.db.repositories import squads as squads_repo
from src.discord_state import provisioning
from src.discord_state.capacity import find_available_category
from src.discord_state.role_resolver import ResolvedGuildState
from src.errors import BotUserError
from src.models.squad import Squad, SquadStatus

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


async def restore_squad(
    conn: asyncpg.Connection,
    *,
    state: ResolvedGuildState,
    squad: Squad,
    actor_id: int,
) -> tuple[Squad, list[tuple[int, str]]]:
    """Recover a squad that was disbanded but is still inside its 30-day archive
    window (channels not yet purged). Recreates the squad-specific role that
    was deleted at disband, flips the record back to active, reopens the
    memberships it closed, and re-grants Discord access. Returns the restored
    squad and the reopened `(discord_user_id, squad_role)` list."""
    if squad.status is not SquadStatus.DISBANDED:
        raise BotUserError(f"**{squad.name}** isn't disbanded — nothing to restore.")
    if squad.discord_objects_purged_at is not None:
        raise BotUserError(
            f"**{squad.name}**'s 30-day archive window has elapsed and its channels are gone. "
            "It can't be auto-restored; the name stays reserved."
        )

    # The recorded Leader must be free to lead again.
    leader_elsewhere = await memberships_repo.get_active_membership(conn, squad.leader_user_id)
    if leader_elsewhere is not None:
        raise BotUserError(
            f"The former Leader <@{squad.leader_user_id}> is now in another squad. "
            "They must leave it before this squad can be restored."
        )

    new_role = await state.guild.create_role(
        name=f"Squad {squad.name}", mentionable=False, reason=f"Squad restored by {actor_id}"
    )
    try:
        restored, reopened = await squads_repo.mark_restored(
            conn, squad.id, actor_id=actor_id, new_role_id=new_role.id
        )
    except Exception:
        logger.exception("Squad restore DB step failed for %s; deleting the recreated role", squad.id)
        try:
            await new_role.delete(reason="Rollback: squad restore failed")
        except discord.DiscordException:
            logger.exception("Failed to roll back recreated role for %s", squad.id)
        raise

    await provisioning.reapply_restored_squad_access(state, restored, reopened)
    await audit_repo.record(
        conn,
        actor_id=actor_id,
        action="squad.restore",
        target_type="squad",
        target_id=str(squad.id),
        old_value={"status": "disbanded"},
        new_value={"status": "active", "reopened_members": len(reopened)},
    )
    return restored, reopened


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
