from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass(frozen=True, slots=True)
class PersonalXp:
    discord_user_id: int
    verified_player: bool
    manava_user_id: str | None
    lifetime_xp: int
    season_xp: int


@dataclass(frozen=True, slots=True)
class SquadXp:
    squad_id: UUID
    lifetime_xp: int
    season_xp: int


@dataclass(frozen=True, slots=True)
class ManavaEvent:
    """A validated inbound MANAVA event, ready for processing.

    Field names follow the MANAVA Gateway payload (gateway-diagram-en.html):
    `place` (final tournament ranking) and `won_prize_slot` (landed in a paid
    prize-pool slot). `result` is retained for backward compatibility only —
    the Gateway never sends it.
    """

    event_id: str
    manava_user_id: str
    event_type: str
    game: str
    timestamp: datetime
    match_id: str | None
    tournament_id: str | None
    result: str | None
    place: int | None
    won_prize_slot: bool | None = None


@dataclass(frozen=True, slots=True)
class ManavaEventValidationError:
    reason: str


@dataclass(frozen=True, slots=True)
class ManavaEventOutcome:
    """Result of running one event through the processing pipeline — used for
    both the webhook response and the local test harness's reply."""

    event_id: str
    status: str  # "processed" | "duplicate" | "unresolved_user"
    xp_granted: int
    discord_user_id: int | None


@dataclass(frozen=True, slots=True)
class GlobalLeaderboardEntry:
    rank: int
    squad_id: UUID
    squad_name: str
    season_xp: int
    lifetime_xp: int


@dataclass(frozen=True, slots=True)
class SquadMemberLeaderboardEntry:
    rank: int
    discord_user_id: int
    squad_role: str
    personal_lifetime_xp: int
    personal_season_xp: int
    contributed_xp: int
