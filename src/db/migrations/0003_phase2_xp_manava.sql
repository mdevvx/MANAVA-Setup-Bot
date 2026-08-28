-- Phase 2: XP Economy, Leaderboards, and MANAVA Integration schema.

-- Unified Personal XP: personal_xp.lifetime_xp/season_xp become the REAL
-- accumulator this phase (Discord text XP + MANAVA event XP combined), no
-- longer the Phase 1 Discord-only stub. manava_user_id links a Discord user
-- to their MANAVA account — STUB manual linking (via /admin
-- link-manava-account) until Phase 3's real MANAVA account-linking lands,
-- same pattern as the existing verified_player stub column.
alter table personal_xp add column if not exists manava_user_id text;
create unique index if not exists personal_xp_manava_user_id_unique
    on personal_xp (manava_user_id)
    where manava_user_id is not null;

-- Per-membership-stint XP contribution to the CURRENT squad. Scoped to one
-- squad_memberships row (not the user globally), so it naturally starts at 0
-- again if someone leaves and later rejoins (a new row) — matching the
-- "never backfilled, never clawed back" rule without a separate table.
alter table squad_memberships add column if not exists contributed_xp integer not null default 0;

-- Lifetime + season XP per squad. Own table (not columns on squads) to match
-- the project's documented target schema list.
create table if not exists squad_xp (
    squad_id uuid primary key references squads(id),
    lifetime_xp bigint not null default 0,
    season_xp bigint not null default 0,
    updated_at timestamptz not null default now()
);

-- Backfill a row for any squad created before this table existed (Phase 1 squads).
insert into squad_xp (squad_id)
select id from squads
on conflict (squad_id) do nothing;

-- xp_config: admin-editable XP amounts. Key -> integer value, seeded with
-- client-confirmed defaults (2026-08-25); all tunable via /admin xp-config.
create table if not exists xp_config (
    key text primary key,
    value integer not null,
    updated_at timestamptz not null default now(),
    updated_by bigint
);

insert into xp_config (key, value) values
    ('skill_match_xp', 50),
    ('tournament_participation_xp', 100),
    ('placement_reward_1', 500),
    ('placement_reward_2', 300),
    ('placement_reward_3', 150)
on conflict (key) do nothing;

-- level_thresholds: Lifetime Squad XP required to reach level 2-7 (level 1 is
-- the starting level for every new squad, no threshold needed). Member caps
-- per level are fixed in src/constants.py, not stored here — only the XP
-- thresholds to reach each level are admin-configurable.
create table if not exists level_thresholds (
    level integer primary key check (level between 2 and 7),
    lifetime_squad_xp_required integer not null,
    updated_at timestamptz not null default now(),
    updated_by bigint
);

insert into level_thresholds (level, lifetime_squad_xp_required) values
    (2, 5000),
    (3, 15000),
    (4, 40000),
    (5, 100000),
    (6, 250000),
    (7, 600000)
on conflict (level) do nothing;

-- processed_events: dedupe guard so a retried/duplicate MANAVA event_id can
-- never grant XP twice — this is a hard correctness requirement.
create table if not exists processed_events (
    event_id text primary key,
    manava_user_id text not null,
    event_type text not null,
    discord_user_id bigint,
    xp_granted integer not null default 0,
    processed_at timestamptz not null default now()
);

-- bot_config: generic non-secret config store. The webhook auth secret and
-- polling URL/API key stay in environment variables regardless — never here.
create table if not exists bot_config (
    key text primary key,
    value jsonb not null,
    updated_at timestamptz not null default now()
);

insert into bot_config (key, value) values
    ('xp_excluded_channel_ids', '[]'::jsonb),
    ('manava_integration_mode', '"webhook"'::jsonb)
on conflict (key) do nothing;
