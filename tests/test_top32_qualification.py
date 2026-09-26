"""Pre/post-publish Top-32 replacement: withdraw is pre-publish only,
disqualify works either side of publish. Both are staff-controlled — no
leader-facing path exists (client's Q1 answer, 2026-09-23)."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from src.errors import SeasonStateError
from src.models.season import QualificationEntry, QualificationEntryStatus, Season, SeasonPhase, SeasonStatus
from src.services import top32_service


class _FakeTxn:
    async def __aenter__(self) -> "_FakeTxn":
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None


class _FakeConn:
    def transaction(self) -> _FakeTxn:
        return _FakeTxn()


def _season(*, phase: SeasonPhase) -> Season:
    return Season(
        id=uuid4(),
        season_number=3,
        status=SeasonStatus.ACTIVE,
        started_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        started_by=1,
        ended_at=None,
        ended_by=None,
        phase=phase,
    )


def _entry(*, season_id: object, status: QualificationEntryStatus = QualificationEntryStatus.WITHDRAWN) -> QualificationEntry:
    return QualificationEntry(
        season_id=season_id,  # type: ignore[arg-type]
        squad_id=uuid4(),
        squad_name="Alpha",
        rank=5,
        season_xp_snapshot=1000,
        lifetime_xp_snapshot=5000,
        status=status,
        seed=None,
        decided_by=9,
        decided_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
        decided_reason="left the server",
    )


@pytest.mark.asyncio
async def test_withdraw_allowed_pre_publish(monkeypatch: pytest.MonkeyPatch) -> None:
    conn = _FakeConn()
    active = _season(phase=SeasonPhase.QUALIFICATION_LOCK)
    monkeypatch.setattr(top32_service.seasons_repo, "get_active", AsyncMock(return_value=active))
    entry = _entry(season_id=active.id)
    set_status_mock = AsyncMock(return_value=entry)
    monkeypatch.setattr(top32_service.season_qualifications_repo, "set_status", set_status_mock)
    audit = AsyncMock()
    monkeypatch.setattr(top32_service.audit_repo, "record", audit)

    result = await top32_service.withdraw(conn, "Alpha", actor_id=9, reason="left the server")  # type: ignore[arg-type]

    assert result.squad_name == "Alpha"
    _, kwargs = set_status_mock.await_args
    assert kwargs["new_status"] == QualificationEntryStatus.WITHDRAWN
    _, akwargs = audit.await_args
    assert akwargs["action"] == "season.top32.withdraw"


@pytest.mark.asyncio
async def test_withdraw_blocked_after_publish(monkeypatch: pytest.MonkeyPatch) -> None:
    conn = _FakeConn()
    active = _season(phase=SeasonPhase.TOP32_PLAYOFFS)
    monkeypatch.setattr(top32_service.seasons_repo, "get_active", AsyncMock(return_value=active))
    set_status_mock = AsyncMock()
    monkeypatch.setattr(top32_service.season_qualifications_repo, "set_status", set_status_mock)

    with pytest.raises(SeasonStateError):
        await top32_service.withdraw(conn, "Alpha", actor_id=9, reason=None)  # type: ignore[arg-type]
    set_status_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_withdraw_blocked_before_lock(monkeypatch: pytest.MonkeyPatch) -> None:
    conn = _FakeConn()
    active = _season(phase=SeasonPhase.QUALIFICATION)
    monkeypatch.setattr(top32_service.seasons_repo, "get_active", AsyncMock(return_value=active))
    set_status_mock = AsyncMock()
    monkeypatch.setattr(top32_service.season_qualifications_repo, "set_status", set_status_mock)

    with pytest.raises(SeasonStateError):
        await top32_service.withdraw(conn, "Alpha", actor_id=9, reason=None)  # type: ignore[arg-type]
    set_status_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_disqualify_allowed_pre_publish(monkeypatch: pytest.MonkeyPatch) -> None:
    conn = _FakeConn()
    active = _season(phase=SeasonPhase.QUALIFICATION_LOCK)
    monkeypatch.setattr(top32_service.seasons_repo, "get_active", AsyncMock(return_value=active))
    entry = _entry(season_id=active.id, status=QualificationEntryStatus.DISQUALIFIED)
    monkeypatch.setattr(top32_service.season_qualifications_repo, "set_status", AsyncMock(return_value=entry))
    monkeypatch.setattr(top32_service.audit_repo, "record", AsyncMock())

    result = await top32_service.disqualify(conn, "Alpha", actor_id=9, reason="cheating")  # type: ignore[arg-type]
    assert result.status == QualificationEntryStatus.DISQUALIFIED


@pytest.mark.asyncio
async def test_disqualify_allowed_post_publish(monkeypatch: pytest.MonkeyPatch) -> None:
    """Unlike withdraw, disqualify still works after the bracket is
    published — it just doesn't trigger any automatic replacement."""
    conn = _FakeConn()
    active = _season(phase=SeasonPhase.TOP32_PLAYOFFS)
    monkeypatch.setattr(top32_service.seasons_repo, "get_active", AsyncMock(return_value=active))
    entry = _entry(season_id=active.id, status=QualificationEntryStatus.DISQUALIFIED)
    monkeypatch.setattr(top32_service.season_qualifications_repo, "set_status", AsyncMock(return_value=entry))
    monkeypatch.setattr(top32_service.audit_repo, "record", AsyncMock())

    result = await top32_service.disqualify(conn, "Alpha", actor_id=9, reason="no-show")  # type: ignore[arg-type]
    assert result.status == QualificationEntryStatus.DISQUALIFIED


@pytest.mark.asyncio
async def test_disqualify_blocked_before_lock(monkeypatch: pytest.MonkeyPatch) -> None:
    conn = _FakeConn()
    active = _season(phase=SeasonPhase.QUALIFICATION)
    monkeypatch.setattr(top32_service.seasons_repo, "get_active", AsyncMock(return_value=active))
    set_status_mock = AsyncMock()
    monkeypatch.setattr(top32_service.season_qualifications_repo, "set_status", set_status_mock)

    with pytest.raises(SeasonStateError):
        await top32_service.disqualify(conn, "Alpha", actor_id=9, reason="cheating")  # type: ignore[arg-type]
    set_status_mock.assert_not_awaited()
