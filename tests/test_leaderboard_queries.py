from __future__ import annotations

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from src.services import leaderboard_service


@pytest.mark.asyncio
async def test_global_leaderboard_maps_rows_to_entries(monkeypatch: pytest.MonkeyPatch) -> None:
    squad_id = uuid4()
    fake_rows = [
        {"rank": 1, "squad_id": squad_id, "squad_name": "Alpha", "season_xp": 500, "lifetime_xp": 900},
    ]
    monkeypatch.setattr(
        leaderboard_service.squad_xp_repo, "get_global_leaderboard", AsyncMock(return_value=fake_rows)
    )

    entries = await leaderboard_service.get_global_squad_leaderboard(None)  # type: ignore[arg-type]

    assert len(entries) == 1
    assert entries[0].rank == 1
    assert entries[0].squad_name == "Alpha"
    assert entries[0].season_xp == 500
    assert entries[0].lifetime_xp == 900


@pytest.mark.asyncio
async def test_member_leaderboard_maps_rows_to_entries(monkeypatch: pytest.MonkeyPatch) -> None:
    squad_id = uuid4()
    fake_rows = [
        {
            "rank": 1,
            "discord_user_id": 111,
            "squad_role": "leader",
            "personal_lifetime_xp": 2000,
            "personal_season_xp": 300,
            "contributed_xp": 250,
        },
        {
            "rank": 2,
            "discord_user_id": 222,
            "squad_role": "member",
            "personal_lifetime_xp": 1600,
            "personal_season_xp": 100,
            "contributed_xp": 90,
        },
    ]
    monkeypatch.setattr(leaderboard_service.memberships_repo, "get_member_leaderboard", AsyncMock(return_value=fake_rows))

    entries = await leaderboard_service.get_squad_member_leaderboard(None, squad_id)  # type: ignore[arg-type]

    assert [e.discord_user_id for e in entries] == [111, 222]
    assert entries[0].contributed_xp == 250
    assert entries[1].squad_role == "member"
