"""Application domain model: the two application types (Developer,
Creator/Streamer), their status lifecycle, and the field definitions that
drive both the submission form and the review embed.

The per-type answers are stored as a flat ``dict[str, str]`` (``fields`` on the
DB row) keyed by the ``*_FIELD_KEYS`` below, rather than as a rigid dataclass
per type — the two field sets barely overlap and are display-only once
submitted, so a keyed dict with an explicit label map is simpler than two
parallel schemas plus conversion code.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from uuid import UUID


class AppType(str, Enum):
    DEVELOPER = "developer"
    CREATOR_STREAMER = "creator_streamer"

    @property
    def label(self) -> str:
        return "Developer" if self is AppType.DEVELOPER else "Creator / Streamer"


class AppStatus(str, Enum):
    PENDING = "pending"
    MORE_INFO_REQUESTED = "more_info_requested"
    APPROVED = "approved"
    REJECTED = "rejected"

    @property
    def is_active(self) -> bool:
        """Active = still blocks a second application of the same type."""
        return self in (AppStatus.PENDING, AppStatus.MORE_INFO_REQUESTED)

    @property
    def is_decided(self) -> bool:
        return self in (AppStatus.APPROVED, AppStatus.REJECTED)


class HistoryActorRole(str, Enum):
    APPLICANT = "applicant"
    REVIEWER = "reviewer"
    SYSTEM = "system"


@dataclass(frozen=True, slots=True)
class Application:
    id: UUID
    applicant_id: int
    applicant_username: str
    app_type: AppType
    status: AppStatus
    fields: dict[str, str]
    review_channel_id: int | None
    review_message_id: int | None
    submitted_at: datetime
    decided_at: datetime | None
    decided_by: int | None


@dataclass(frozen=True, slots=True)
class ApplicationHistoryEntry:
    id: UUID
    application_id: UUID
    old_status: AppStatus | None
    new_status: AppStatus
    actor_id: int
    actor_role: HistoryActorRole
    note: str | None
    created_at: datetime


# --- Field definitions -------------------------------------------------------
#
# Order here is the order shown in the review embed. Keys are the jsonb keys in
# applications.fields. "select" fields are collected via dropdowns in an
# ephemeral pre-form; the rest are free text collected in a modal (Discord caps
# a modal at 5 inputs, hence the split — see ui/application_apply_view.py).

ADDITIONAL_COMMENTS_KEY = "additional_comments"

# PII / contact fields: never logged outside the applications-review flow.
PII_FIELD_KEYS: frozenset[str] = frozenset({"contact_email"})


# Deliberately permissive — reject only clearly-broken input, no
# deliverability / reachability checks (that's the reviewer's job):
#   email — needs an "@" and a dotted domain, no whitespace
#   url   — needs an http(s):// scheme and a dotted host, no whitespace
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_URL_RE = re.compile(r"^https?://[^\s.]+\.[^\s]+$", re.IGNORECASE)

_VALIDATORS: dict[str, tuple[re.Pattern[str], str]] = {
    "email": (_EMAIL_RE, "is not a valid email address"),
    "url": (_URL_RE, "is not a valid URL (must start with http:// or https://)"),
}


@dataclass(frozen=True, slots=True)
class FieldSpec:
    key: str
    label: str
    kind: str  # "text" | "paragraph" | "select"
    required: bool = True
    options: tuple[str, ...] = ()
    validate: str = ""  # "" | "email" | "url"


DEVELOPER_FIELDS: tuple[FieldSpec, ...] = (
    FieldSpec("company_studio", "Company / Studio", "text"),
    FieldSpec("project_game", "Project / Game", "text"),
    FieldSpec("website_url", "Website / Portfolio URL", "text", validate="url"),
    FieldSpec(
        "integration_interest",
        "Integration Interest",
        "select",
        options=(
            "API integration",
            "SDK / client library",
            "Game data / event feed",
            "Co-marketing / partnership",
            "Just exploring",
            "Other",
        ),
    ),
    FieldSpec("relevant_experience", "Relevant Experience", "paragraph"),
    FieldSpec("contact_email", "Contact Email", "text", validate="email"),
    FieldSpec(ADDITIONAL_COMMENTS_KEY, "Additional Comments", "paragraph", required=False),
)

CREATOR_STREAMER_FIELDS: tuple[FieldSpec, ...] = (
    FieldSpec("profile_type", "Profile Type", "select", options=("Creator", "Streamer", "Both")),
    FieldSpec(
        "platform",
        "Primary Platform",
        "select",
        options=("Twitch", "YouTube", "Kick", "TikTok", "Instagram", "X / Twitter", "Other"),
    ),
    FieldSpec(
        "region",
        "Region",
        "select",
        options=(
            "North America",
            "Latin America",
            "Europe",
            "MENA",
            "Sub-Saharan Africa",
            "Asia-Pacific",
            "Oceania",
            "Other",
        ),
    ),
    FieldSpec(
        "audience_size",
        "Audience Size (followers/subs)",
        "select",
        options=("Under 1K", "1K – 10K", "10K – 50K", "50K – 250K", "250K+"),
    ),
    FieldSpec("profile_url", "Profile / Channel URL", "text", validate="url"),
    FieldSpec("content_languages", "Content Languages", "text"),
    FieldSpec("avg_viewers", "Average Views / Live Viewers", "text"),
    FieldSpec("content_examples", "Content Examples", "paragraph"),
    FieldSpec("contact_email", "Contact Email", "text", validate="email"),
    FieldSpec(ADDITIONAL_COMMENTS_KEY, "Additional Comments", "paragraph", required=False),
)

FIELDS_BY_TYPE: dict[AppType, tuple[FieldSpec, ...]] = {
    AppType.DEVELOPER: DEVELOPER_FIELDS,
    AppType.CREATOR_STREAMER: CREATOR_STREAMER_FIELDS,
}


# Discord hard limits: a modal holds at most 5 text inputs; a message holds at
# most 5 action rows (so at most 5 selects, leaving no room for a button, or 4
# selects + 1 button). Both field sets are arranged to fit:
#   selects  -> ephemeral pre-form (<=4) + a "Continue" button
#   required free-text -> one modal (exactly 5 for both types)
#   the single optional "Additional Comments" paragraph -> a follow-up button
MODAL_FIELD_LIMIT = 5
PREFORM_SELECT_LIMIT = 4


def field_specs(app_type: AppType) -> tuple[FieldSpec, ...]:
    return FIELDS_BY_TYPE[app_type]


def select_specs(app_type: AppType) -> tuple[FieldSpec, ...]:
    return tuple(f for f in field_specs(app_type) if f.kind == "select")


def modal_specs(app_type: AppType) -> tuple[FieldSpec, ...]:
    """The required free-text fields, collected in the submission modal."""
    return tuple(f for f in field_specs(app_type) if f.kind != "select" and f.required)


def followup_spec(app_type: AppType) -> FieldSpec | None:
    """The single optional paragraph field, collected after the modal via its
    own button (it doesn't fit in the 5-input modal alongside the required
    fields). Returns None if a type has no optional field."""
    optional = [f for f in field_specs(app_type) if f.kind != "select" and not f.required]
    return optional[0] if optional else None


def label_for(app_type: AppType, key: str) -> str:
    for spec in field_specs(app_type):
        if spec.key == key:
            return spec.label
    return key


def validate_fields(app_type: AppType, fields: dict[str, str]) -> list[str]:
    """Content validation on a submitted application. Returns a list of
    human-readable problems (empty = OK). Widget-level rules (required, which
    options) are already enforced by the form; this catches what a Discord
    modal can't — a malformed contact email or website/profile URL — which
    must block submission."""
    problems: list[str] = []
    for spec in field_specs(app_type):
        value = (fields.get(spec.key) or "").strip()
        if spec.required and not value:
            problems.append(f"{spec.label} is required.")
            continue
        if not value:
            continue
        rule = _VALIDATORS.get(spec.validate)
        if rule is not None and not rule[0].match(value):
            problems.append(f'{spec.label}: "{value}" {rule[1]}.')
    return problems


# Fail fast at import time if a future field edit breaks the Discord layout limits.
for _t in AppType:
    assert len(modal_specs(_t)) <= MODAL_FIELD_LIMIT, f"{_t}: too many required modal fields"
    assert len(select_specs(_t)) <= PREFORM_SELECT_LIMIT, f"{_t}: too many select fields for one pre-form"
