"""_compute_xp — the per-event-type XP formula. Regression coverage for a
client-reported bug (2026-09-15): a tournament_placement event was also
re-granting the tournament_participation_xp base, double-counting
participation for any player who both registered and placed in the same
tournament."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest

from src import constants
from src.models.xp import ManavaEvent
from src.services import manava_event_service

_CONFIG = {
    constants.XP_CONFIG_KEY_SKILL_MATCH: 50,
    constants.XP_CONFIG_KEY_TOURNAMENT_PARTICIPATION: 100,
    constants.XP_CONFIG_KEY_PLACEMENT_1ST: 500,
    constants.XP_CONFIG_KEY_PLACEMENT_2ND: 300,
    constants.XP_CONFIG_KEY_PLACEMENT_3RD: 150,
    constants.XP_CONFIG_KEY_PRIZE_SLOT_BONUS: 0,
}


def _event(event_type: str, *, place: int | None = None, won_prize_slot: bool | None = None) -> ManavaEvent:
    return ManavaEvent(
        event_id="evt-1",
        manava_user_id="manava-1",
        event_type=event_type,
        game="cs2",
        timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
        match_id=None,
        tournament_id="trn-1",
        result=None,
        place=place,
        won_prize_slot=won_prize_slot,
    )


@pytest.mark.asyncio
async def test_match_completed_grants_skill_match_xp(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(manava_event_service.xp_config_repo, "get_all", AsyncMock(return_value=_CONFIG))
    xp = await manava_event_service._compute_xp(None, _event(constants.MANAVA_EVENT_MATCH_COMPLETED))  # type: ignore[arg-type]
    assert xp == 50


@pytest.mark.asyncio
async def test_tournament_registered_grants_participation_xp(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(manava_event_service.xp_config_repo, "get_all", AsyncMock(return_value=_CONFIG))
    xp = await manava_event_service._compute_xp(None, _event(constants.MANAVA_EVENT_TOURNAMENT_REGISTERED))  # type: ignore[arg-type]
    assert xp == 100


@pytest.mark.asyncio
async def test_tournament_placement_does_not_repeat_participation_xp(monkeypatch: pytest.MonkeyPatch) -> None:
    """The fix: a placement event grants only the placement bonus (+ prize-slot
    bonus), never the participation base again — tournament_registered already
    covered that for the same tournament."""
    monkeypatch.setattr(manava_event_service.xp_config_repo, "get_all", AsyncMock(return_value=_CONFIG))
    xp = await manava_event_service._compute_xp(  # type: ignore[arg-type]
        None, _event(constants.MANAVA_EVENT_TOURNAMENT_PLACEMENT, place=1)
    )
    assert xp == 500  # placement_reward_1 only, NOT 100 + 500


@pytest.mark.asyncio
async def test_tournament_placement_adds_prize_slot_bonus_on_top(monkeypatch: pytest.MonkeyPatch) -> None:
    config = {**_CONFIG, constants.XP_CONFIG_KEY_PRIZE_SLOT_BONUS: 200}
    monkeypatch.setattr(manava_event_service.xp_config_repo, "get_all", AsyncMock(return_value=config))
    xp = await manava_event_service._compute_xp(  # type: ignore[arg-type]
        None, _event(constants.MANAVA_EVENT_TOURNAMENT_PLACEMENT, place=2, won_prize_slot=True)
    )
    assert xp == 500  # placement_reward_2 (300) + prize_slot_bonus_xp (200)


@pytest.mark.asyncio
async def test_tournament_placement_outside_top_3_grants_no_placement_bonus(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(manava_event_service.xp_config_repo, "get_all", AsyncMock(return_value=_CONFIG))
    xp = await manava_event_service._compute_xp(  # type: ignore[arg-type]
        None, _event(constants.MANAVA_EVENT_TOURNAMENT_PLACEMENT, place=7)
    )
    assert xp == 0
