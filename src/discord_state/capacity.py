from __future__ import annotations

from src import constants
from src.discord_state.role_resolver import ResolvedGuildState
from src.errors import CapacityExceededError


def find_available_category(state: ResolvedGuildState, active_squad_count_by_category: dict[int, int]) -> int:
    """Pick the first squad category with room under MAX_SQUADS_PER_CATEGORY.

    Assignment is purely by available capacity, in category-name order — never
    by leaderboard rank or any other ranking signal.
    """
    for category in state.squad_categories:
        current = active_squad_count_by_category.get(category.id, 0)
        if current < constants.MAX_SQUADS_PER_CATEGORY:
            return category.id
    raise CapacityExceededError()
