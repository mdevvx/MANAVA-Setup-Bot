from __future__ import annotations

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from src.models.season import Season, SeasonStatus
from src.models.squad import SquadMembership, SquadRole
from src.models.xp import PersonalXp, SquadXp
from src.services import xp_service

DISCORD_USER_ID = 111222333


def _personal_xp(*, lifetime: int, season: int) -> PersonalXp:
    return PersonalXp(
        discord_user_id=DISCORD_USER_ID,
        verified_player=True,
        manava_user_id=None,
        lifetime_xp=lifetime,
        season_xp=season,
    )


def _membership(squad_id: object) -> SquadMembership:
    return SquadMembership(
        id=uuid4(),
        squad_id=squad_id,  # type: ignore[arg-type]
        discord_user_id=DISCORD_USER_ID,
        squad_role=SquadRole.MEMBER,
        joined_at=None,  # type: ignore[arg-type]
        left_at=None,
        contributed_xp=0,
    )


def _active_season() -> Season:
    return Season(
        id=uuid4(),
        season_number=1,
        status=SeasonStatus.ACTIVE,
        started_at=None,  # type: ignore[arg-type]
        started_by=1,
        ended_at=None,
        ended_by=None,
    )


@pytest.mark.asyncio
async def test_grant_xp_moves_season_xp_while_season_active(monkeypatch: pytest.MonkeyPatch) -> None:
    """The common case: a season is running, so both lifetime_xp and season_xp
    move together — the pre-existing behaviour."""
    monkeypatch.setattr(xp_service.seasons_repo, "get_active", AsyncMock(return_value=_active_season()))
    add_xp_mock = AsyncMock(return_value=_personal_xp(lifetime=1015, season=1015))
    monkeypatch.setattr(xp_service.xp_repo, "add_xp", add_xp_mock)
    monkeypatch.setattr(xp_service.memberships_repo, "get_active_membership", AsyncMock(return_value=None))

    result = await xp_service.grant_personal_xp(None, DISCORD_USER_ID, 15)  # type: ignore[arg-type]

    add_xp_mock.assert_awaited_once_with(None, DISCORD_USER_ID, 15, season_active=True)
    assert result.season_xp == 1015


@pytest.mark.asyncio
async def test_grant_xp_freezes_season_xp_between_seasons(monkeypatch: pytest.MonkeyPatch) -> None:
    """Regression for the client-reported bug: after /season end (no active
    season yet), Discord/MANAVA XP grants must keep raising Lifetime XP but
    must NOT move Personal Season XP or Squad Season XP."""
    monkeypatch.setattr(xp_service.seasons_repo, "get_active", AsyncMock(return_value=None))
    add_xp_mock = AsyncMock(return_value=_personal_xp(lifetime=1030, season=1000))
    monkeypatch.setattr(xp_service.xp_repo, "add_xp", add_xp_mock)

    squad_id = uuid4()
    membership = _membership(squad_id)
    monkeypatch.setattr(xp_service.memberships_repo, "get_active_membership", AsyncMock(return_value=membership))
    squad_add_xp_mock = AsyncMock(return_value=SquadXp(squad_id=squad_id, lifetime_xp=5000, season_xp=2000))
    monkeypatch.setattr(xp_service.squad_xp_repo, "add_xp", squad_add_xp_mock)
    contributed_mock = AsyncMock()
    monkeypatch.setattr(xp_service.memberships_repo, "add_contributed_xp", contributed_mock)

    result = await xp_service.grant_personal_xp(None, DISCORD_USER_ID, 15)  # type: ignore[arg-type]

    add_xp_mock.assert_awaited_once_with(None, DISCORD_USER_ID, 15, season_active=False)
    squad_add_xp_mock.assert_awaited_once_with(None, squad_id, 15, season_active=False)
    # Lifetime keeps growing; season_xp on the mocked-back row is unchanged from before the grant.
    assert result.lifetime_xp == 1030
    assert result.season_xp == 1000
    # Contribution is a per-stint lifetime figure — never season-gated.
    contributed_mock.assert_awaited_once_with(None, membership.id, 15)


@pytest.mark.asyncio
async def test_grant_xp_cascades_to_squad_with_matching_season_state(monkeypatch: pytest.MonkeyPatch) -> None:
    """The squad cascade must use the *same* season_active value as the
    personal grant in the same call — they can never disagree."""
    monkeypatch.setattr(xp_service.seasons_repo, "get_active", AsyncMock(return_value=_active_season()))
    monkeypatch.setattr(xp_service.xp_repo, "add_xp", AsyncMock(return_value=_personal_xp(lifetime=100, season=100)))

    squad_id = uuid4()
    membership = _membership(squad_id)
    monkeypatch.setattr(xp_service.memberships_repo, "get_active_membership", AsyncMock(return_value=membership))
    squad_add_xp_mock = AsyncMock(return_value=SquadXp(squad_id=squad_id, lifetime_xp=100, season_xp=100))
    monkeypatch.setattr(xp_service.squad_xp_repo, "add_xp", squad_add_xp_mock)
    monkeypatch.setattr(xp_service.memberships_repo, "add_contributed_xp", AsyncMock())

    await xp_service.grant_personal_xp(None, DISCORD_USER_ID, 50)  # type: ignore[arg-type]

    squad_add_xp_mock.assert_awaited_once_with(None, squad_id, 50, season_active=True)
