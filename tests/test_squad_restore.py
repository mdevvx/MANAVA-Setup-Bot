"""Disband recovery: /admin restore-squad within the 30-day archive window."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from src.errors import BotUserError
from src.models.squad import Squad, SquadRole, SquadStatus
from src.services import squad_lifecycle


class _FakeTxn:
    async def __aenter__(self) -> "_FakeTxn":
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None


class _FakeConn:
    def transaction(self) -> _FakeTxn:
        return _FakeTxn()


def _squad(*, status: SquadStatus, purged: datetime | None = None, leader_id: int = 1) -> Squad:
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return Squad(
        id=uuid4(),
        name="Alpha",
        status=status,
        leader_user_id=leader_id,
        category_id=100,
        role_id=200,
        member_text_channel_id=300,
        member_voice_channel_id=301,
        officer_text_channel_id=302,
        officer_voice_channel_id=303,
        created_at=now,
        disbanded_at=now,
        archive_purge_after=now,
        discord_objects_purged_at=purged,
    )


def _state() -> SimpleNamespace:
    return SimpleNamespace(guild=SimpleNamespace(create_role=AsyncMock(return_value=SimpleNamespace(id=999, delete=AsyncMock()))))


@pytest.mark.asyncio
async def test_restore_rejects_active_squad() -> None:
    with pytest.raises(BotUserError):
        await squad_lifecycle.restore_squad(
            _FakeConn(), state=_state(), squad=_squad(status=SquadStatus.ACTIVE), actor_id=9  # type: ignore[arg-type]
        )


@pytest.mark.asyncio
async def test_restore_rejects_after_channels_purged() -> None:
    purged = datetime(2026, 2, 1, tzinfo=timezone.utc)
    with pytest.raises(BotUserError):
        await squad_lifecycle.restore_squad(
            _FakeConn(),  # type: ignore[arg-type]
            state=_state(),
            squad=_squad(status=SquadStatus.DISBANDED, purged=purged),
            actor_id=9,
        )


@pytest.mark.asyncio
async def test_restore_rejects_when_former_leader_is_in_another_squad(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        squad_lifecycle.memberships_repo,
        "get_active_membership",
        AsyncMock(return_value=SimpleNamespace(squad_id=uuid4())),
    )
    with pytest.raises(BotUserError):
        await squad_lifecycle.restore_squad(
            _FakeConn(), state=_state(), squad=_squad(status=SquadStatus.DISBANDED), actor_id=9  # type: ignore[arg-type]
        )


@pytest.mark.asyncio
async def test_restore_happy_path(monkeypatch: pytest.MonkeyPatch) -> None:
    squad = _squad(status=SquadStatus.DISBANDED)
    restored = _squad(status=SquadStatus.ACTIVE)
    reopened = [(1, SquadRole.LEADER.value), (2, SquadRole.MEMBER.value)]

    monkeypatch.setattr(squad_lifecycle.memberships_repo, "get_active_membership", AsyncMock(return_value=None))
    mark = AsyncMock(return_value=(restored, reopened))
    monkeypatch.setattr(squad_lifecycle.squads_repo, "mark_restored", mark)
    reapply = AsyncMock()
    monkeypatch.setattr(squad_lifecycle.provisioning, "reapply_restored_squad_access", reapply)
    audit = AsyncMock()
    monkeypatch.setattr(squad_lifecycle.audit_repo, "record", audit)

    state = _state()
    out_squad, out_reopened = await squad_lifecycle.restore_squad(
        _FakeConn(), state=state, squad=squad, actor_id=9  # type: ignore[arg-type]
    )

    state.guild.create_role.assert_awaited_once()
    mark.assert_awaited_once()
    reapply.assert_awaited_once()
    audit.assert_awaited_once()
    assert out_squad is restored
    assert out_reopened == reopened


@pytest.mark.asyncio
async def test_restore_rolls_back_recreated_role_if_db_step_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(squad_lifecycle.memberships_repo, "get_active_membership", AsyncMock(return_value=None))
    monkeypatch.setattr(
        squad_lifecycle.squads_repo, "mark_restored", AsyncMock(side_effect=RuntimeError("db boom"))
    )
    state = _state()

    with pytest.raises(RuntimeError):
        await squad_lifecycle.restore_squad(
            _FakeConn(), state=state, squad=_squad(status=SquadStatus.DISBANDED), actor_id=9  # type: ignore[arg-type]
        )

    created_role = state.guild.create_role.return_value
    created_role.delete.assert_awaited_once()
