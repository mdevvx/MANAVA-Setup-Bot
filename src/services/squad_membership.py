from __future__ import annotations

import logging
from uuid import UUID

import asyncpg
import discord

from src import constants
from src.db.repositories import audit_logs as audit_repo
from src.db.repositories import join_requests as join_requests_repo
from src.db.repositories import memberships as memberships_repo
from src.db.repositories import squads as squads_repo
from src.discord_state import provisioning
from src.discord_state.role_resolver import ResolvedGuildState
from src.errors import (
    AlreadyInSquadError,
    InsufficientSquadPermissionError,
    InvalidSquadStateError,
    NotSquadMemberError,
    OfficerLimitReachedError,
    SquadNotFoundError,
)
from src.models.squad import Squad, SquadJoinRequest, SquadMembership, SquadRole

logger = logging.getLogger(__name__)


async def _require_active_squad(conn: asyncpg.Connection, squad_id: UUID) -> Squad:
    squad = await squads_repo.get_squad_by_id(conn, squad_id)
    if squad.status.value != "active":
        raise SquadNotFoundError()
    return squad


async def _require_leader_or_officer(
    conn: asyncpg.Connection, squad: Squad, member: discord.abc.User
) -> SquadMembership:
    membership = await memberships_repo.get_membership_in_squad(conn, squad.id, member.id)
    if membership is None or membership.squad_role not in (SquadRole.LEADER, SquadRole.OFFICER):
        raise InsufficientSquadPermissionError()
    return membership


async def submit_join_request(
    conn: asyncpg.Connection, *, squad_id: UUID, applicant: discord.Member
) -> SquadJoinRequest:
    squad = await _require_active_squad(conn, squad_id)
    existing = await memberships_repo.get_active_membership(conn, applicant.id)
    if existing is not None:
        raise AlreadyInSquadError()
    request = await join_requests_repo.create_request(conn, squad.id, applicant.id)
    await audit_repo.record(
        conn,
        actor_id=applicant.id,
        action="squad.join_request.submit",
        target_type="squad",
        target_id=str(squad.id),
        new_value={"applicant_id": applicant.id},
    )
    return request


async def approve_join_request(
    conn: asyncpg.Connection,
    *,
    state: ResolvedGuildState,
    request_id: UUID,
    approver: discord.Member,
    applicant: discord.Member,
) -> SquadMembership:
    request = await join_requests_repo.get_request(conn, request_id)
    if request is None or request.status.value != "pending":
        raise InvalidSquadStateError("This request has already been decided or no longer exists.")
    squad = await _require_active_squad(conn, request.squad_id)
    await _require_leader_or_officer(conn, squad, approver)

    # Re-check one-user/one-active-squad immediately before approval completes.
    existing = await memberships_repo.get_active_membership(conn, applicant.id)
    if existing is not None:
        await join_requests_repo.decide_request(conn, request_id, approved=False, decided_by=approver.id)
        raise AlreadyInSquadError()

    try:
        membership = await memberships_repo.add_member(conn, squad.id, applicant.id)
    except asyncpg.UniqueViolationError as exc:
        raise AlreadyInSquadError() from exc
    await join_requests_repo.decide_request(conn, request_id, approved=True, decided_by=approver.id)
    await provisioning.grant_squad_membership_access(state, squad, applicant)
    await audit_repo.record(
        conn,
        actor_id=approver.id,
        action="squad.join_request.approve",
        target_type="squad",
        target_id=str(squad.id),
        new_value={"applicant_id": applicant.id},
    )
    return membership


async def reject_join_request(conn: asyncpg.Connection, *, request_id: UUID, approver: discord.Member) -> None:
    request = await join_requests_repo.get_request(conn, request_id)
    if request is None or request.status.value != "pending":
        raise InvalidSquadStateError("This request has already been decided or no longer exists.")
    squad = await _require_active_squad(conn, request.squad_id)
    await _require_leader_or_officer(conn, squad, approver)
    await join_requests_repo.decide_request(conn, request_id, approved=False, decided_by=approver.id)
    await audit_repo.record(
        conn,
        actor_id=approver.id,
        action="squad.join_request.reject",
        target_type="squad",
        target_id=str(squad.id),
        new_value={"applicant_id": request.applicant_id},
    )


