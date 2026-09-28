"""Match decisions: set-result and the staff override suite both advance the
round when it's fully decided, complete the tournament on the final, and a
bye (uneven bracket) advances automatically without staff action."""

from __future__ import annotations

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from datetime import datetime, timezone

from src.errors import OceanMastersStateError
from src.models.ocean_masters import MatchStatus, OceanMastersMatch, OceanMastersMode, OceanMastersStatus
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
    round_: int = 1,
    seed_a: int = 1,
    seed_b: int = 2,
    squad_a_id: object | None = None,
    squad_b_id: object | None = None,
    winner_squad_id: object | None = None,
    status: MatchStatus = MatchStatus.PENDING,
    per_discipline_results: dict[str, str] | None = None,
) -> OceanMastersMatch:
    return OceanMastersMatch(
        id=uuid4(),
        tournament_id=tournament_id,  # type: ignore[arg-type]
        round=round_,
        seed_a=seed_a,
        seed_b=seed_b,
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


@pytest.mark.asyncio
async def test_set_result_rejects_squad_not_in_match(monkeypatch: pytest.MonkeyPatch) -> None:
    conn = _FakeConn()
    tid = uuid4()
    a, b = uuid4(), uuid4()
    match = _match(tournament_id=tid, squad_a_id=a, squad_b_id=b)
    monkeypatch.setattr(ocean_masters_service.ocean_masters_repo, "get_match", AsyncMock(return_value=match))
    decide_mock = AsyncMock()
    monkeypatch.setattr(ocean_masters_service.ocean_masters_repo, "decide_match", decide_mock)

    with pytest.raises(OceanMastersStateError):
        await ocean_masters_service.set_result(
            conn, match.id, winner_squad_id=uuid4(), actor_id=1, reason=None, channels=None  # type: ignore[arg-type]
        )
    decide_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_set_result_rejects_already_decided_match(monkeypatch: pytest.MonkeyPatch) -> None:
    conn = _FakeConn()
    tid = uuid4()
    a, b = uuid4(), uuid4()
    match = _match(tournament_id=tid, squad_a_id=a, squad_b_id=b, winner_squad_id=a, status=MatchStatus.COMPLETED)
    monkeypatch.setattr(ocean_masters_service.ocean_masters_repo, "get_match", AsyncMock(return_value=match))

    with pytest.raises(OceanMastersStateError):
        await ocean_masters_service.set_result(
            conn, match.id, winner_squad_id=a, actor_id=1, reason=None, channels=None  # type: ignore[arg-type]
        )


@pytest.mark.asyncio
async def test_round_does_not_advance_until_every_match_decided(monkeypatch: pytest.MonkeyPatch) -> None:
    conn = _FakeConn()
    tid = uuid4()
    a, b = uuid4(), uuid4()
    match = _match(tournament_id=tid, squad_a_id=a, squad_b_id=b)
    monkeypatch.setattr(ocean_masters_service.ocean_masters_repo, "get_match", AsyncMock(return_value=match))
    decided = _match(tournament_id=tid, squad_a_id=a, squad_b_id=b, winner_squad_id=a, status=MatchStatus.COMPLETED)
    monkeypatch.setattr(ocean_masters_service.ocean_masters_repo, "decide_match", AsyncMock(return_value=decided))
    # Sibling match in the same round is still pending.
    sibling = _match(tournament_id=tid, seed_a=3, seed_b=4)
    monkeypatch.setattr(
        ocean_masters_service.ocean_masters_repo, "get_round_matches", AsyncMock(return_value=[decided, sibling])
    )
    insert_round_mock = AsyncMock()
    monkeypatch.setattr(ocean_masters_service.ocean_masters_repo, "insert_round", insert_round_mock)
    monkeypatch.setattr(ocean_masters_service.audit_repo, "record", AsyncMock())

    result = await ocean_masters_service.set_result(
        conn, match.id, winner_squad_id=a, actor_id=1, reason=None, channels=None  # type: ignore[arg-type]
    )

    assert result.round_advanced is False
    assert result.tournament_completed is False
    insert_round_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_final_match_decided_completes_tournament(monkeypatch: pytest.MonkeyPatch) -> None:
    conn = _FakeConn()
    tid = uuid4()
    a, b = uuid4(), uuid4()
    match = _match(tournament_id=tid, squad_a_id=a, squad_b_id=b)
    monkeypatch.setattr(ocean_masters_service.ocean_masters_repo, "get_match", AsyncMock(return_value=match))
    decided = _match(tournament_id=tid, squad_a_id=a, squad_b_id=b, winner_squad_id=a, status=MatchStatus.COMPLETED)
    monkeypatch.setattr(ocean_masters_service.ocean_masters_repo, "decide_match", AsyncMock(return_value=decided))
    # Only one match in the round = the final.
    monkeypatch.setattr(
        ocean_masters_service.ocean_masters_repo, "get_round_matches", AsyncMock(return_value=[decided])
    )
    mark_completed_mock = AsyncMock()
    monkeypatch.setattr(ocean_masters_service.ocean_masters_repo, "mark_completed", mark_completed_mock)
    monkeypatch.setattr(ocean_masters_service.audit_repo, "record", AsyncMock())

    result = await ocean_masters_service.set_result(
        conn, match.id, winner_squad_id=a, actor_id=1, reason=None, channels=None  # type: ignore[arg-type]
    )

    assert result.tournament_completed is True
    assert result.round_advanced is False
    mark_completed_mock.assert_awaited_once_with(conn, tid, winner_squad_id=a)


@pytest.mark.asyncio
async def test_full_round_generates_next_round_pairings_by_bracket_adjacency(monkeypatch: pytest.MonkeyPatch) -> None:
    """Match 1's winner must pair with match 2's winner (not match 3's) —
    sequential adjacency in seed_a order, which is bracket-correct because
    round-1 matches are created in standard bracket order."""
    conn = _FakeConn()
    tid = uuid4()
    w1, w2, w3, w4 = uuid4(), uuid4(), uuid4(), uuid4()
    m1_a = uuid4()
    m1_pending = _match(tournament_id=tid, seed_a=1, seed_b=32, squad_a_id=w1, squad_b_id=m1_a)
    m1 = _match(tournament_id=tid, seed_a=1, seed_b=32, squad_a_id=w1, squad_b_id=m1_a, winner_squad_id=w1, status=MatchStatus.COMPLETED)
    m2 = _match(tournament_id=tid, seed_a=16, seed_b=17, squad_a_id=uuid4(), squad_b_id=w2, winner_squad_id=w2, status=MatchStatus.COMPLETED)
    m3 = _match(tournament_id=tid, seed_a=8, seed_b=25, squad_a_id=w3, squad_b_id=uuid4(), winner_squad_id=w3, status=MatchStatus.COMPLETED)
    m4 = _match(tournament_id=tid, seed_a=9, seed_b=24, squad_a_id=uuid4(), squad_b_id=w4, winner_squad_id=w4, status=MatchStatus.COMPLETED)
    monkeypatch.setattr(ocean_masters_service.ocean_masters_repo, "get_match", AsyncMock(return_value=m1_pending))
    monkeypatch.setattr(ocean_masters_service.ocean_masters_repo, "decide_match", AsyncMock(return_value=m1))

    async def _get_round_matches(conn: object, tournament_id: object, round_number: int) -> list[OceanMastersMatch]:
        if round_number == 1:
            return [m1, m2, m3, m4]
        # Round 2 was just created by this call — still pending, so
        # _try_advance_round for round 2 stops here instead of recursing.
        return [_match(tournament_id=tid, seed_a=1, seed_b=16)]

    monkeypatch.setattr(
        ocean_masters_service.ocean_masters_repo, "get_round_matches", AsyncMock(side_effect=_get_round_matches)
    )
    insert_round_mock = AsyncMock()
    monkeypatch.setattr(ocean_masters_service.ocean_masters_repo, "insert_round", insert_round_mock)
    monkeypatch.setattr(ocean_masters_service.audit_repo, "record", AsyncMock())

    result = await ocean_masters_service.set_result(
        conn, m1_pending.id, winner_squad_id=w1, actor_id=1, reason=None, channels=None  # type: ignore[arg-type]
    )

    assert result.round_advanced is True
    insert_round_mock.assert_awaited_once()
    pairings = insert_round_mock.await_args.args[3]
    # w1 sits on seed_a=1 (match 1's "a" side); w2 sits on seed_b=17 (match
    # 2's "b" side) — the winner's carried-forward seed is whichever side of
    # its own match it actually won from.
    assert pairings == [(1, 17, w1, w2), (8, 24, w3, w4)]


@pytest.mark.asyncio
async def test_override_requires_reason_to_advance_winner(monkeypatch: pytest.MonkeyPatch) -> None:
    conn = _FakeConn()
    tid = uuid4()
    a, b = uuid4(), uuid4()
    match = _match(tournament_id=tid, squad_a_id=a, squad_b_id=b)
    monkeypatch.setattr(ocean_masters_service.ocean_masters_repo, "get_match", AsyncMock(return_value=match))
    decided = _match(tournament_id=tid, squad_a_id=a, squad_b_id=b, winner_squad_id=b, status=MatchStatus.NO_SHOW)
    monkeypatch.setattr(ocean_masters_service.ocean_masters_repo, "decide_match", AsyncMock(return_value=decided))
    monkeypatch.setattr(
        ocean_masters_service.ocean_masters_repo, "get_round_matches", AsyncMock(return_value=[decided])
    )
    monkeypatch.setattr(ocean_masters_service.ocean_masters_repo, "mark_completed", AsyncMock())
    audit_mock = AsyncMock()
    monkeypatch.setattr(ocean_masters_service.audit_repo, "record", audit_mock)

    result = await ocean_masters_service.override_match(
        conn,
        match.id,  # type: ignore[arg-type]
        outcome=MatchStatus.NO_SHOW,
        winner_squad_id=b,
        actor_id=9,
        reason="Squad A never showed up",
        channels=None,
    )

    assert result.match.status is MatchStatus.NO_SHOW
    _, kwargs = audit_mock.await_args
    assert kwargs["new_value"]["status"] == "no_show"
    assert kwargs["reason"] == "Squad A never showed up"


@pytest.mark.asyncio
async def test_override_rejects_invalid_outcome(monkeypatch: pytest.MonkeyPatch) -> None:
    conn = _FakeConn()
    with pytest.raises(OceanMastersStateError):
        await ocean_masters_service.override_match(
            conn,
            uuid4(),  # type: ignore[arg-type]
            outcome=MatchStatus.COMPLETED,  # not an override outcome
            winner_squad_id=uuid4(),  # type: ignore[arg-type]
            actor_id=9,
            reason="x",
            channels=None,
        )


@pytest.mark.asyncio
async def test_bye_advances_automatically_with_no_staff_action(monkeypatch: pytest.MonkeyPatch) -> None:
    conn = _FakeConn()
    tid = uuid4()
    real_squad = uuid4()
    bye_match = _match(tournament_id=tid, squad_a_id=real_squad, squad_b_id=None)
    monkeypatch.setattr(
        ocean_masters_service.ocean_masters_repo, "get_round_matches", AsyncMock(return_value=[bye_match])
    )
    decide_mock = AsyncMock(
        return_value=_match(
            tournament_id=tid, squad_a_id=real_squad, squad_b_id=None, winner_squad_id=real_squad, status=MatchStatus.COMPLETED
        )
    )
    monkeypatch.setattr(ocean_masters_service.ocean_masters_repo, "decide_match", decide_mock)
    monkeypatch.setattr(ocean_masters_service.ocean_masters_repo, "mark_completed", AsyncMock())

    await ocean_masters_service._resolve_byes_and_cascade(conn, tid, 1, channels=None)  # type: ignore[arg-type]

    decide_mock.assert_awaited_once()
    _, kwargs = decide_mock.await_args
    assert kwargs["winner_squad_id"] == real_squad
    assert kwargs["decided_by"] == ocean_masters_service._SYSTEM_ACTOR_ID


def _tournament(*, status: OceanMastersStatus = OceanMastersStatus.LAUNCHED) -> object:
    from src.models.ocean_masters import OceanMasters

    return OceanMasters(
        id=uuid4(),
        season_id=uuid4(),
        mode=OceanMastersMode.SINGLE_GAME,
        games=("cs2",),
        min_squads_required=None,
        status=status,
        launched_at=None,
        launched_by=None,
        completed_at=None,
        winner_squad_id=None,
        created_by=1,
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )


@pytest.mark.asyncio
async def test_correct_result_rejects_pending_match(monkeypatch: pytest.MonkeyPatch) -> None:
    conn = _FakeConn()
    tid = uuid4()
    a, b = uuid4(), uuid4()
    match = _match(tournament_id=tid, squad_a_id=a, squad_b_id=b)
    monkeypatch.setattr(ocean_masters_service.ocean_masters_repo, "get_match", AsyncMock(return_value=match))

    with pytest.raises(OceanMastersStateError):
        await ocean_masters_service.correct_result(
            conn, match.id, winner_squad_id=a, actor_id=9, reason="oops", channels=None  # type: ignore[arg-type]
        )


@pytest.mark.asyncio
async def test_correct_result_blocked_once_next_round_exists(monkeypatch: pytest.MonkeyPatch) -> None:
    conn = _FakeConn()
    tid = uuid4()
    a, b = uuid4(), uuid4()
    decided = _match(tournament_id=tid, squad_a_id=a, squad_b_id=b, winner_squad_id=a, status=MatchStatus.COMPLETED)
    monkeypatch.setattr(ocean_masters_service.ocean_masters_repo, "get_match", AsyncMock(return_value=decided))
    monkeypatch.setattr(
        ocean_masters_service.ocean_masters_repo, "get_by_id", AsyncMock(return_value=_tournament())
    )
    # Round 2 already exists — built off this match's (now-wrong) winner.
    monkeypatch.setattr(
        ocean_masters_service.ocean_masters_repo,
        "get_round_matches",
        AsyncMock(return_value=[_match(tournament_id=tid, squad_a_id=a, squad_b_id=uuid4())]),
    )
    correct_mock = AsyncMock()
    monkeypatch.setattr(ocean_masters_service.ocean_masters_repo, "correct_match", correct_mock)

    with pytest.raises(OceanMastersStateError):
        await ocean_masters_service.correct_result(
            conn, decided.id, winner_squad_id=b, actor_id=9, reason="wrong side recorded", channels=None  # type: ignore[arg-type]
        )
    correct_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_correct_result_blocked_once_tournament_completed(monkeypatch: pytest.MonkeyPatch) -> None:
    conn = _FakeConn()
    tid = uuid4()
    a, b = uuid4(), uuid4()
    decided = _match(tournament_id=tid, squad_a_id=a, squad_b_id=b, winner_squad_id=a, status=MatchStatus.COMPLETED)
    monkeypatch.setattr(ocean_masters_service.ocean_masters_repo, "get_match", AsyncMock(return_value=decided))
    monkeypatch.setattr(
        ocean_masters_service.ocean_masters_repo,
        "get_by_id",
        AsyncMock(return_value=_tournament(status=OceanMastersStatus.COMPLETED)),
    )
    correct_mock = AsyncMock()
    monkeypatch.setattr(ocean_masters_service.ocean_masters_repo, "correct_match", correct_mock)

    with pytest.raises(OceanMastersStateError):
        await ocean_masters_service.correct_result(
            conn, decided.id, winner_squad_id=b, actor_id=9, reason="wrong champion", channels=None  # type: ignore[arg-type]
        )
    correct_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_correct_result_allowed_before_round_advances(monkeypatch: pytest.MonkeyPatch) -> None:
    conn = _FakeConn()
    tid = uuid4()
    a, b = uuid4(), uuid4()
    decided = _match(tournament_id=tid, squad_a_id=a, squad_b_id=b, winner_squad_id=a, status=MatchStatus.COMPLETED)
    monkeypatch.setattr(ocean_masters_service.ocean_masters_repo, "get_match", AsyncMock(return_value=decided))
    monkeypatch.setattr(
        ocean_masters_service.ocean_masters_repo, "get_by_id", AsyncMock(return_value=_tournament())
    )
    corrected = _match(tournament_id=tid, squad_a_id=a, squad_b_id=b, winner_squad_id=b, status=MatchStatus.COMPLETED)
    correct_mock = AsyncMock(return_value=corrected)
    monkeypatch.setattr(ocean_masters_service.ocean_masters_repo, "correct_match", correct_mock)
    audit_mock = AsyncMock()
    monkeypatch.setattr(ocean_masters_service.audit_repo, "record", audit_mock)

    # First call (the pre-check for "did the round already advance") returns
    # empty — no round 2 yet. Second call (inside _try_advance_round, same
    # round number) returns the sibling still pending, so nothing cascades.
    sibling = _match(tournament_id=tid, seed_a=3, seed_b=4)
    call_count = {"n": 0}

    async def _get_round_matches(conn: object, tournament_id: object, round_number: int) -> list[OceanMastersMatch]:
        call_count["n"] += 1
        if call_count["n"] == 1:
            return []  # round+1 check: doesn't exist yet
        return [corrected, sibling]  # _try_advance_round's look at round 1 itself

    monkeypatch.setattr(
        ocean_masters_service.ocean_masters_repo, "get_round_matches", AsyncMock(side_effect=_get_round_matches)
    )

    result = await ocean_masters_service.correct_result(
        conn, decided.id, winner_squad_id=b, actor_id=9, reason="scorekeeping error", channels=None  # type: ignore[arg-type]
    )

    assert result.match.winner_squad_id == b
    correct_mock.assert_awaited_once()
    _, kwargs = audit_mock.await_args
    assert kwargs["action"] == "oceanmasters.match.correct_result"
    assert kwargs["old_value"]["winner_squad_id"] == str(a)
    assert kwargs["new_value"]["winner_squad_id"] == str(b)
