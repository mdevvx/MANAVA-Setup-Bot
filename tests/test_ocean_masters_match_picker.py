"""Picking a match from Discord: /oceanmasters match commands offer a
match_id dropdown (pending matches for set-result/override, decided ones for
correct-result), and also accept the short code /oceanmasters bracket shows."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch
from uuid import UUID, uuid4

import pytest

from src.cogs import ocean_masters as cog
from src.errors import BotUserError
from src.models.ocean_masters import MatchStatus, OceanMastersMatch


def _match(
    *,
    round_: int = 1,
    seed_a: int = 1,
    seed_b: int = 2,
    a: str | None = "Alpha",
    b: str | None = "Bravo",
    status: MatchStatus = MatchStatus.PENDING,
) -> OceanMastersMatch:
    return OceanMastersMatch(
        id=uuid4(),
        tournament_id=uuid4(),
        round=round_,
        seed_a=seed_a,
        seed_b=seed_b,
        squad_a_id=uuid4() if a else None,
        squad_b_id=uuid4() if b else None,
        squad_a_name=a,
        squad_b_name=b,
        per_discipline_results={},
        winner_squad_id=None,
        status=status,
        decided_by=None,
        decided_at=None,
        decided_reason=None,
    )


def test_pending_choices_carry_full_match_id_and_readable_label() -> None:
    m = _match()
    [choice] = cog.match_choices([m], "", decided=False)
    assert choice.value == str(m.id)
    assert choice.name.startswith("R1 · #1 Alpha v #2 Bravo")
    assert cog.match_short_code(m) in choice.name


def test_pending_and_decided_lists_are_separate() -> None:
    pending = _match()
    done = _match(seed_a=3, seed_b=4, status=MatchStatus.COMPLETED)
    done = OceanMastersMatch(**{**_as_dict(done), "winner_squad_id": done.squad_a_id})
    assert [c.value for c in cog.match_choices([pending, done], "", decided=False)] == [str(pending.id)]
    assert [c.value for c in cog.match_choices([pending, done], "", decided=True)] == [str(done.id)]


def test_byes_are_never_offered() -> None:
    bye = _match(b=None, status=MatchStatus.COMPLETED)
    assert [c.value for c in cog.match_choices([bye], "", decided=True)] == [cog._NO_MATCH]


def test_correct_result_only_offers_matches_still_correctable() -> None:
    r1_done = _match(status=MatchStatus.COMPLETED)
    r1_done = OceanMastersMatch(**{**_as_dict(r1_done), "winner_squad_id": r1_done.squad_a_id})
    # Next match not played yet: still correctable.
    r2_pending = _match(round_=2)
    r2_pending = OceanMastersMatch(**{**_as_dict(r2_pending), "squad_a_id": r1_done.winner_squad_id})
    assert [c.value for c in cog.match_choices([r1_done, r2_pending], "", decided=True)] == [str(r1_done.id)]
    # Next match already played: not correctable any more.
    r2_played = OceanMastersMatch(
        **{**_as_dict(r2_pending), "status": MatchStatus.COMPLETED, "winner_squad_id": r1_done.winner_squad_id}
    )
    # (the played round-2 match is the final here, so that one is offered instead)
    assert [c.value for c in cog.match_choices([r1_done, r2_played], "", decided=True)] == [str(r2_played.id)]
    # A decided final is correctable even after the tournament completed.
    assert [c.value for c in cog.match_choices([r1_done], "", decided=True)] == [str(r1_done.id)]


def _as_dict(m: OceanMastersMatch) -> dict[str, object]:
    return {f: getattr(m, f) for f in OceanMastersMatch.__slots__}


def test_empty_pending_list_explains_itself() -> None:
    [choice] = cog.match_choices([_match(status=MatchStatus.COMPLETED)], "", decided=False)
    assert choice.value == cog._NO_MATCH and len(choice.name) <= 100


@pytest.mark.asyncio
async def test_placeholder_value_gives_a_friendly_error() -> None:
    with pytest.raises(BotUserError, match="no match to pick"):
        await cog._resolve_match_id(AsyncMock(), cog._NO_MATCH)


def test_typing_filters_by_squad_name_or_code() -> None:
    alpha = _match(a="Alpha", b="Bravo")
    other = _match(a="Charlie", b="Delta", seed_a=3, seed_b=4)
    assert [c.value for c in cog.match_choices([alpha, other], "charl", decided=False)] == [str(other.id)]
    code = cog.match_short_code(alpha)
    assert [c.value for c in cog.match_choices([alpha, other], code, decided=False)] == [str(alpha.id)]


def test_choices_capped_at_discord_limit_and_labels_fit() -> None:
    long_name = "X" * 99
    matches = [_match(a=long_name, b=long_name, seed_a=i, seed_b=65 - i) for i in range(1, 33)]
    choices = cog.match_choices(matches, "", decided=False)
    assert len(choices) == 25
    assert all(len(c.name) <= 100 for c in choices)
    by_id = {str(m.id): m for m in matches}
    assert all(c.name.endswith(f"[{cog.match_short_code(by_id[c.value])}]") for c in choices)


@pytest.mark.asyncio
async def test_resolve_accepts_full_uuid_without_db_lookup() -> None:
    match_id = uuid4()
    assert await cog._resolve_match_id(AsyncMock(), str(match_id)) == match_id


@pytest.mark.asyncio
async def test_resolve_accepts_short_code_from_bracket() -> None:
    match_id = uuid4()
    tournament = AsyncMock(id=uuid4())
    with (
        patch.object(cog, "_current_tournament", AsyncMock(return_value=tournament)),
        patch.object(cog.ocean_masters_repo, "find_match_ids_by_prefix", AsyncMock(return_value=[match_id])) as find,
    ):
        assert await cog._resolve_match_id(AsyncMock(), f"`{match_id.hex[:8].upper()}`") == match_id
    find.assert_awaited_once()
    assert find.await_args.args[2] == match_id.hex[:8]


@pytest.mark.asyncio
async def test_resolve_rejects_ambiguous_or_unknown_codes() -> None:
    tournament = AsyncMock(id=uuid4())
    with patch.object(cog, "_current_tournament", AsyncMock(return_value=tournament)):
        with patch.object(cog.ocean_masters_repo, "find_match_ids_by_prefix", AsyncMock(return_value=[])):
            with pytest.raises(BotUserError, match="No match with code"):
                await cog._resolve_match_id(AsyncMock(), "abcd1234")
        with patch.object(
            cog.ocean_masters_repo, "find_match_ids_by_prefix", AsyncMock(return_value=[uuid4(), uuid4()])
        ):
            with pytest.raises(BotUserError, match="more than one"):
                await cog._resolve_match_id(AsyncMock(), "abcd")
    with pytest.raises(BotUserError, match="dropdown"):
        await cog._resolve_match_id(AsyncMock(), "not-a-match")


def test_long_bracket_is_split_under_discord_message_limit() -> None:
    lines = ["**Ocean Masters**"] + [f"`{UUID(int=i).hex[:8]}` #{i} " + "Y" * 80 for i in range(40)]
    chunks = cog.chunk_lines(lines)
    assert len(chunks) > 1
    assert all(len(c) <= 2000 for c in chunks)
    assert "\n".join(chunks).count("#") == 40
