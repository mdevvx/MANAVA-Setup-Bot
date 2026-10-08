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
async def test_full_round_generates_next_round_pairings_by_bracket_position(monkeypatch: pytest.MonkeyPatch) -> None:
    """8-squad bracket, round 1 = 1v8, 4v5, 2v7, 3v6 in bracket order. The
    repo returns a round sorted by seed_a (1v8, 2v7, 3v6, 4v5); pairing in
    that order would put seed 1 against seed 2 in the semi-final. Round 2
    must instead be 1v4 and 2v3, so seeds 1 and 2 can only meet in the final."""
    conn = _FakeConn()
    tid = uuid4()
    squads = {seed: uuid4() for seed in range(1, 9)}

    def _r1(seed_a: int, seed_b: int, status: MatchStatus = MatchStatus.COMPLETED) -> OceanMastersMatch:
        return _match(
            tournament_id=tid,
            seed_a=seed_a,
            seed_b=seed_b,
            squad_a_id=squads[seed_a],
            squad_b_id=squads[seed_b],
            winner_squad_id=squads[seed_a] if status is MatchStatus.COMPLETED else None,
            status=status,
        )

    last_pending = _r1(4, 5, MatchStatus.PENDING)
    round_1_by_seed = [_r1(1, 8), _r1(2, 7), _r1(3, 6), _r1(4, 5)]  # repo order: by seed_a
    monkeypatch.setattr(ocean_masters_service.ocean_masters_repo, "get_match", AsyncMock(return_value=last_pending))
    monkeypatch.setattr(ocean_masters_service.ocean_masters_repo, "decide_match", AsyncMock(return_value=round_1_by_seed[3]))

    async def _get_round_matches(conn: object, tournament_id: object, round_number: int) -> list[OceanMastersMatch]:
        if round_number == 1:
            return round_1_by_seed
        # Round 2 was just created by this call — still pending, so it stops here.
        return [_match(tournament_id=tid, seed_a=1, seed_b=4), _match(tournament_id=tid, seed_a=2, seed_b=3)]

    monkeypatch.setattr(
        ocean_masters_service.ocean_masters_repo, "get_round_matches", AsyncMock(side_effect=_get_round_matches)
    )
    insert_round_mock = AsyncMock()
    monkeypatch.setattr(ocean_masters_service.ocean_masters_repo, "insert_round", insert_round_mock)
    monkeypatch.setattr(ocean_masters_service.audit_repo, "record", AsyncMock())

    result = await ocean_masters_service.set_result(
        conn, last_pending.id, winner_squad_id=squads[4], actor_id=1, reason=None, channels=None  # type: ignore[arg-type]
    )

    assert result.round_advanced is True
    pairings = insert_round_mock.await_args.args[3]
    assert pairings == [(1, 4, squads[1], squads[4]), (2, 3, squads[2], squads[3])]


def test_bracket_order_holds_in_later_rounds_whichever_side_won() -> None:
    """Round 2 of a 16-squad bracket: a match's position comes from the block
    of seeds it was drawn from, so an upset winner (seed 16 knocking out
    seed 1) still keeps the match at the top of the bracket."""
    tid = uuid4()
    r2 = [
        _match(tournament_id=tid, round_=2, seed_a=s_a, seed_b=s_b)
        for s_a, s_b in [(2, 7), (4, 5), (3, 6), (16, 9)]  # shuffled; 16 beat 1, 9 beat 8
    ]
    ordered = ocean_masters_service.in_bracket_order(r2, 2)
    assert [(m.seed_a, m.seed_b) for m in ordered] == [(16, 9), (4, 5), (2, 7), (3, 6)]


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
async def test_correct_result_moves_new_winner_into_unplayed_next_match(monkeypatch: pytest.MonkeyPatch) -> None:
    conn = _FakeConn()
    tid = uuid4()
    a, b, other = uuid4(), uuid4(), uuid4()
    decided = _match(
        tournament_id=tid, seed_a=1, seed_b=8, squad_a_id=a, squad_b_id=b, winner_squad_id=a, status=MatchStatus.COMPLETED
    )
    next_match = _match(tournament_id=tid, round_=2, seed_a=1, seed_b=4, squad_a_id=a, squad_b_id=other)
    corrected = _match(
        tournament_id=tid, seed_a=1, seed_b=8, squad_a_id=a, squad_b_id=b, winner_squad_id=b, status=MatchStatus.COMPLETED
    )
    monkeypatch.setattr(ocean_masters_service.ocean_masters_repo, "get_match", AsyncMock(return_value=decided))
    monkeypatch.setattr(ocean_masters_service.ocean_masters_repo, "get_by_id", AsyncMock(return_value=_tournament()))
    monkeypatch.setattr(
        ocean_masters_service.ocean_masters_repo, "get_round_matches", AsyncMock(return_value=[next_match])
    )
    monkeypatch.setattr(ocean_masters_service.ocean_masters_repo, "correct_match", AsyncMock(return_value=corrected))
    replace_mock = AsyncMock(return_value=next_match)
    monkeypatch.setattr(ocean_masters_service.ocean_masters_repo, "replace_match_squad", replace_mock)
    champion_mock = AsyncMock()
    monkeypatch.setattr(ocean_masters_service.ocean_masters_repo, "set_champion", champion_mock)
    monkeypatch.setattr(ocean_masters_service.audit_repo, "record", AsyncMock())

    result = await ocean_masters_service.correct_result(
        conn, decided.id, winner_squad_id=b, actor_id=9, reason="wrong side recorded", channels=None  # type: ignore[arg-type]
    )

    replace_mock.assert_awaited_once_with(conn, next_match.id, old_squad_id=a, new_squad_id=b, new_seed=8)
    champion_mock.assert_not_awaited()
    assert result.next_match is next_match
    assert result.champion_changed is False


