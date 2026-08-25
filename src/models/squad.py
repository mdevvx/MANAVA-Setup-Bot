from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from uuid import UUID


class SquadStatus(str, Enum):
    ACTIVE = "active"
    DISBANDED = "disbanded"


class SquadRole(str, Enum):
    LEADER = "leader"
    OFFICER = "officer"
    MEMBER = "member"


class JoinRequestStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


@dataclass(frozen=True, slots=True)
class Squad:
    id: UUID
    name: str
    status: SquadStatus
    leader_user_id: int
    category_id: int
    role_id: int
    member_text_channel_id: int
    member_voice_channel_id: int
    officer_text_channel_id: int
    officer_voice_channel_id: int
    created_at: datetime
    disbanded_at: datetime | None
    archive_purge_after: datetime | None


@dataclass(frozen=True, slots=True)
class SquadMembership:
    id: UUID
    squad_id: UUID
    discord_user_id: int
    squad_role: SquadRole
    joined_at: datetime
    left_at: datetime | None


@dataclass(frozen=True, slots=True)
class SquadJoinRequest:
    id: UUID
    squad_id: UUID
    applicant_id: int
    status: JoinRequestStatus
    created_at: datetime
    decided_at: datetime | None
    decided_by: int | None


@dataclass(frozen=True, slots=True)
class NewSquadDiscordObjects:
    """IDs of the Discord objects provisioned for a brand-new squad, before the DB row exists."""

    role_id: int
    category_id: int
    member_text_channel_id: int
    member_voice_channel_id: int
    officer_text_channel_id: int
    officer_voice_channel_id: int


@dataclass(frozen=True, slots=True)
class EligibilityFailure:
    code: str
    message: str


@dataclass(frozen=True, slots=True)
class EligibilityResult:
    eligible: bool
    failures: tuple[EligibilityFailure, ...] = ()
