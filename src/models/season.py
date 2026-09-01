from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from uuid import UUID


class SeasonStatus(str, Enum):
    ACTIVE = "active"
    ENDED = "ended"


@dataclass(frozen=True, slots=True)
class Season:
    id: UUID
    season_number: int
    status: SeasonStatus
    started_at: datetime
    started_by: int
    ended_at: datetime | None
    ended_by: int | None


@dataclass(frozen=True, slots=True)
class SeasonResetResult:
    """What a Start New Season action changed — surfaced to the admin who ran
    it and written to audit_logs. Lifetime counters are deliberately absent:
    a season reset never touches them."""

    ended_season_number: int | None
    new_season_number: int
    personal_rows_reset: int
    squad_rows_reset: int
