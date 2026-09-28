"""Standard single-elimination bracket seeding: the round-1 pairs must match
Milestone 1's #1v#32...#16v#17 convention, but the MATCH ORDER must place
seed 1 and seed 2 on opposite halves so they can only meet in the final."""

from __future__ import annotations

from src.services.ocean_masters_service import _next_power_of_two, _standard_bracket_seed_order


def test_next_power_of_two() -> None:
    assert _next_power_of_two(1) == 1
    assert _next_power_of_two(2) == 2
    assert _next_power_of_two(20) == 32
    assert _next_power_of_two(32) == 32
    assert _next_power_of_two(33) == 64


def test_bracket_order_produces_same_pairs_as_milestone_1_seeding() -> None:
    order = _standard_bracket_seed_order(32)
    pairs = {frozenset((order[i], order[i + 1])) for i in range(0, 32, 2)}
    expected = {frozenset((i, 33 - i)) for i in range(1, 17)}
    assert pairs == expected


def test_bracket_order_separates_seed_1_and_seed_2() -> None:
    """Seed 1 and seed 2 must be in different round-1 match-pairs AND on
    different halves of the match list, so round-2 pairing can't bring them
    together before the final."""
    order = _standard_bracket_seed_order(32)
    matches = [tuple(order[i : i + 2]) for i in range(0, 32, 2)]
    index_of_1 = next(i for i, m in enumerate(matches) if 1 in m)
    index_of_2 = next(i for i, m in enumerate(matches) if 2 in m)
    half = len(matches) // 2
    assert (index_of_1 < half) != (index_of_2 < half)


def test_bracket_order_small_size() -> None:
    order = _standard_bracket_seed_order(4)
    pairs = {frozenset((order[0], order[1])), frozenset((order[2], order[3]))}
    assert pairs == {frozenset((1, 4)), frozenset((2, 3))}