@pytest.mark.asyncio
async def test_correct_result_blocked_once_next_match_played(monkeypatch: pytest.MonkeyPatch) -> None:
    conn = _FakeConn()
    tid = uuid4()
    a, b, other = uuid4(), uuid4(), uuid4()
    decided = _match(tournament_id=tid, squad_a_id=a, squad_b_id=b, winner_squad_id=a, status=MatchStatus.COMPLETED)
    played = _match(
        tournament_id=tid, round_=2, squad_a_id=a, squad_b_id=other, winner_squad_id=a, status=MatchStatus.COMPLETED
    )
    monkeypatch.setattr(ocean_masters_service.ocean_masters_repo, "get_match", AsyncMock(return_value=decided))
    monkeypatch.setattr(ocean_masters_service.ocean_masters_repo, "get_round_matches", AsyncMock(return_value=[played]))
    correct_mock = AsyncMock()
    monkeypatch.setattr(ocean_masters_service.ocean_masters_repo, "correct_match", correct_mock)

    with pytest.raises(OceanMastersStateError, match="already has a result"):
        await ocean_masters_service.correct_result(
            conn, decided.id, winner_squad_id=b, actor_id=9, reason="wrong side recorded", channels=None  # type: ignore[arg-type]
        )
    correct_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_correct_result_blocked_once_cross_game_next_match_started(monkeypatch: pytest.MonkeyPatch) -> None:
    conn = _FakeConn()
    tid = uuid4()
    a, b, other = uuid4(), uuid4(), uuid4()
    decided = _match(tournament_id=tid, squad_a_id=a, squad_b_id=b, winner_squad_id=a, status=MatchStatus.COMPLETED)
    started = _match(tournament_id=tid, round_=2, squad_a_id=a, squad_b_id=other, per_discipline_results={"cs2": str(a)})
    monkeypatch.setattr(ocean_masters_service.ocean_masters_repo, "get_match", AsyncMock(return_value=decided))
    monkeypatch.setattr(ocean_masters_service.ocean_masters_repo, "get_round_matches", AsyncMock(return_value=[started]))

    with pytest.raises(OceanMastersStateError, match="Discipline results"):
        await ocean_masters_service.correct_result(
            conn, decided.id, winner_squad_id=b, actor_id=9, reason="wrong side", channels=None  # type: ignore[arg-type]
        )


@pytest.mark.asyncio
async def test_correct_result_on_completed_final_swaps_champion(monkeypatch: pytest.MonkeyPatch) -> None:
    conn = _FakeConn()
    tid = uuid4()
    a, b = uuid4(), uuid4()
    final = _match(tournament_id=tid, squad_a_id=a, squad_b_id=b, winner_squad_id=a, status=MatchStatus.COMPLETED)
    corrected = _match(tournament_id=tid, squad_a_id=a, squad_b_id=b, winner_squad_id=b, status=MatchStatus.COMPLETED)
    tournament = _tournament(status=OceanMastersStatus.COMPLETED)
    monkeypatch.setattr(ocean_masters_service.ocean_masters_repo, "get_match", AsyncMock(return_value=final))
    monkeypatch.setattr(ocean_masters_service.ocean_masters_repo, "get_by_id", AsyncMock(return_value=tournament))
    monkeypatch.setattr(ocean_masters_service.ocean_masters_repo, "get_round_matches", AsyncMock(return_value=[]))
    monkeypatch.setattr(ocean_masters_service.ocean_masters_repo, "correct_match", AsyncMock(return_value=corrected))
    champion_mock = AsyncMock()
    monkeypatch.setattr(ocean_masters_service.ocean_masters_repo, "set_champion", champion_mock)
    standings_mock = AsyncMock()
    monkeypatch.setattr(ocean_masters_service.season_history_repo, "refresh_ocean_masters_standings", standings_mock)
    monkeypatch.setattr(ocean_masters_service.audit_repo, "record", AsyncMock())

    result = await ocean_masters_service.correct_result(
        conn, final.id, winner_squad_id=b, actor_id=9, reason="wrong champion", channels=None  # type: ignore[arg-type]
    )

    champion_mock.assert_awaited_once_with(conn, tournament.id, winner_squad_id=b)
    standings_mock.assert_awaited_once_with(conn, tournament.season_id)
    assert result.champion_changed is True


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

    # The only lookup is the next round: it doesn't exist yet, so the
    # correction just rewrites this match.
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
