from __future__ import annotations

import re

# --- Staff roles authorized to see all squad channels ---
ROLE_NAME_ADMIN = "Admin"
ROLE_NAME_MANAVA_TEAM = "MANAVA Team"
ROLE_NAME_SENIOR_MODERATOR = "Senior Moderator"
ROLE_NAME_MODERATOR = "Moderator"

STAFF_ROLE_NAMES: tuple[str, ...] = (
    ROLE_NAME_ADMIN,
    ROLE_NAME_MANAVA_TEAM,
    ROLE_NAME_SENIOR_MODERATOR,
    ROLE_NAME_MODERATOR,
)

# --- Shared squad roles, reused across all squads (assumed to already exist) ---
ROLE_NAME_SQUAD_LEADER = "Squad Leader"
ROLE_NAME_SQUAD_OFFICER = "Squad Officer"
ROLE_NAME_SQUAD_MEMBER = "Squad Member"

# --- Onboarding gate ---
# Decision (2026-08-25): "onboarding complete" collapses into "Member role present" — one check, not two.
ROLE_NAME_MEMBER = "Member"

# --- Roles the bot must never grant under any circumstances (defense in depth ---
# for the least-privilege requirement finalized in Phase 3, but the guard lives
# here from Phase 1 on since the bot already grants roles starting Phase 1).
PROTECTED_ROLE_NAMES: tuple[str, ...] = (
    ROLE_NAME_ADMIN,
    ROLE_NAME_MANAVA_TEAM,
    ROLE_NAME_SENIOR_MODERATOR,
    ROLE_NAME_MODERATOR,
)

ALL_RESOLVED_ROLE_NAMES: tuple[str, ...] = (
    *STAFF_ROLE_NAMES,
    ROLE_NAME_SQUAD_LEADER,
    ROLE_NAME_SQUAD_OFFICER,
    ROLE_NAME_SQUAD_MEMBER,
    ROLE_NAME_MEMBER,
)

# --- Squad category distribution ---
# Styled to match the server's existing category naming convention (e.g. the
# "🪪〔ONBOARDING〕" category) — client creates these manually, exact name match
# required (case-insensitive; see discord_state/role_resolver.py).
SQUAD_CATEGORY_NAMES: tuple[str, ...] = tuple(f"⚔️〔SQUADS {i:02d}〕" for i in range(1, 8))
MAX_SQUADS_PER_CATEGORY = 10
CHANNELS_PER_SQUAD = 4
MAX_CHANNELS_PER_CATEGORY = MAX_SQUADS_PER_CATEGORY * CHANNELS_PER_SQUAD  # 40
MAX_ACTIVE_SQUADS = MAX_SQUADS_PER_CATEGORY * len(SQUAD_CATEGORY_NAMES)  # 70

# --- Squad membership rules ---
MAX_OFFICERS_PER_SQUAD = 2

# --- Squad naming rules (client-confirmed defaults, 2026-08-25) ---
SQUAD_NAME_MIN_LEN = 3
SQUAD_NAME_MAX_LEN = 32
SQUAD_NAME_PATTERN = re.compile(r"^[A-Za-z0-9 _-]+$")

# --- Eligibility ---
# STUB: replaced by full Unified XP system in Phase 2
WAVE_XP_GATE = 1500
