from __future__ import annotations

from types import SimpleNamespace

import pytest

from src import constants
from src.discord_state.capacity import find_available_category
from src.errors import CapacityExceededError


def _fake_state(num_categories: int) -> SimpleNamespace:
    categories = [SimpleNamespace(id=i, name=f"SQUADS {i:02d}") for i in range(1, num_categories + 1)]
    return SimpleNamespace(squad_categories=tuple(categories))


def test_picks_first_category_with_room() -> None:
    state = _fake_state(3)
    counts = {1: constants.MAX_SQUADS_PER_CATEGORY, 2: 5, 3: 0}
    assert find_available_category(state, counts) == 2  # type: ignore[arg-type]


def test_raises_when_all_categories_full() -> None:
    state = _fake_state(2)
    counts = {1: constants.MAX_SQUADS_PER_CATEGORY, 2: constants.MAX_SQUADS_PER_CATEGORY}
    with pytest.raises(CapacityExceededError):
        find_available_category(state, counts)  # type: ignore[arg-type]


def test_empty_counts_defaults_to_first_category() -> None:
    state = _fake_state(2)
    assert find_available_category(state, {}) == 1  # type: ignore[arg-type]


def test_never_assigns_by_squad_count_beyond_capacity() -> None:
    # A category with more active squads than the cap (shouldn't happen, but
    # if it ever does, it must never be selected as "available").
    state = _fake_state(2)
    counts = {1: constants.MAX_SQUADS_PER_CATEGORY + 5, 2: constants.MAX_SQUADS_PER_CATEGORY - 1}
    assert find_available_category(state, counts) == 2  # type: ignore[arg-type]
