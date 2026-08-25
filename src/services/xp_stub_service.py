"""STUB: Discord-only Personal Lifetime XP accumulator for the Phase 1 Wave 1500 gate.

Replaced by the full Unified Personal XP system (Discord + MANAVA sources) in
Phase 2 — do not build on top of this beyond what Phase 1 needs.
"""

from __future__ import annotations

import asyncpg

from src.db.repositories import personal_xp as xp_repo

STUB_XP_PER_MESSAGE = 1


async def record_message_activity(conn: asyncpg.Connection, discord_user_id: int) -> None:
    await xp_repo.add_lifetime_xp(conn, discord_user_id, STUB_XP_PER_MESSAGE)
