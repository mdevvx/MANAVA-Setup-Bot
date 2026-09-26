"""Season Complete persists history from ANY non-terminal phase — including a
season that never went through Qualification Lock at all (no Top-32 /
Ocean Masters that cycle), which should still close out cleanly."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

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


def _season(*, phase: SeasonPhase) -> Season:
    return Season(
        id=uuid4(),
        season_number=11,
        status=SeasonStatus.ACTIVE,
        started_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        started_by=1,
        ended_at=None,
        ended_by=None,
        phase=phase,
    )


@pytest.mark.parametrize(
    "phase",
    [SeasonPhase.QUALIFICATION, SeasonPhase.QUALIFICATION_LOCK, SeasonPhase.TOP32_PLAYOFFS],
)
@pytest.mark.asyncio
async def test_complete_season_works_from_any_non_terminal_phase(
    monkeypatch: pytest.MonkeyPatch, phase: SeasonPhase
) -> None:
    conn = _FakeConn()
    active = _season(phase=phase)
    # mark_complete returns the row AFTER the update — same id as `active`,
    # just with status/phase flipped, exactly like the real UPDATE...RETURNING.
    completed = replace(active, phase=SeasonPhase.SEASON_COMPLETE)
    monkeypatch.setattr(season_service.seasons_repo, "get_active", AsyncMock(return_value=active))
    monkeypatch.setattr(season_service.seasons_repo, "mark_complete", AsyncMock(return_value=completed))
    snapshot_mock = AsyncMock(return_value=17)
    monkeypatch.setattr(season_service.season_history_repo, "snapshot_all_active_squads", snapshot_mock)
    monkeypatch.setattr(season_service.audit_repo, "record", AsyncMock())

    result = await season_service.complete_season(conn, actor_id=5)  # type: ignore[arg-type]

    assert result.squads_recorded == 17
    snapshot_mock.assert_awaited_once_with(conn, active.id)


@pytest.mark.asyncio
async def test_complete_season_does_not_reset_xp_or_open_new_season(monkeypatch: pytest.MonkeyPatch) -> None:
    """Client-approved 2026-09-23: /season complete only finalizes and
    persists history. Resetting XP and opening the next season stay
    /season new's job, untouched by this call."""
    conn = _FakeConn()
    active = _season(phase=SeasonPhase.TOP32_PLAYOFFS)
    monkeypatch.setattr(season_service.seasons_repo, "get_active", AsyncMock(return_value=active))
    monkeypatch.setattr(
        season_service.seasons_repo, "mark_complete", AsyncMock(return_value=_season(phase=SeasonPhase.SEASON_COMPLETE))
    )
    monkeypatch.setattr(season_service.season_history_repo, "snapshot_all_active_squads", AsyncMock(return_value=0))
    monkeypatch.setattr(season_service.audit_repo, "record", AsyncMock())
    personal_reset = AsyncMock()
    squad_reset = AsyncMock()
    start_mock = AsyncMock()
    monkeypatch.setattr(season_service.personal_xp_repo, "reset_all_season_xp", personal_reset)
    monkeypatch.setattr(season_service.squad_xp_repo, "reset_all_season_xp", squad_reset)
    monkeypatch.setattr(season_service.seasons_repo, "start", start_mock)

    await season_service.complete_season(conn, actor_id=5)  # type: ignore[arg-type]

    personal_reset.assert_not_awaited()
    squad_reset.assert_not_awaited()
    start_mock.assert_not_awaited()
