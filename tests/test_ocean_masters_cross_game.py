"""Cross-game scoring: one point per discipline win, higher total wins the
matchup. On an equal tally, the only implemented rule (staff_manual) leaves
the match pending rather than guessing."""

from __future__ import annotations

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from src.errors import OceanMastersStateError
from src.models.ocean_masters import MatchStatus, OceanMastersMatch, OceanMastersMode
from src.services import ocean_masters_service


class _FakeTxn:
    async def __aenter__(self) -> "_FakeTxn":
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None


class _FakeConn:
    def transaction(self) -> _FakeTxn:
        return _FakeTxn()


def _match(
    *,
    tournament_id: object,
    squad_a_id: object,
    squad_b_id: object,
    per_discipline_results: dict[str, str] | None = None,
    winner_squad_id: object | None = None,
    status: MatchStatus = MatchStatus.PENDING,
) -> OceanMastersMatch:
    return OceanMastersMatch(
        id=uuid4(),
        tournament_id=tournament_id,  # type: ignore[arg-type]
        round=1,
        seed_a=1,
        seed_b=2,
        squad_a_id=squad_a_id,  # type: ignore[arg-type]
        squad_b_id=squad_b_id,  # type: ignore[arg-type]
        squad_a_name="Alpha",
        squad_b_name="Bravo",
        per_discipline_results=per_discipline_results or {},
        winner_squad_id=winner_squad_id,  # type: ignore[arg-type]
        status=status,
        decided_by=None,
        decided_at=None,
        decided_reason=None,
    )


def _tournament(*, games: tuple[str, ...], mode: OceanMastersMode = OceanMastersMode.CROSS_GAME) -> object:
    from datetime import datetime, timezone

    from src.models.ocean_masters import OceanMasters, OceanMastersStatus

    return OceanMasters(
        id=uuid4(),
        season_id=uuid4(),
        mode=mode,
        games=games,
        min_squads_required=None,
        status=OceanMastersStatus.LAUNCHED,
        launched_at=None,
        launched_by=None,
        completed_at=None,
        winner_squad_id=None,
        created_by=1,
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )


@pytest.mark.asyncio
async def test_rejects_game_not_in_tournament(monkeypatch: pytest.MonkeyPatch) -> None:
    conn = _FakeConn()
    a, b = uuid4(), uuid4()
    match = _match(tournament_id=uuid4(), squad_a_id=a, squad_b_id=b)
    monkeypatch.setattr(ocean_masters_service.ocean_masters_repo, "get_match", AsyncMock(return_value=match))
    monkeypatch.setattr(
        ocean_masters_service.ocean_masters_repo, "get_by_id", AsyncMock(return_value=_tournament(games=("cs2", "swag")))
    )

    with pytest.raises(OceanMastersStateError):
        await ocean_masters_service.set_discipline_result(
            conn, match.id, game="billiard", winner_squad_id=a, actor_id=1, channels=None  # type: ignore[arg-type]
        )


@pytest.mark.asyncio
async def test_single_game_tournament_rejects_discipline_result(monkeypatch: pytest.MonkeyPatch) -> None:
    conn = _FakeConn()
    a, b = uuid4(), uuid4()
    match = _match(tournament_id=uuid4(), squad_a_id=a, squad_b_id=b)
    monkeypatch.setattr(ocean_masters_service.ocean_masters_repo, "get_match", AsyncMock(return_value=match))
    monkeypatch.setattr(
        ocean_masters_service.ocean_masters_repo,
        "get_by_id",
        AsyncMock(return_value=_tournament(games=("cs2",), mode=OceanMastersMode.SINGLE_GAME)),
    )

    with pytest.raises(OceanMastersStateError):
        await ocean_masters_service.set_discipline_result(
            conn, match.id, game="cs2", winner_squad_id=a, actor_id=1, channels=None  # type: ignore[arg-type]
        )


