"""Unified Personal XP: the single choke point every XP grant — Discord text
activity or MANAVA events alike — goes through. This is what makes it "one
canonical XP system," per the spec, instead of two unsynchronized counters.
"""

from __future__ import annotations

import logging

import asyncpg

from src.db.repositories import memberships as memberships_repo
from src.db.repositories import personal_xp as xp_repo
from src.db.repositories import squad_xp as squad_xp_repo
from src.models.xp import PersonalXp

logger = logging.getLogger(__name__)


async def grant_personal_xp(conn: asyncpg.Connection, discord_user_id: int, amount: int) -> PersonalXp:
    """Grants Personal Lifetime + Season XP together. If the user is currently
    in an active squad, the same amount cascades 1:1 into that squad's
    Lifetime + Season XP and that specific membership's contribution counter.

    XP earned before joining a squad is never backfilled (this function is
    simply never called retroactively), and XP already contributed stays with
    the squad after the member leaves (contributed_xp lives on the membership
    row, not clawed back on leave/remove).
    """
    if amount <= 0:
        raise ValueError("amount must be positive")

    personal = await xp_repo.add_xp(conn, discord_user_id, amount)

    membership = await memberships_repo.get_active_membership(conn, discord_user_id)
    if membership is not None:
        await squad_xp_repo.add_xp(conn, membership.squad_id, amount)
        await memberships_repo.add_contributed_xp(conn, membership.id, amount)
        logger.info(
            "Granted %s XP to user %s (cascaded to squad %s)", amount, discord_user_id, membership.squad_id
        )
    else:
        logger.info("Granted %s XP to user %s (not currently in a squad)", amount, discord_user_id)

    return personal
