"""Pre/post-publish Top-32 qualification-list mutations: withdraw and
disqualify. Reading the list (`/season top32 list`) is a plain repo call from
the cog, same as other read-only leaderboard-style displays in this codebase
— only the mutations below carry business rules + audit logging.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence

import asyncpg

from src.db.repositories import audit_logs as audit_repo
from src.db.repositories import season_qualifications as season_qualifications_repo
from src.db.repositories import seasons as seasons_repo
from src.errors import SeasonStateError
from src.models.season import QualificationEntry, QualificationEntryStatus, Season, SeasonPhase, SeedPairing

logger = logging.getLogger(__name__)


def generate_seed_pairings(entries: Sequence[QualificationEntry]) -> list[SeedPairing]:
    """#1 v #N, #2 v #(N-1), ... #(N/2) v #(N/2+1) — generic over however many
    squads actually got a seed, not hard-coded to 32, so it still pairs
    correctly if fewer than 32 squads qualified this season. Milestone 2's
    bracket engine consumes this same pairing. Unseeded entries (not yet
    published) are ignored."""
    seeded = sorted((e for e in entries if e.seed is not None), key=lambda e: e.seed or 0)
    total = len(seeded)
    pairings: list[SeedPairing] = []
    for i in range(total // 2):
        top_entry = seeded[i]
        bottom_entry = seeded[total - 1 - i]
        assert top_entry.seed is not None and bottom_entry.seed is not None
        pairings.append(
            SeedPairing(
                seed_a=top_entry.seed,
                seed_b=bottom_entry.seed,
                squad_a_id=top_entry.squad_id,
                squad_b_id=bottom_entry.squad_id,
            )
        )
    return pairings


async def _require_active_locked_season(conn: asyncpg.Connection) -> Season:
    active = await seasons_repo.get_active(conn)
    if active is None or active.phase == SeasonPhase.QUALIFICATION:
        raise SeasonStateError("There's no locked qualification list yet — run /season lock first.")
    return active


async def withdraw(
    conn: asyncpg.Connection, squad_name: str, *, actor_id: int, reason: str | None
) -> QualificationEntry:
    """Pre-publish only, per the client's Q1 answer: withdrawal is a
    staff-confirmed action, never leader-facing. Marking the row `withdrawn`
    is enough — the Top-32 window (a live filter over `status = 'qualified'`)
    automatically pulls in whoever was next in rank, no renumbering."""
    async with conn.transaction():
        active = await _require_active_locked_season(conn)
        if active.phase != SeasonPhase.QUALIFICATION_LOCK:
            raise SeasonStateError(
                "Withdrawal only works before the bracket is published. "
                "Once published, use /season top32 disqualify instead."
            )
        entry = await season_qualifications_repo.set_status(
            conn,
            active.id,
            squad_name,
            new_status=QualificationEntryStatus.WITHDRAWN,
            decided_by=actor_id,
            reason=reason,
        )
        await audit_repo.record(
            conn,
            actor_id=actor_id,
            action="season.top32.withdraw",
            target_type="squad",
            target_id=str(entry.squad_id),
            old_value={"status": "qualified", "rank": entry.rank},
            new_value={"status": "withdrawn"},
            reason=reason,
        )
    logger.info("Squad %s withdrawn from Top-32 by %s", entry.squad_name, actor_id)
    return entry


async def disqualify(
    conn: asyncpg.Connection, squad_name: str, *, actor_id: int, reason: str
) -> QualificationEntry:
    """Works pre- or post-publish. Pre-publish behaves like withdraw (the
    Top-32 window slides automatically); post-publish this is just a flag for
    Milestone 2's staff override suite to read — no bracket exists yet in
    this milestone to react to it."""
    async with conn.transaction():
        active = await _require_active_locked_season(conn)
        entry = await season_qualifications_repo.set_status(
            conn,
            active.id,
            squad_name,
            new_status=QualificationEntryStatus.DISQUALIFIED,
            decided_by=actor_id,
            reason=reason,
        )
        await audit_repo.record(
            conn,
            actor_id=actor_id,
            action="season.top32.disqualify",
            target_type="squad",
            target_id=str(entry.squad_id),
            old_value={"status": "qualified", "rank": entry.rank},
            new_value={"status": "disqualified"},
            reason=reason,
        )
    logger.info("Squad %s disqualified from Top-32 by %s: %s", entry.squad_name, actor_id, reason)
    return entry
