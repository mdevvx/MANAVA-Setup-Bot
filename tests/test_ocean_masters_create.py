"""Ocean Masters creation: mode/game validation, the Cross-game tie-rule
block, and the Top-32-must-be-published precondition."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from src.errors import OceanMastersStateError
from src.models.ocean_masters import CreateResult, MatchStatus, OceanMastersMatch, OceanMastersMode
from src.models.season import QualificationEntry, QualificationEntryStatus, Season, SeasonPhase, SeasonStatus
from src.services import ocean_masters_service


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
        season_number=4,
        status=SeasonStatus.ACTIVE,
        started_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        started_by=1,
        ended_at=None,
        ended_by=None,
        phase=phase,
    )


def _qualified_entries(n: int, *, seeded: bool = True) -> list[QualificationEntry]:
    return [
        QualificationEntry(
            season_id=uuid4(),
            squad_id=uuid4(),
            squad_name=f"Squad{i}",
            rank=i,
            season_xp_snapshot=1000 - i,
            lifetime_xp_snapshot=5000 - i,
            status=QualificationEntryStatus.QUALIFIED,
            seed=i if seeded else None,
            decided_by=None,
            decided_at=None,
            decided_reason=None,
        )
        for i in range(1, n + 1)
    ]


def _patch_common(monkeypatch: pytest.MonkeyPatch, *, season: Season, entries: list[QualificationEntry]) -> None:
    monkeypatch.setattr(ocean_masters_service.seasons_repo, "get_active", AsyncMock(return_value=season))
    monkeypatch.setattr(
        ocean_masters_service.season_qualifications_repo, "get_top32_window", AsyncMock(return_value=entries)
    )
    monkeypatch.setattr(ocean_masters_service.bot_config_repo, "get_ocean_masters_min_squads", AsyncMock(return_value=None))
    monkeypatch.setattr(ocean_masters_service.audit_repo, "record", AsyncMock())


@pytest.mark.asyncio
async def test_single_game_requires_exactly_one_game(monkeypatch: pytest.MonkeyPatch) -> None:
    conn = _FakeConn()
    with pytest.raises(OceanMastersStateError):
        await ocean_masters_service.create_tournament(
            conn, mode=OceanMastersMode.SINGLE_GAME, games=["cs2", "swag"], created_by=1  # type: ignore[arg-type]
        )


@pytest.mark.asyncio
async def test_cross_game_requires_at_least_two_games(monkeypatch: pytest.MonkeyPatch) -> None:
    conn = _FakeConn()
    with pytest.raises(OceanMastersStateError):
        await ocean_masters_service.create_tournament(
            conn, mode=OceanMastersMode.CROSS_GAME, games=["cs2"], created_by=1  # type: ignore[arg-type]
        )


@pytest.mark.asyncio
async def test_unknown_game_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    conn = _FakeConn()
    with pytest.raises(OceanMastersStateError):
        await ocean_masters_service.create_tournament(
            conn, mode=OceanMastersMode.SINGLE_GAME, games=["chess"], created_by=1  # type: ignore[arg-type]
        )


@pytest.mark.asyncio
async def test_cross_game_blocked_until_tie_rule_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    conn = _FakeConn()
    monkeypatch.setattr(ocean_masters_service.bot_config_repo, "get_cross_game_tie_rule", AsyncMock(return_value=None))
    create_mock = AsyncMock()
    monkeypatch.setattr(ocean_masters_service.ocean_masters_repo, "create_tournament", create_mock)

    with pytest.raises(OceanMastersStateError):
        await ocean_masters_service.create_tournament(
            conn, mode=OceanMastersMode.CROSS_GAME, games=["cs2", "swag"], created_by=1  # type: ignore[arg-type]
        )
    create_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_blocked_before_top32_is_published(monkeypatch: pytest.MonkeyPatch) -> None:
    conn = _FakeConn()
    season = _season(phase=SeasonPhase.QUALIFICATION_LOCK)  # locked, not yet published
    _patch_common(monkeypatch, season=season, entries=[])
    create_mock = AsyncMock()
    monkeypatch.setattr(ocean_masters_service.ocean_masters_repo, "create_tournament", create_mock)

    with pytest.raises(OceanMastersStateError):
        await ocean_masters_service.create_tournament(
            conn, mode=OceanMastersMode.SINGLE_GAME, games=["cs2"], created_by=1  # type: ignore[arg-type]
        )
    create_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_blocked_if_qualification_entries_have_no_seed_yet(monkeypatch: pytest.MonkeyPatch) -> None:
    """Phase says top32_playoffs but the seed-assignment step somehow never
    ran — treat that defensively as "not published" rather than trusting the
    phase alone."""
    conn = _FakeConn()
    season = _season(phase=SeasonPhase.TOP32_PLAYOFFS)
    _patch_common(monkeypatch, season=season, entries=_qualified_entries(32, seeded=False))
    create_mock = AsyncMock()
    monkeypatch.setattr(ocean_masters_service.ocean_masters_repo, "create_tournament", create_mock)

    with pytest.raises(OceanMastersStateError):
        await ocean_masters_service.create_tournament(
            conn, mode=OceanMastersMode.SINGLE_GAME, games=["cs2"], created_by=1  # type: ignore[arg-type]
        )
    create_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_happy_path_creates_16_first_round_matches(monkeypatch: pytest.MonkeyPatch) -> None:
    conn = _FakeConn()
    season = _season(phase=SeasonPhase.TOP32_PLAYOFFS)
    entries = _qualified_entries(32)
    _patch_common(monkeypatch, season=season, entries=entries)

    tournament_id = uuid4()
    create_mock = AsyncMock(
        return_value=type(
            "T", (), {"id": tournament_id, "season_id": season.id, "mode": OceanMastersMode.SINGLE_GAME}
        )()
    )
    monkeypatch.setattr(ocean_masters_service.ocean_masters_repo, "create_tournament", create_mock)
    insert_round_mock = AsyncMock(return_value=16)
    monkeypatch.setattr(ocean_masters_service.ocean_masters_repo, "insert_round", insert_round_mock)
    # No byes with exactly 32 real squads — every match has both sides filled
    # and no winner yet, so _try_advance_round/_resolve_byes should no-op.
    pending_matches = [
        OceanMastersMatch(
            id=uuid4(),
            tournament_id=tournament_id,
            round=1,
            seed_a=i,
            seed_b=33 - i,
            squad_a_id=uuid4(),
            squad_b_id=uuid4(),
            squad_a_name=f"SeedA{i}",
            squad_b_name=f"SeedB{i}",
            per_discipline_results={},
            winner_squad_id=None,
            status=MatchStatus.PENDING,
            decided_by=None,
            decided_at=None,
            decided_reason=None,
        )
        for i in range(1, 17)
    ]
    monkeypatch.setattr(
        ocean_masters_service.ocean_masters_repo, "get_round_matches", AsyncMock(return_value=pending_matches)
    )

    result = await ocean_masters_service.create_tournament(
        conn, mode=OceanMastersMode.SINGLE_GAME, games=["cs2"], created_by=1  # type: ignore[arg-type]
    )

    assert isinstance(result, CreateResult)
    assert result.matches_created == 16
    pairings = insert_round_mock.await_args.args[3]
    assert len(pairings) == 16
    # Every pairing's two seeds sum to 33 (the #i v #(33-i) convention).
    assert all(a + b == 33 for a, b, _, _ in pairings)
