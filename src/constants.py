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
WAVE_XP_GATE = 1500

# --- Phase 2: Discord text XP ---
DISCORD_TEXT_XP_AMOUNT = 15
DISCORD_TEXT_XP_MIN_CHARS = 10
DISCORD_TEXT_XP_COOLDOWN_SECONDS = 60

# --- Phase 2: squad levels ---
# Member cap per level is a fixed rule straight from the spec, not admin-configurable.
# The Lifetime Squad XP required to REACH each level IS admin-configurable — see
# the level_thresholds table. Level 1 is the starting level (no threshold needed).
SQUAD_LEVEL_MEMBER_CAPS: dict[int, int] = {
    1: 20,
    2: 50,
    3: 100,
    4: 200,
    5: 300,
    6: 500,
    7: 1000,
}
MIN_SQUAD_LEVEL = 1
MAX_SQUAD_LEVEL = 7

# --- Phase 2: xp_config keys (admin-editable amounts, seeded with defaults in the migration) ---
XP_CONFIG_KEY_SKILL_MATCH = "skill_match_xp"
XP_CONFIG_KEY_TOURNAMENT_PARTICIPATION = "tournament_participation_xp"
XP_CONFIG_KEY_PLACEMENT_1ST = "placement_reward_1"
XP_CONFIG_KEY_PLACEMENT_2ND = "placement_reward_2"
XP_CONFIG_KEY_PLACEMENT_3RD = "placement_reward_3"
# Phase 3 / Gateway: extra XP when tournament_placement carries wonPrizeSlot=true
# (a paid prize-pool slot, not necessarily 1st). Seeded to 0 in migration 0007 —
# inert until an admin sets it, so it changes nothing by default.
XP_CONFIG_KEY_PRIZE_SLOT_BONUS = "prize_slot_bonus_xp"
ALL_XP_CONFIG_KEYS: tuple[str, ...] = (
    XP_CONFIG_KEY_SKILL_MATCH,
    XP_CONFIG_KEY_TOURNAMENT_PARTICIPATION,
    XP_CONFIG_KEY_PLACEMENT_1ST,
    XP_CONFIG_KEY_PLACEMENT_2ND,
    XP_CONFIG_KEY_PLACEMENT_3RD,
    XP_CONFIG_KEY_PRIZE_SLOT_BONUS,
)

# --- MANAVA event types ---
# Canonical names = the MANAVA Gateway's `eventType` values (gateway-diagram-en.html).
# The pre-Gateway names are kept as accepted aliases (MANAVA_EVENT_TYPE_ALIASES)
# so old payloads and the existing simulate-event harness still parse.
MANAVA_EVENT_MATCH_COMPLETED = "match_completed"
MANAVA_EVENT_TOURNAMENT_REGISTERED = "tournament_registered"
MANAVA_EVENT_TOURNAMENT_PLACEMENT = "tournament_placement"
ALL_MANAVA_EVENT_TYPES: tuple[str, ...] = (
    MANAVA_EVENT_MATCH_COMPLETED,
    MANAVA_EVENT_TOURNAMENT_REGISTERED,
    MANAVA_EVENT_TOURNAMENT_PLACEMENT,
)
MANAVA_EVENT_TYPE_ALIASES: dict[str, str] = {
    "skill_match_completed": MANAVA_EVENT_MATCH_COMPLETED,
    "tournament_participated": MANAVA_EVENT_TOURNAMENT_REGISTERED,
}

# Games the Gateway sends events for (gateway-diagram-en.html). Not enforced on
# inbound events (any value is stored) — used only for the simulate-event
# harness's dropdown.
MANAVA_GAMES: tuple[str, ...] = ("cs2", "swag", "billiard")

# --- Phase 2: bot_config keys ---
BOT_CONFIG_KEY_XP_EXCLUDED_CHANNELS = "xp_excluded_channel_ids"
BOT_CONFIG_KEY_MANAVA_INTEGRATION_MODE = "manava_integration_mode"
MANAVA_INTEGRATION_MODE_WEBHOOK = "webhook"
MANAVA_INTEGRATION_MODE_POLLING = "polling"

# --- Phase 2: leaderboards ---
GLOBAL_LEADERBOARD_TOP_HIGHLIGHT = 32

# --- Phase 3: application roles + review channel ---
# The bot resolves these by name and CREATES them if missing on startup
# (client decision, 2026-08-31) — unlike the squad/staff roles, which are
# assumed to already exist. Creation needs Manage Roles + Manage Channels.
ROLE_NAME_DEVELOPER_PENDING = "Developer Pending"
ROLE_NAME_DEVELOPER = "Developer"
ROLE_NAME_CREATOR = "Creator"
ROLE_NAME_STREAMER = "Streamer"

APPLICATION_ROLE_NAMES: tuple[str, ...] = (
    ROLE_NAME_DEVELOPER_PENDING,
    ROLE_NAME_DEVELOPER,
    ROLE_NAME_CREATOR,
    ROLE_NAME_STREAMER,
)

# Single private review channel for BOTH application types. Access is restricted
# to Admin + MANAVA Team only — Moderator and Senior Moderator are explicitly
# excluded (spec), even though they count as staff everywhere else.
CHANNEL_NAME_APPLICATIONS_REVIEW = "applications-review"

# --- Phase 3: application rules ---
# After a rejection, the same application type can't be resubmitted for this
# many days. Enforced server-side against the most recent rejected row.
APPLICATION_REJECT_COOLDOWN_DAYS = 30

# --- Phase 3: seasons ---
# The very first season created gets this number; each subsequent Start Season /
# Start New Season increments it.
FIRST_SEASON_NUMBER = 1
