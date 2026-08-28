from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from src.errors import InsufficientSquadPermissionError, InvalidSquadStateError, OfficerLimitReachedError
from src.models.squad import Squad, SquadMembership, SquadRole, SquadStatus
from src.services import squad_membership


def _fake_squad(squad_id) -> Squad:
    return Squad(
        id=squad_id,
        name="Test Squad",
        status=SquadStatus.ACTIVE,
        leader_user_id=1,
        category_id=100,
        role_id=200,
        member_text_channel_id=300,
        member_voice_channel_id=301,
        officer_text_channel_id=302,
        officer_voice_channel_id=303,
        created_at=None,  # type: ignore[arg-type]
        disbanded_at=None,
        archive_purge_after=None,
    )


def _fake_membership(squad_id, user_id, role: SquadRole) -> SquadMembership:
    return SquadMembership(
        id=uuid4(),
        squad_id=squad_id,
        discord_user_id=user_id,
        squad_role=role,
        joined_at=None,  # type: ignore[arg-type]
        left_at=None,
        contributed_xp=0,
    )


@pytest.mark.asyncio
async def test_promote_blocked_at_officer_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    squad_id = uuid4()
    squad = _fake_squad(squad_id)
    leader = SimpleNamespace(id=1)
    target = SimpleNamespace(id=3)

    monkeypatch.setattr(squad_membership.squads_repo, "get_squad_by_id", AsyncMock(return_value=squad))
    monkeypatch.setattr(
        squad_membership.memberships_repo,
        "get_membership_in_squad",
        AsyncMock(
            side_effect=lambda conn, sid, uid: _fake_membership(
                sid, uid, SquadRole.LEADER if uid == 1 else SquadRole.MEMBER
            )
        ),
    )
    monkeypatch.setattr(squad_membership.memberships_repo, "count_officers", AsyncMock(return_value=2))

    with pytest.raises(OfficerLimitReachedError):
        await squad_membership.promote_to_officer(
            None, state=None, squad_id=squad_id, actor=leader, target=target  # type: ignore[arg-type]
        )


@pytest.mark.asyncio
async def test_officer_cannot_promote_peers(monkeypatch: pytest.MonkeyPatch) -> None:
    squad_id = uuid4()
    squad = _fake_squad(squad_id)
    officer_actor = SimpleNamespace(id=2)
    target = SimpleNamespace(id=3)

    monkeypatch.setattr(squad_membership.squads_repo, "get_squad_by_id", AsyncMock(return_value=squad))
    monkeypatch.setattr(
        squad_membership.memberships_repo,
        "get_membership_in_squad",
        AsyncMock(return_value=_fake_membership(squad_id, 2, SquadRole.OFFICER)),
    )

    with pytest.raises(InsufficientSquadPermissionError):
        await squad_membership.promote_to_officer(
            None, state=None, squad_id=squad_id, actor=officer_actor, target=target  # type: ignore[arg-type]
        )


@pytest.mark.asyncio
async def test_leader_cannot_leave_without_transfer_or_disband(monkeypatch: pytest.MonkeyPatch) -> None:
    squad_id = uuid4()
    squad = _fake_squad(squad_id)
    leader = SimpleNamespace(id=1)

    monkeypatch.setattr(
        squad_membership.memberships_repo,
        "get_active_membership",
        AsyncMock(return_value=_fake_membership(squad_id, 1, SquadRole.LEADER)),
    )
    monkeypatch.setattr(squad_membership.squads_repo, "get_squad_by_id", AsyncMock(return_value=squad))

    with pytest.raises(InvalidSquadStateError):
        await squad_membership.leave_squad(None, state=None, member=leader)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_cannot_remove_the_leader(monkeypatch: pytest.MonkeyPatch) -> None:
    squad_id = uuid4()
    squad = _fake_squad(squad_id)
    officer_actor = SimpleNamespace(id=2)
    leader_target = SimpleNamespace(id=1)

    monkeypatch.setattr(squad_membership.squads_repo, "get_squad_by_id", AsyncMock(return_value=squad))

    async def fake_membership_lookup(conn, sid, uid):
        return _fake_membership(sid, uid, SquadRole.OFFICER if uid == 2 else SquadRole.LEADER)

    monkeypatch.setattr(
        squad_membership.memberships_repo, "get_membership_in_squad", AsyncMock(side_effect=fake_membership_lookup)
    )

    with pytest.raises(InvalidSquadStateError):
        await squad_membership.remove_member(
            None,  # type: ignore[arg-type]
            state=None,  # type: ignore[arg-type]
            squad_id=squad_id,
            actor=officer_actor,
            target=leader_target,
            reason=None,
        )
