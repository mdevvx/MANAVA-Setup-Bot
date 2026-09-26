"""Season state machine: /season lock, /season publish-top32, /season
complete. Each is a thin orchestration over seasons_repo + the
season_qualifications/season_history repos — this suite proves the
orchestration (audit logging, "no active season" guards), not the raw SQL."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from src.errors import SeasonStateError
from src.models.season import Season, SeasonPhase, SeasonStatus
from src.services import season_service


class _FakeTxn:
    async def __aenter__(self) -> "_FakeTxn":
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None


class _FakeConn:
    def transaction(self) -> _FakeTxn:
        return _FakeTxn()


def _season(*, phase: SeasonPhase, number: int = 7) -> Season:
    return Season(
        id=uuid4(),
        season_number=number,
        status=SeasonStatus.ACTIVE,
        started_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        started_by=1,
        ended_at=None,
        ended_by=None,
        phase=phase,
    )


@pytest.mark.asyncio
async def test_lock_qualification_snapshots_and_audits(monkeypatch: pytest.MonkeyPatch) -> None:
    conn = _FakeConn()
    active = _season(phase=SeasonPhase.QUALIFICATION)
    locked = _season(phase=SeasonPhase.QUALIFICATION_LOCK, number=active.season_number)
    monkeypatch.setattr(season_service.seasons_repo, "get_active", AsyncMock(return_value=active))
    lock_mock = AsyncMock(return_value=locked)
    monkeypatch.setattr(season_service.seasons_repo, "lock", lock_mock)
    monkeypatch.setattr(
        season_service.season_qualifications_repo, "snapshot_at_lock", AsyncMock(return_value=41)
    )
    audit = AsyncMock()
    monkeypatch.setattr(season_service.audit_repo, "record", audit)

    result = await season_service.lock_qualification(conn, actor_id=9)  # type: ignore[arg-type]

    assert result.squads_ranked == 41
    assert result.season_number == active.season_number
    lock_mock.assert_awaited_once_with(conn, active.id, actor_id=9)
    _, kwargs = audit.await_args
    assert kwargs["action"] == "season.lock"


@pytest.mark.asyncio
async def test_lock_qualification_with_no_active_season_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    conn = _FakeConn()
    monkeypatch.setattr(season_service.seasons_repo, "get_active", AsyncMock(return_value=None))
    lock_mock = AsyncMock()
    monkeypatch.setattr(season_service.seasons_repo, "lock", lock_mock)

    with pytest.raises(SeasonStateError):
        await season_service.lock_qualification(conn, actor_id=9)  # type: ignore[arg-type]
    lock_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_publish_top32_assigns_seeds_and_audits(monkeypatch: pytest.MonkeyPatch) -> None:
    conn = _FakeConn()
    active = _season(phase=SeasonPhase.QUALIFICATION_LOCK)
    published = _season(phase=SeasonPhase.TOP32_PLAYOFFS, number=active.season_number)
    monkeypatch.setattr(season_service.seasons_repo, "get_active", AsyncMock(return_value=active))
    publish_mock = AsyncMock(return_value=published)
    monkeypatch.setattr(season_service.seasons_repo, "advance_to_playoffs", publish_mock)
    monkeypatch.setattr(
        season_service.season_qualifications_repo, "assign_seeds_at_publish", AsyncMock(return_value=32)
    )
    audit = AsyncMock()
    monkeypatch.setattr(season_service.audit_repo, "record", audit)

    result = await season_service.publish_top32(conn, actor_id=9)  # type: ignore[arg-type]

    assert result.seeds_assigned == 32
    publish_mock.assert_awaited_once_with(conn, active.id, actor_id=9)
    _, kwargs = audit.await_args
    assert kwargs["action"] == "season.publish_top32"


@pytest.mark.asyncio
async def test_complete_season_persists_history_and_audits(monkeypatch: pytest.MonkeyPatch) -> None:
    conn = _FakeConn()
    active = _season(phase=SeasonPhase.TOP32_PLAYOFFS)
    completed = _season(phase=SeasonPhase.SEASON_COMPLETE, number=active.season_number)
    monkeypatch.setattr(season_service.seasons_repo, "get_active", AsyncMock(return_value=active))
    complete_mock = AsyncMock(return_value=completed)
    monkeypatch.setattr(season_service.seasons_repo, "mark_complete", complete_mock)
    monkeypatch.setattr(
        season_service.season_history_repo, "snapshot_all_active_squads", AsyncMock(return_value=58)
    )
    audit = AsyncMock()
    monkeypatch.setattr(season_service.audit_repo, "record", audit)

    result = await season_service.complete_season(conn, actor_id=9)  # type: ignore[arg-type]

    assert result.squads_recorded == 58
    complete_mock.assert_awaited_once_with(conn, active.id, actor_id=9)
    _, kwargs = audit.await_args
    assert kwargs["action"] == "season.complete"


@pytest.mark.asyncio
async def test_complete_season_with_no_active_season_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    conn = _FakeConn()
    monkeypatch.setattr(season_service.seasons_repo, "get_active", AsyncMock(return_value=None))
    complete_mock = AsyncMock()
    monkeypatch.setattr(season_service.seasons_repo, "mark_complete", complete_mock)

    with pytest.raises(SeasonStateError):
        await season_service.complete_season(conn, actor_id=9)  # type: ignore[arg-type]
    complete_mock.assert_not_awaited()
