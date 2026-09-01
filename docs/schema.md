# Database schema

Supabase Postgres, accessed directly via `asyncpg` (not the REST API). All
DDL lives in `src/db/migrations/*.sql`, applied in filename order by
`python -m scripts.run_migrations` (tracked in `schema_migrations`, idempotent).

**All bot-owned tables live in a dedicated `discord_bot` Postgres schema**
(migration `0008`), not `public` — this database is shared with other MANAVA
services (Supabase's own `auth` / `realtime` schemas are visible here too), and
several bot table names are generic (`applications`, `audit_logs`,
`bot_config`, …). The bot's connection pool and the migration runner both set
`search_path = discord_bot, public`, so unqualified table references in the
code resolve to `discord_bot`; `public` stays on the path only for shared
objects (pgcrypto etc.).

Every table also has Row Level Security enabled with **no policies** — a
default-deny for the Supabase REST API; the bot connects as the table owner so
RLS doesn't affect it (see `0002` / `0004` / `0006`).

Migration files:

| File | Adds |
|---|---|
| `0001_phase1_squads.sql` | `personal_xp`, `squads`, `squad_memberships`, `squad_join_requests`, `squad_status_history`, `audit_logs` |
| `0002_enable_rls.sql` | RLS on the above |
| `0003_phase2_xp_manava.sql` | `squad_xp`, `xp_config`, `level_thresholds`, `processed_events`, `bot_config`; `personal_xp.manava_user_id`; `squad_memberships.contributed_xp` |
| `0004_enable_rls_phase2.sql` | RLS on the Phase 2 tables |
| `0005_phase3_applications_seasons.sql` | `applications`, `application_history`, `season_state` |
| `0006_enable_rls_phase3.sql` | RLS on the Phase 3 tables |
| `0007_gateway_xp_config.sql` | seeds `xp_config` row `prize_slot_bonus_xp = 0` |
| `0008_isolate_bot_schema.sql` | moves every bot table from `public` into the `discord_bot` schema |

---

## Identity & XP

### `personal_xp`
One row per Discord user. The canonical Unified Personal XP counters.

| Column | Notes |
|---|---|
| `discord_user_id` (PK) | |
| `verified_player` | Verified Player gate. Manual override (`/admin set-verified`) or, in Gateway mode, cached from the Gateway's `verifiedPlayer`. |
| `manava_user_id` (unique, nullable) | Discord ↔ MANAVA id map. Manual (`/admin link-manava-account`) or cached from the Gateway identity lookup. Enables reverse lookup for inbound events. |
| `lifetime_xp` | Personal Lifetime XP — never reset. Feeds the Wave 1500 squad-creation gate. |
| `season_xp` | Personal Season XP — zeroed by Start New Season. |

Every XP grant (`xp_service.grant_personal_xp`) increments `lifetime_xp` and
`season_xp` together.

### `xp_config`
Admin-editable XP amounts (`/xpconfig set-xp`). Key → int value. Keys:
`skill_match_xp`, `tournament_participation_xp`, `placement_reward_1/2/3`,
`prize_slot_bonus_xp`. Seeded with client-confirmed defaults in `0003` / `0007`.

### `level_thresholds`
Lifetime Squad XP required to reach squad levels 2–7 (`/xpconfig set-threshold`).
Level 1 is the floor (no threshold). Member caps per level are fixed in
`src/constants.py`, not here.

### `processed_events`
Dedup guard for inbound MANAVA events. `event_id` (PK) is reserved *before* any
XP is computed, so a retried/duplicate delivery can never double-grant. Stores
`manava_user_id`, `event_type`, resolved `discord_user_id`, `xp_granted`.

---

## Squads

### `squads`
One row per squad, ever (never hard-deleted — that's what makes name
reservation permanent, via the `name_lower` unique index across all statuses).

| Column | Notes |
|---|---|
| `id` (PK, uuid) | |
| `name`, `name_lower` (generated, unique) | |
| `status` | `active` \| `disbanded` |
| `leader_user_id` | denormalised; the authoritative leader is the `squad_memberships` row with `squad_role = 'leader'` |
| `category_id`, `role_id`, `member_text_channel_id`, `member_voice_channel_id`, `officer_text_channel_id`, `officer_voice_channel_id` | Discord object ids |
| `disbanded_at`, `archive_purge_after`, `discord_objects_purged_at` | 30-day archive lifecycle (see `archive-model.md`) |

### `squad_memberships`
One row per user per membership stint (a new row on rejoin).

| Column | Notes |
|---|---|
| `squad_id` → `squads.id` | |
| `discord_user_id` | |
| `squad_role` | `leader` \| `officer` \| `member` |
| `joined_at`, `left_at` | `left_at IS NULL` = active. Partial unique index on `discord_user_id WHERE left_at IS NULL` enforces one active squad per user globally. |
| `contributed_xp` | This stint's 1:1 contribution to the current squad. Not backfilled on join, not clawed back on leave, **not** reset by a season reset. |

### `squad_join_requests`
`/squad apply` requests. `status` `pending` \| `approved` \| `rejected`;
partial unique index allows one pending request per (squad, applicant).

### `squad_xp`
One row per squad. `lifetime_xp` (permanent) and `season_xp` (zeroed by Start
New Season). Incremented 1:1 when a current member earns Personal XP.

### `squad_status_history`
Append-only log of `squads.status` transitions: `old_status`, `new_status`,
`actor_id`, `reason`, `changed_at`.

---

## Applications

### `applications`
One row per submitted application, either type.

| Column | Notes |
|---|---|
| `id` (PK, uuid) | |
| `applicant_id`, `applicant_username` | username captured at submit time |
| `app_type` | `developer` \| `creator_streamer` |
| `status` | `pending` \| `more_info_requested` \| `approved` \| `rejected` |
| `fields` (jsonb) | type-specific answers, keyed per `src/models/application.py`. **Contains PII (contact email)** — never logged outside the applications-review flow. |
| `review_channel_id`, `review_message_id` | the review-channel message the persistent Approve/Reject/Request-More-Info view is attached to |
| `submitted_at`, `decided_at`, `decided_by` | |

Indexes: partial unique on `(applicant_id, app_type) WHERE status IN
('pending','more_info_requested')` — one active application per type;
`(applicant_id, app_type, decided_at DESC) WHERE status = 'rejected'` — the
30-day reapplication cooldown lookup.

### `application_history`
Append-only trail: `old_status`, `new_status`, `actor_id`, `actor_role`
(`applicant` \| `reviewer` \| `system`), `note` (rejection reason / info
request / applicant reply — **may contain PII**, private-flow only), `created_at`.

---

## Seasons

### `season_state`
One row per season. `season_number` (unique), `status` (`active` \| `ended`,
partial unique index allows one `active`), `started_at`/`started_by`,
`ended_at`/`ended_by`. Start New Season ends the active row, zeroes every
`personal_xp.season_xp` and `squad_xp.season_xp` in one transaction, and inserts
a fresh `active` row.

---

## Cross-cutting

### `audit_logs`
Every administrative / lifecycle change: `actor_id`, `action` (dotted string,
e.g. `squad.disband`, `application.approve`, `season.start_new`,
`admin.add_xp`), `target_type`, `target_id`, `old_value`/`new_value` (jsonb),
`reason`, `created_at`. Application `fields` PII is deliberately excluded from
`new_value`.

### `bot_config`
Generic non-secret key→jsonb store. Keys: `xp_excluded_channel_ids` (array),
`manava_integration_mode` (`webhook` \| `polling`). Secrets never go here.

### `schema_migrations`
`filename` (PK), `applied_at`. Written by `scripts/run_migrations.py`.
