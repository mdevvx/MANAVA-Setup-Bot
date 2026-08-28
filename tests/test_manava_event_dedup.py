"""Hard correctness requirement: a retried/duplicate MANAVA event_id must
never grant XP twice."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest

from src import constants
from src.models.xp import ManavaEvent
from src.services import manava_event_service


def _fake_event(event_id: str = "evt-1") -> ManavaEvent:
    return ManavaEvent(
        event_id=event_id,
        manava_user_id="manava-123",
        event_type=constants.MANAVA_EVENT_SKILL_MATCH_COMPLETED,
        game="Test Game",
        timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
        match_id=None,
        tournament_id=None,
        result=None,
        placement=None,
    )


@pytest.mark.asyncio
async def test_duplicate_event_id_never_grants_xp_twice(monkeypatch: pytest.MonkeyPatch) -> None:
    event = _fake_event()

    # First call "wins" the reservation (True), second call finds it already
    # claimed (False) — exactly what the DB's unique constraint on event_id
    # would produce for a genuine retry/duplicate delivery.
    reserve_mock = AsyncMock(side_effect=[True, False])
    monkeypatch.setattr(manava_event_service.processed_events_repo, "reserve", reserve_mock)
    monkeypatch.setattr(manava_event_service.processed_events_repo, "finalize", AsyncMock())
    monkeypatch.setattr(
        manava_event_service.personal_xp_repo, "get_discord_user_id_by_manava_id", AsyncMock(return_value=42)
    )
    monkeypatch.setattr(
        manava_event_service.xp_config_repo, "get_all", AsyncMock(return_value={"skill_match_xp": 50})
    )
    grant_mock = AsyncMock()
    monkeypatch.setattr(manava_event_service.xp_service, "grant_personal_xp", grant_mock)
    monkeypatch.setattr(manava_event_service.audit_repo, "record", AsyncMock())

    first = await manava_event_service.process_event(None, event)  # type: ignore[arg-type]
    second = await manava_event_service.process_event(None, event)  # type: ignore[arg-type]

    assert first.status == "processed"
    assert first.xp_granted == 50
    assert second.status == "duplicate"
    assert second.xp_granted == 0

    # The real, hard assertion: XP was only ever granted once, for the first call.
    assert grant_mock.await_count == 1


@pytest.mark.asyncio
async def test_unresolved_manava_user_grants_no_xp(monkeypatch: pytest.MonkeyPatch) -> None:
    event = _fake_event(event_id="evt-2")

    monkeypatch.setattr(manava_event_service.processed_events_repo, "reserve", AsyncMock(return_value=True))
    monkeypatch.setattr(manava_event_service.processed_events_repo, "finalize", AsyncMock())
    monkeypatch.setattr(
        manava_event_service.personal_xp_repo, "get_discord_user_id_by_manava_id", AsyncMock(return_value=None)
    )
    grant_mock = AsyncMock()
    monkeypatch.setattr(manava_event_service.xp_service, "grant_personal_xp", grant_mock)

    outcome = await manava_event_service.process_event(None, event)  # type: ignore[arg-type]

    assert outcome.status == "unresolved_user"
    assert outcome.xp_granted == 0
    grant_mock.assert_not_awaited()
