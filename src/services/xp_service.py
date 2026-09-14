"""Unified Personal XP: the single choke point every XP grant — Discord text
activity or MANAVA events alike — goes through. This is what makes it "one
canonical XP system," per the spec, instead of two unsynchronized counters.
"""

from __future__ import annotations

import logging

import asyncpg

from src.db.repositories import memberships as memberships_repo
from src.db.repositories import personal_xp as xp_repo
from src.db.repositories import seasons as seasons_repo
from src.db.repositories import squad_xp as squad_xp_repo
from src.models.xp import PersonalXp

logger = logging.getLogger(__name__)


async def grant_personal_xp(conn: asyncpg.Connection, discord_user_id: int, amount: int) -> PersonalXp:
    """Grants Personal Lifetime XP (and, only while a season is active,
    Personal Season XP). If the user is currently in an active squad, the same
    amount cascades 1:1 into that squad's Lifetime XP (+ Season XP, same
    condition) and that specific membership's contribution counter.

    Between End Season and the next Start (New) Season, Season XP is frozen —
    Discord activity and MANAVA events keep raising Lifetime XP, but must not
    move Season XP until a new season opens.

    XP earned before joining a squad is never backfilled (this function is
    simply never called retroactively), and XP already contributed stays with
    the squad after the member leaves (contributed_xp lives on the membership
    row, not clawed back on leave/remove, and is never season-gated — it's a
    per-stint lifetime figure).
    """
    if amount <= 0:
        raise ValueError("amount must be positive")

    season_active = await seasons_repo.get_active(conn) is not None

    personal = await xp_repo.add_xp(conn, discord_user_id, amount, season_active=season_active)

    membership = await memberships_repo.get_active_membership(conn, discord_user_id)
    if membership is not None:
        await squad_xp_repo.add_xp(conn, membership.squad_id, amount, season_active=season_active)
        await memberships_repo.add_contributed_xp(conn, membership.id, amount)
        logger.info(
            "Granted %s XP to user %s (cascaded to squad %s, season_active=%s)",
            amount,
            discord_user_id,
            membership.squad_id,
            season_active,
        )
    else:
        logger.info(
            "Granted %s XP to user %s (not currently in a squad, season_active=%s)",
            amount,
            discord_user_id,
            season_active,
        )

    return personal
