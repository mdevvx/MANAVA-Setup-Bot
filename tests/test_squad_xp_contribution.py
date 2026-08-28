from __future__ import annotations

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from src.errors import BotUserError
from src.models.xp import SquadXp
from src.services import squad_xp_service


@pytest.mark.asyncio
async def test_squad_level_stays_at_1_below_first_threshold(monkeypatch: pytest.MonkeyPatch) -> None:
    squad_id = uuid4()
    monkeypatch.setattr(
        squad_xp_service.squad_xp_repo, "get", AsyncMock(return_value=SquadXp(squad_id=squad_id, lifetime_xp=100, season_xp=0))
    )
    monkeypatch.setattr(
        squad_xp_service.level_thresholds_repo,
        "get_all",
        AsyncMock(return_value={2: 5000, 3: 15000, 4: 40000, 5: 100000, 6: 250000, 7: 600000}),
    )

    level = await squad_xp_service.get_squad_level(None, squad_id)  # type: ignore[arg-type]
    assert level == 1


@pytest.mark.asyncio
async def test_squad_level_advances_past_multiple_thresholds(monkeypatch: pytest.MonkeyPatch) -> None:
    squad_id = uuid4()
    monkeypatch.setattr(
        squad_xp_service.squad_xp_repo,
        "get",
        AsyncMock(return_value=SquadXp(squad_id=squad_id, lifetime_xp=42000, season_xp=0)),
    )
    monkeypatch.setattr(
        squad_xp_service.level_thresholds_repo,
        "get_all",
        AsyncMock(return_value={2: 5000, 3: 15000, 4: 40000, 5: 100000, 6: 250000, 7: 600000}),
    )

    level = await squad_xp_service.get_squad_level(None, squad_id)  # type: ignore[arg-type]
    assert level == 4  # past L2, L3, L4 thresholds but not L5


@pytest.mark.asyncio
async def test_capacity_blocks_new_member_when_full(monkeypatch: pytest.MonkeyPatch) -> None:
    squad_id = uuid4()
    monkeypatch.setattr(
        squad_xp_service.squad_xp_repo, "get", AsyncMock(return_value=SquadXp(squad_id=squad_id, lifetime_xp=0, season_xp=0))
    )
    monkeypatch.setattr(squad_xp_service.level_thresholds_repo, "get_all", AsyncMock(return_value={}))
    # Level 1 cap is 20 members (fixed constant) — simulate already being full.
    monkeypatch.setattr(squad_xp_service.memberships_repo, "count_active_members", AsyncMock(return_value=20))

    with pytest.raises(BotUserError):
        await squad_xp_service.ensure_capacity_for_new_member(None, squad_id)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_capacity_allows_new_member_below_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    squad_id = uuid4()
    monkeypatch.setattr(
        squad_xp_service.squad_xp_repo, "get", AsyncMock(return_value=SquadXp(squad_id=squad_id, lifetime_xp=0, season_xp=0))
    )
    monkeypatch.setattr(squad_xp_service.level_thresholds_repo, "get_all", AsyncMock(return_value={}))
    monkeypatch.setattr(squad_xp_service.memberships_repo, "count_active_members", AsyncMock(return_value=19))

    await squad_xp_service.ensure_capacity_for_new_member(None, squad_id)  # type: ignore[arg-type]
