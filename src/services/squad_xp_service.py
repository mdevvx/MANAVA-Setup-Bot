from __future__ import annotations

from uuid import UUID

import asyncpg

from src import constants
from src.db.repositories import level_thresholds as level_thresholds_repo
from src.db.repositories import memberships as memberships_repo
from src.db.repositories import squad_xp as squad_xp_repo
from src.errors import BotUserError


async def get_squad_level(conn: asyncpg.Connection, squad_id: UUID) -> int:
    """Determines a squad's current level from its Lifetime Squad XP against
    the admin-configurable level_thresholds. Level 1 is the floor — every
    squad starts there regardless of thresholds."""
    xp = await squad_xp_repo.get(conn, squad_id)
    thresholds = await level_thresholds_repo.get_all(conn)

    level = constants.MIN_SQUAD_LEVEL
    for candidate_level in range(2, constants.MAX_SQUAD_LEVEL + 1):
        required = thresholds.get(candidate_level)
        if required is not None and xp.lifetime_xp >= required:
            level = candidate_level
        else:
            break
    return level


def get_member_cap(level: int) -> int:
    return constants.SQUAD_LEVEL_MEMBER_CAPS[level]


async def ensure_capacity_for_new_member(conn: asyncpg.Connection, squad_id: UUID) -> None:
    """Raises a friendly error if adding one more member would exceed the
    squad's current level's member cap. Call this before inserting a new
    squad_memberships row (invite, or join-request approval)."""
    level = await get_squad_level(conn, squad_id)
    cap = get_member_cap(level)
    current_count = await memberships_repo.count_active_members(conn, squad_id)
    if current_count >= cap:
        raise BotUserError(
            f"This squad is at its member capacity for Level {level} ({cap} members). "
            "It needs more Lifetime Squad XP to level up before it can add more members."
        )