@pytest.mark.asyncio
async def test_match_stays_pending_until_all_games_reported(monkeypatch: pytest.MonkeyPatch) -> None:
    conn = _FakeConn()
    a, b = uuid4(), uuid4()
    match = _match(tournament_id=uuid4(), squad_a_id=a, squad_b_id=b)
    monkeypatch.setattr(ocean_masters_service.ocean_masters_repo, "get_match", AsyncMock(return_value=match))
    monkeypatch.setattr(
        ocean_masters_service.ocean_masters_repo, "get_by_id", AsyncMock(return_value=_tournament(games=("cs2", "swag")))
    )
    one_game_in = _match(tournament_id=match.tournament_id, squad_a_id=a, squad_b_id=b, per_discipline_results={"cs2": str(a)})
    monkeypatch.setattr(
        ocean_masters_service.ocean_masters_repo, "set_discipline_result", AsyncMock(return_value=one_game_in)
    )
    monkeypatch.setattr(ocean_masters_service.audit_repo, "record", AsyncMock())
    decide_mock = AsyncMock()
    monkeypatch.setattr(ocean_masters_service.ocean_masters_repo, "decide_match", decide_mock)

    result = await ocean_masters_service.set_discipline_result(
        conn, match.id, game="cs2", winner_squad_id=a, actor_id=1, channels=None  # type: ignore[arg-type]
    )

    assert result.match.status is MatchStatus.PENDING
    decide_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_resolves_winner_once_every_game_is_in(monkeypatch: pytest.MonkeyPatch) -> None:
    conn = _FakeConn()
    a, b = uuid4(), uuid4()
    match = _match(tournament_id=uuid4(), squad_a_id=a, squad_b_id=b)
    monkeypatch.setattr(ocean_masters_service.ocean_masters_repo, "get_match", AsyncMock(return_value=match))
    monkeypatch.setattr(
        ocean_masters_service.ocean_masters_repo, "get_by_id", AsyncMock(return_value=_tournament(games=("cs2", "swag")))
    )
    # a won cs2 and swag -> 2-0, a is the overall winner.
    both_in = _match(
        tournament_id=match.tournament_id,
        squad_a_id=a,
        squad_b_id=b,
        per_discipline_results={"cs2": str(a), "swag": str(a)},
    )
    monkeypatch.setattr(ocean_masters_service.ocean_masters_repo, "set_discipline_result", AsyncMock(return_value=both_in))
    monkeypatch.setattr(ocean_masters_service.audit_repo, "record", AsyncMock())
    decided = _match(tournament_id=match.tournament_id, squad_a_id=a, squad_b_id=b, winner_squad_id=a, status=MatchStatus.COMPLETED)
    decide_mock = AsyncMock(return_value=decided)
    monkeypatch.setattr(ocean_masters_service.ocean_masters_repo, "decide_match", decide_mock)
    monkeypatch.setattr(
        ocean_masters_service.ocean_masters_repo, "get_round_matches", AsyncMock(return_value=[decided])
    )
    monkeypatch.setattr(ocean_masters_service.ocean_masters_repo, "mark_completed", AsyncMock())

    result = await ocean_masters_service.set_discipline_result(
        conn, match.id, game="swag", winner_squad_id=a, actor_id=1, channels=None  # type: ignore[arg-type]
    )

    decide_mock.assert_awaited_once()
    _, kwargs = decide_mock.await_args
    assert kwargs["winner_squad_id"] == a
    assert result.tournament_completed is True


@pytest.mark.asyncio
async def test_tie_leaves_match_pending_for_staff_resolution(monkeypatch: pytest.MonkeyPatch) -> None:
    conn = _FakeConn()
    a, b = uuid4(), uuid4()
    match = _match(tournament_id=uuid4(), squad_a_id=a, squad_b_id=b)
    monkeypatch.setattr(ocean_masters_service.ocean_masters_repo, "get_match", AsyncMock(return_value=match))
    monkeypatch.setattr(
        ocean_masters_service.ocean_masters_repo,
        "get_by_id",
        AsyncMock(return_value=_tournament(games=("cs2", "swag"))),
    )
    # a won cs2, b won swag -> 1-1 tie.
    tied = _match(
        tournament_id=match.tournament_id,
        squad_a_id=a,
        squad_b_id=b,
        per_discipline_results={"cs2": str(a), "swag": str(b)},
    )
    monkeypatch.setattr(ocean_masters_service.ocean_masters_repo, "set_discipline_result", AsyncMock(return_value=tied))
    monkeypatch.setattr(ocean_masters_service.audit_repo, "record", AsyncMock())
    decide_mock = AsyncMock()
    monkeypatch.setattr(ocean_masters_service.ocean_masters_repo, "decide_match", decide_mock)

    result = await ocean_masters_service.set_discipline_result(
        conn, match.id, game="swag", winner_squad_id=b, actor_id=1, channels=None  # type: ignore[arg-type]
    )

    decide_mock.assert_not_awaited()
    assert result.match.status is MatchStatus.PENDING
