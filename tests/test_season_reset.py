"""Season reset: Start New Season zeroes Season XP (personal + squad) but never
touches Lifetime XP, always opens a fresh season, and records the actor."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from src.errors import SeasonStateError
from src.models.season import Season, SeasonStatus
from src.services import season_service


class _FakeTxn:
    async def __aenter__(self) -> "_FakeTxn":
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None


class _FakeConn:
    """Just enough of an asyncpg connection for season_service: a transaction()
    context manager. All real DB access is monkeypatched at the repo layer."""

    def transaction(self) -> _FakeTxn:
        return _FakeTxn()


def _season(number: int, status: SeasonStatus) -> Season:
    return Season(
        id=uuid4(),
        season_number=number,
        status=status,
        started_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        started_by=1,
        ended_at=None,
        ended_by=None,
    )


@pytest.mark.asyncio
async def test_start_new_season_resets_season_xp_only(monkeypatch: pytest.MonkeyPatch) -> None:
    conn = _FakeConn()
    audit = AsyncMock()

    monkeypatch.setattr(season_service.seasons_repo, "get_active", AsyncMock(return_value=_season(3, SeasonStatus.ACTIVE)))
    end_mock = AsyncMock(return_value=_season(3, SeasonStatus.ENDED))
    monkeypatch.setattr(season_service.seasons_repo, "end_active", end_mock)
    monkeypatch.setattr(season_service.seasons_repo, "start", AsyncMock(return_value=_season(4, SeasonStatus.ACTIVE)))
    personal_reset = AsyncMock(return_value=12)
    squad_reset = AsyncMock(return_value=5)
    monkeypatch.setattr(season_service.personal_xp_repo, "reset_all_season_xp", personal_reset)
    monkeypatch.setattr(season_service.squad_xp_repo, "reset_all_season_xp", squad_reset)
    monkeypatch.setattr(season_service.audit_repo, "record", audit)

    result = await season_service.start_new_season(conn, actor_id=99)  # type: ignore[arg-type]

    assert result.ended_season_number == 3
    assert result.new_season_number == 4
    assert result.personal_rows_reset == 12
    assert result.squad_rows_reset == 5
    personal_reset.assert_awaited_once()
    squad_reset.assert_awaited_once()

    # The actor is recorded, and only season-scoped values move.
    _, kwargs = audit.await_args
    assert kwargs["actor_id"] == 99
    assert kwargs["action"] == "season.start_new"
    assert "lifetime" not in str(kwargs).lower()


@pytest.mark.asyncio
async def test_start_new_season_with_no_active_season(monkeypatch: pytest.MonkeyPatch) -> None:
    conn = _FakeConn()

    monkeypatch.setattr(season_service.seasons_repo, "get_active", AsyncMock(return_value=None))
    end_mock = AsyncMock()
    monkeypatch.setattr(season_service.seasons_repo, "end_active", end_mock)
    monkeypatch.setattr(season_service.seasons_repo, "start", AsyncMock(return_value=_season(1, SeasonStatus.ACTIVE)))
    monkeypatch.setattr(season_service.personal_xp_repo, "reset_all_season_xp", AsyncMock(return_value=0))
    monkeypatch.setattr(season_service.squad_xp_repo, "reset_all_season_xp", AsyncMock(return_value=0))
    monkeypatch.setattr(season_service.audit_repo, "record", AsyncMock())

    result = await season_service.start_new_season(conn, actor_id=7)  # type: ignore[arg-type]

    assert result.ended_season_number is None
    assert result.new_season_number == 1
    end_mock.assert_not_awaited()  # nothing to end


@pytest.mark.asyncio
async def test_end_season_with_none_active_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    conn = _FakeConn()
    monkeypatch.setattr(
        season_service.seasons_repo,
        "end_active",
        AsyncMock(side_effect=SeasonStateError("There's no active season to end.")),
    )
    monkeypatch.setattr(season_service.audit_repo, "record", AsyncMock())

    with pytest.raises(SeasonStateError):
        await season_service.end_season(conn, actor_id=1)  # type: ignore[arg-type]
