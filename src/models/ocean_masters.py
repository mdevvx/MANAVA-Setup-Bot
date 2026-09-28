from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from uuid import UUID


class OceanMastersMode(str, Enum):
    SINGLE_GAME = "single_game"
    CROSS_GAME = "cross_game"


class OceanMastersStatus(str, Enum):
    DRAFT = "draft"
    LAUNCHED = "launched"
    COMPLETED = "completed"


class MatchStatus(str, Enum):
    """`COMPLETED` covers both a normal decided result and a resolved
    cross-game tie-break. The other four are the staff override outcomes from
    the approved scope (technical loss, no-show, disqualified, forfeit) —
    each one still sets `winner_squad_id` to whoever advances."""

    PENDING = "pending"
    COMPLETED = "completed"
    TECHNICAL_LOSS = "technical_loss"
    NO_SHOW = "no_show"
    DISQUALIFIED = "disqualified"
    FORFEIT = "forfeit"


OVERRIDE_MATCH_STATUSES: tuple[MatchStatus, ...] = (
    MatchStatus.TECHNICAL_LOSS,
    MatchStatus.NO_SHOW,
    MatchStatus.DISQUALIFIED,
    MatchStatus.FORFEIT,
)


@dataclass(frozen=True, slots=True)
class OceanMasters:
    id: UUID
    season_id: UUID
    mode: OceanMastersMode
    games: tuple[str, ...]
    min_squads_required: int | None
    status: OceanMastersStatus
    launched_at: datetime | None
    launched_by: int | None
    completed_at: datetime | None
    winner_squad_id: UUID | None
    created_by: int
    created_at: datetime


@dataclass(frozen=True, slots=True)
class OceanMastersMatch:
    id: UUID
    tournament_id: UUID
    round: int
    seed_a: int
    seed_b: int
    squad_a_id: UUID | None
    squad_b_id: UUID | None
    squad_a_name: str | None
    squad_b_name: str | None
    per_discipline_results: dict[str, str]
    winner_squad_id: UUID | None
    status: MatchStatus
    decided_by: int | None
    decided_at: datetime | None
    decided_reason: str | None


@dataclass(frozen=True, slots=True)
class CreateResult:
    tournament_id: UUID
    matches_created: int


@dataclass(frozen=True, slots=True)
class MatchDecisionResult:
    match: OceanMastersMatch
    round_advanced: bool
    tournament_completed: bool
