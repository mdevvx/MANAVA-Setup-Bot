-- Phase 1: Squad System Core schema.
-- Shaped to match the project's final target schema so later
-- phases extend these tables rather than migrate/rename them.

create extension if not exists pgcrypto;

-- Combined per-user profile + XP table. verified_player and lifetime_xp are
-- both Phase 1 stubs (see column comments); season_xp is unused until Phase 2.
create table if not exists personal_xp (
    discord_user_id bigint primary key,
    verified_player boolean not null default false, -- STUB: replaced by MANAVA account-linking integration in Phase 3
    lifetime_xp integer not null default 0,          -- STUB: Discord-only accumulator, replaced by the full Unified XP system in Phase 2
    season_xp integer not null default 0,            -- unused until Phase 2 season logic lands
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create table if not exists squads (
    id uuid primary key default gen_random_uuid(),
    name text not null,
    name_lower text generated always as (lower(name)) stored,
    status text not null default 'active' check (status in ('active', 'disbanded')),
    leader_user_id bigint not null,
    category_id bigint not null,
    role_id bigint not null,
    member_text_channel_id bigint not null,
    member_voice_channel_id bigint not null,
    officer_text_channel_id bigint not null,
    officer_voice_channel_id bigint not null,
    created_at timestamptz not null default now(),
    disbanded_at timestamptz,
    archive_purge_after timestamptz,
    discord_objects_purged_at timestamptz
);

-- Squad names are reserved forever: unique across ALL rows regardless of
-- status, so a disbanded squad's name can never be reused. Rows are never
-- hard-deleted, which is what makes this permanent.
create unique index if not exists squads_name_lower_unique on squads (name_lower);
create index if not exists squads_status_category_idx on squads (status, category_id);

create table if not exists squad_memberships (
    id uuid primary key default gen_random_uuid(),
    squad_id uuid not null references squads(id),
    discord_user_id bigint not null,
    squad_role text not null check (squad_role in ('leader', 'officer', 'member')),
    joined_at timestamptz not null default now(),
    left_at timestamptz
);

-- A user can hold at most one ACTIVE membership at a time, globally. This is
-- the DB-level backstop for "not a member/owner of another active squad";
-- the leader also has a row here (squad_role = 'leader'), so one constraint
-- covers both the membership and leadership eligibility gates.
create unique index if not exists squad_memberships_one_active_per_user
    on squad_memberships (discord_user_id)
    where left_at is null;

create index if not exists squad_memberships_squad_id_idx on squad_memberships (squad_id);

create table if not exists squad_join_requests (
    id uuid primary key default gen_random_uuid(),
    squad_id uuid not null references squads(id),
    applicant_id bigint not null,
    status text not null default 'pending' check (status in ('pending', 'approved', 'rejected')),
    created_at timestamptz not null default now(),
    decided_at timestamptz,
    decided_by bigint
);

-- Only one pending request per (squad, applicant) at a time.
create unique index if not exists squad_join_requests_one_pending
    on squad_join_requests (squad_id, applicant_id)
    where status = 'pending';

create table if not exists squad_status_history (
    id uuid primary key default gen_random_uuid(),
    squad_id uuid not null references squads(id),
    old_status text,
    new_status text not null,
    actor_id bigint not null,
    reason text,
    changed_at timestamptz not null default now()
);

create table if not exists audit_logs (
    id uuid primary key default gen_random_uuid(),
    actor_id bigint not null,
    action text not null,
    target_type text not null,
    target_id text not null,
    old_value jsonb,
    new_value jsonb,
    reason text,
    created_at timestamptz not null default now()
);

create index if not exists audit_logs_target_idx on audit_logs (target_type, target_id);
