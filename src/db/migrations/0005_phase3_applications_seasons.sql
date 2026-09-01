-- Phase 3: Applications, Seasons.
-- Adds the application-review workflow tables and the season-state table.
-- No changes to existing tables — the season reset operates on the
-- personal_xp.season_xp / squad_xp.season_xp columns that already exist.

-- applications: one row per submitted application, either type. The
-- type-specific answers live in `fields` (jsonb) rather than as columns, so
-- the two very different field sets (Developer vs Creator/Streamer) share one
-- table and one workflow. `fields` can contain PII (contact email) and is
-- NEVER written to audit_logs or the generic logger — it only ever leaves the
-- DB inside the private applications-review flow.
create table if not exists applications (
    id uuid primary key default gen_random_uuid(),
    applicant_id       bigint not null,
    applicant_username text   not null,        -- captured at submit time (name can change later)
    app_type text not null check (app_type in ('developer', 'creator_streamer')),
    status   text not null default 'pending'
             check (status in ('pending', 'more_info_requested', 'approved', 'rejected')),
    fields   jsonb  not null,
    review_channel_id bigint,                  -- where the review message was posted...
    review_message_id bigint,                  -- ...and its id, so the persistent review view survives restarts
    submitted_at timestamptz not null default now(),
    decided_at   timestamptz,                  -- set only on approve/reject
    decided_by   bigint
);

-- Hard cap: at most one ACTIVE application per (user, type) at a time.
-- "Active" = pending or awaiting the applicant's more-info response. Once a row
-- is approved/rejected it no longer blocks a future application of that type
-- (subject to the reject cooldown, which is enforced in code, not here).
create unique index if not exists applications_one_active_per_type
    on applications (applicant_id, app_type)
    where status in ('pending', 'more_info_requested');

-- Supports the 30-day post-rejection cooldown lookup: "most recent rejected
-- application of this type for this user".
create index if not exists applications_reject_cooldown_idx
    on applications (applicant_id, app_type, decided_at desc)
    where status = 'rejected';

-- The persistent review view resolves an application from the review-channel
-- message its buttons are attached to (applications_repo.get_by_review_message)
-- on every Approve / Reject / Request-More-Info click — this keeps that O(1).
create index if not exists applications_review_message_idx
    on applications (review_message_id)
    where review_message_id is not null;

-- application_history: an append-only trail of every status change and every
-- message exchanged (rejection reason, more-info request, applicant's reply).
-- `note` can contain PII (the applicant's own free-text reply) — same handling
-- rule as applications.fields: private-flow only.
create table if not exists application_history (
    id uuid primary key default gen_random_uuid(),
    application_id uuid not null references applications(id),
    old_status text,
    new_status text not null,
    actor_id   bigint not null,
    actor_role text not null check (actor_role in ('applicant', 'reviewer', 'system')),
    note       text,
    created_at timestamptz not null default now()
);

create index if not exists application_history_app_idx
    on application_history (application_id, created_at);

-- season_state: one row per season. Seasons are started/ended manually by an
-- admin; only one can be 'active' at a time (partial unique index below).
-- Start New Season = end the active season + open a fresh one + zero every
-- season_xp counter (that reset is done in a transaction by season_service,
-- not by this schema).
create table if not exists season_state (
    id uuid primary key default gen_random_uuid(),
    season_number integer not null,
    status text not null check (status in ('active', 'ended')),
    started_at timestamptz not null default now(),
    started_by bigint not null,
    ended_at   timestamptz,
    ended_by   bigint
);

create unique index if not exists season_state_one_active
    on season_state (status)
    where status = 'active';

create unique index if not exists season_state_number_unique
    on season_state (season_number);
