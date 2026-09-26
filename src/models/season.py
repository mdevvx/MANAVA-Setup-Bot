from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from uuid import UUID


class SeasonStatus(str, Enum):
    ACTIVE = "active"
    ENDED = "ended"


class SeasonPhase(str, Enum):
    """Where an ACTIVE season sits in the Release 3 lifecycle. Independent of
    `SeasonStatus` — a season can be 'active' status in any of the first
    three phases; 'ended' status pairs with either QUALIFICATION (closed
    early via /season end, no history snapshot) or SEASON_COMPLETE (closed
    properly via /season complete, history snapshot taken)."""

    QUALIFICATION = "qualification"
    QUALIFICATION_LOCK = "qualification_lock"
    TOP32_PLAYOFFS = "top32_playoffs"
    SEASON_COMPLETE = "season_complete"


class QualificationEntryStatus(str, Enum):
    QUALIFIED = "qualified"
    WITHDRAWN = "withdrawn"
    DISQUALIFIED = "disqualified"


@dataclass(frozen=True, slots=True)
class Season:
    id: UUID
    season_number: int
    status: SeasonStatus
    started_at: datetime
    started_by: int
    ended_at: datetime | None
    ended_by: int | None
    phase: SeasonPhase = SeasonPhase.QUALIFICATION
    locked_at: datetime | None = None
    locked_by: int | None = None
    published_at: datetime | None = None
    published_by: int | None = None


@dataclass(frozen=True, slots=True)
class SeasonResetResult:
    """What a Start New Season action changed — surfaced to the admin who ran
    it and written to audit_logs. Lifetime counters are deliberately absent:
    a season reset never touches them."""

    ended_season_number: int | None
    new_season_number: int
    personal_rows_reset: int
    squad_rows_reset: int


@dataclass(frozen=True, slots=True)
class QualificationEntry:
    """One squad's row in the Qualification Lock snapshot. `rank` covers every
    active squad at Lock time, not just the top 32 — the current Top-32 is a
    live filter over `status = 'qualified'` rows, not a fixed list, which is
    what makes pre-publish replacement automatic."""

    season_id: UUID
    squad_id: UUID
    squad_name: str
    rank: int
    season_xp_snapshot: int
    lifetime_xp_snapshot: int
    status: QualificationEntryStatus
    seed: int | None
    decided_by: int | None
    decided_at: datetime | None
    decided_reason: str | None


@dataclass(frozen=True, slots=True)
class LockResult:
    season_id: UUID
    season_number: int
    squads_ranked: int


@dataclass(frozen=True, slots=True)
class PublishResult:
    season_id: UUID
    season_number: int
    seeds_assigned: int


@dataclass(frozen=True, slots=True)
class SeasonHistoryEntry:
    season_id: UUID
    squad_id: UUID
    squad_name: str
    final_rank: int
    final_season_xp: int
    lifetime_xp_at_completion: int
    qualified_top32: bool
    ocean_masters_final_standing: str | None = None


@dataclass(frozen=True, slots=True)
class CompleteResult:
    season_id: UUID
    season_number: int
    squads_recorded: int


@dataclass(frozen=True, slots=True)
class SeedPairing:
    """One bracket matchup generated from the published seed list. Computed
    generically off however many squads actually seeded (`total`), not
    hard-coded to 32, so it still pairs correctly if fewer than 32 squads
    qualified this season — Milestone 2's bracket engine consumes this."""

    seed_a: int
    seed_b: int
    squad_a_id: UUID
    squad_b_id: UUID