async def invite_member(
    conn: asyncpg.Connection,
    *,
    state: ResolvedGuildState,
    squad_id: UUID,
    inviter: discord.Member,
    invitee: discord.Member,
) -> SquadMembership:
    squad = await _require_active_squad(conn, squad_id)
    await _require_leader_or_officer(conn, squad, inviter)
    existing = await memberships_repo.get_active_membership(conn, invitee.id)
    if existing is not None:
        raise AlreadyInSquadError()
    try:
        membership = await memberships_repo.add_member(conn, squad.id, invitee.id)
    except asyncpg.UniqueViolationError as exc:
        raise AlreadyInSquadError() from exc
    await provisioning.grant_squad_membership_access(state, squad, invitee)
    await audit_repo.record(
        conn,
        actor_id=inviter.id,
        action="squad.member.invite",
        target_type="squad",
        target_id=str(squad.id),
        new_value={"invitee_id": invitee.id},
    )
    return membership


async def leave_squad(conn: asyncpg.Connection, *, state: ResolvedGuildState, member: discord.Member) -> Squad:
    membership = await memberships_repo.get_active_membership(conn, member.id)
    if membership is None:
        raise NotSquadMemberError()
    squad = await _require_active_squad(conn, membership.squad_id)

    if membership.squad_role is SquadRole.LEADER:
        # Decision (2026-08-25): leader-leave is blocked outright, not auto-succeeded —
        # a squad must never end up with no Leader.
        raise InvalidSquadStateError(
            "You're the Squad Leader. Transfer leadership to another member or disband the squad before leaving."
        )

    await memberships_repo.remove_member(conn, squad.id, member.id)
    await provisioning.revoke_squad_membership_access(state, squad, member)
    await audit_repo.record(
        conn,
        actor_id=member.id,
        action="squad.member.leave",
        target_type="squad",
        target_id=str(squad.id),
        old_value={"squad_role": membership.squad_role.value},
    )
    return squad


async def remove_member(
    conn: asyncpg.Connection,
    *,
    state: ResolvedGuildState,
    squad_id: UUID,
    actor: discord.Member,
    target: discord.Member,
    reason: str | None,
) -> None:
    squad = await _require_active_squad(conn, squad_id)
    await _require_leader_or_officer(conn, squad, actor)
    target_membership = await memberships_repo.get_membership_in_squad(conn, squad.id, target.id)
    if target_membership is None:
        raise NotSquadMemberError()
    if target_membership.squad_role is SquadRole.LEADER:
        raise InvalidSquadStateError("The Squad Leader can't be removed. Transfer leadership or disband instead.")

    await memberships_repo.remove_member(conn, squad.id, target.id)
    await provisioning.revoke_squad_membership_access(state, squad, target)
    await audit_repo.record(
        conn,
        actor_id=actor.id,
        action="squad.member.remove",
        target_type="squad",
        target_id=str(squad.id),
        old_value={"target_id": target.id, "squad_role": target_membership.squad_role.value},
        reason=reason,
    )


async def promote_to_officer(
    conn: asyncpg.Connection,
    *,
    state: ResolvedGuildState,
    squad_id: UUID,
    actor: discord.Member,
    target: discord.Member,
) -> None:
    squad = await _require_active_squad(conn, squad_id)
    actor_membership = await _require_leader_or_officer(conn, squad, actor)
    if actor_membership.squad_role is not SquadRole.LEADER:
        # Only the Leader promotes; Officers can't create peer Officers.
        raise InsufficientSquadPermissionError()

    target_membership = await memberships_repo.get_membership_in_squad(conn, squad.id, target.id)
    if target_membership is None:
        raise NotSquadMemberError()
    if target_membership.squad_role is not SquadRole.MEMBER:
        raise InvalidSquadStateError("That member is already an Officer or the Leader.")

    officer_count = await memberships_repo.count_officers(conn, squad.id)
    if officer_count >= constants.MAX_OFFICERS_PER_SQUAD:
        raise OfficerLimitReachedError(constants.MAX_OFFICERS_PER_SQUAD)

    await memberships_repo.set_squad_role(conn, squad.id, target.id, SquadRole.OFFICER)
    await provisioning.grant_officer_channel_access(state, squad, target)
    await provisioning.set_squad_rank_role(state, target, SquadRole.OFFICER)
    await audit_repo.record(
        conn,
        actor_id=actor.id,
        action="squad.member.promote",
        target_type="squad",
        target_id=str(squad.id),
        old_value={"target_id": target.id, "squad_role": "member"},
        new_value={"target_id": target.id, "squad_role": "officer"},
    )


async def demote_to_member(
    conn: asyncpg.Connection,
    *,
    state: ResolvedGuildState,
    squad_id: UUID,
    actor: discord.Member,
    target: discord.Member,
) -> None:
    squad = await _require_active_squad(conn, squad_id)
    actor_membership = await _require_leader_or_officer(conn, squad, actor)
    if actor_membership.squad_role is not SquadRole.LEADER:
        raise InsufficientSquadPermissionError()

    target_membership = await memberships_repo.get_membership_in_squad(conn, squad.id, target.id)
    if target_membership is None:
        raise NotSquadMemberError()
    if target_membership.squad_role is not SquadRole.OFFICER:
        raise InvalidSquadStateError("That member isn't an Officer.")

    await memberships_repo.set_squad_role(conn, squad.id, target.id, SquadRole.MEMBER)
    await provisioning.revoke_officer_channel_access(state, squad, target)
    await provisioning.set_squad_rank_role(state, target, SquadRole.MEMBER)
    await audit_repo.record(
        conn,
        actor_id=actor.id,
        action="squad.member.demote",
        target_type="squad",
        target_id=str(squad.id),
        old_value={"target_id": target.id, "squad_role": "officer"},
        new_value={"target_id": target.id, "squad_role": "member"},
    )


async def transfer_leadership(
    conn: asyncpg.Connection,
    *,
    state: ResolvedGuildState,
    squad_id: UUID,
    current_leader: discord.Member,
    new_leader: discord.Member,
) -> None:
    squad = await _require_active_squad(conn, squad_id)
    leader_membership = await memberships_repo.get_membership_in_squad(conn, squad.id, current_leader.id)
    if leader_membership is None or leader_membership.squad_role is not SquadRole.LEADER:
        raise InsufficientSquadPermissionError()

    new_leader_membership = await memberships_repo.get_membership_in_squad(conn, squad.id, new_leader.id)
    if new_leader_membership is None:
        raise NotSquadMemberError()

    officer_count = await memberships_repo.count_officers(conn, squad.id)
    was_already_officer = new_leader_membership.squad_role is SquadRole.OFFICER
    effective_officer_count = officer_count - (1 if was_already_officer else 0)
    # Decision (2026-08-25): outgoing leader becomes Officer if there's room, else Member.
    outgoing_role = (
        SquadRole.OFFICER if effective_officer_count < constants.MAX_OFFICERS_PER_SQUAD else SquadRole.MEMBER
    )

    await memberships_repo.set_squad_role(conn, squad.id, new_leader.id, SquadRole.LEADER)
    await memberships_repo.set_squad_role(conn, squad.id, current_leader.id, outgoing_role)
    await squads_repo.set_leader(conn, squad.id, new_leader.id)

    await provisioning.set_squad_rank_role(state, new_leader, SquadRole.LEADER)
    await provisioning.set_squad_rank_role(state, current_leader, outgoing_role)
    await provisioning.grant_officer_channel_access(state, squad, new_leader)
    if outgoing_role is SquadRole.OFFICER:
        await provisioning.grant_officer_channel_access(state, squad, current_leader)
    else:
        await provisioning.revoke_officer_channel_access(state, squad, current_leader)

    await audit_repo.record(
        conn,
        actor_id=current_leader.id,
        action="squad.leadership.transfer",
        target_type="squad",
        target_id=str(squad.id),
        old_value={"leader_id": current_leader.id},
        new_value={"leader_id": new_leader.id, "outgoing_leader_role": outgoing_role.value},
    )
