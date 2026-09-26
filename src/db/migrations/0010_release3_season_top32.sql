-- Release 3, Milestone 1: Season state machine, Top-32 qualification, seeding.
-- Additive only — the existing `status` column, season_state_one_active /
-- season_state_number_unique indexes, and the already-shipped
-- /season start|end|new commands are untouched. `phase` tracks where an
-- ACTIVE season sits in Qualification -> Qualification Lock -> Top-32
-- Playoffs -> Season Complete; `status` still just answers "is this the
-- current season" the same way it always has.

alter table season_state add column if not exists phase text not null default 'qualification'
    check (phase in ('qualification', 'qualification_lock', 'top32_playoffs', 'season_complete'));
alter table season_state add column if not exists locked_at timestamptz;
alter table season_state add column if not exists locked_by bigint;
alter table season_state add column if not exists published_at timestamptz;
alter table season_state add column if not exists published_by bigint;

-- season_qualifications: the FULL active-squad ranking snapshot taken at
-- Qualification Lock — not just the top 32. Keeping every rank (not only
-- 1-32) is what makes pre-publish replacement automatic: the "current
-- Top-32" is simply the first 32 rows still `status = 'qualified'`, ordered
-- by `rank`, so a withdrawal/disqualification naturally pulls in whoever was
-- next without any renumbering. `seed` is filled in at Publish (client
-- confirmed 2026-09-23: fresh 1..32 over the survivors, in rank order — not
-- pinned to each squad's original rank number).
create table if not exists season_qualifications (
    id uuid primary key default gen_random_uuid(),
    season_id uuid not null references season_state(id),
    squad_id  uuid not null references squads(id),
    rank integer not null,
    season_xp_snapshot   bigint not null,
    lifetime_xp_snapshot bigint not null,
    status text not null default 'qualified'
        check (status in ('qualified', 'withdrawn', 'disqualified')),
    seed integer,
    decided_by bigint,
    decided_at timestamptz,
    decided_reason text,
    created_at timestamptz not null default now(),
    unique (season_id, squad_id),
    unique (season_id, rank)
);

create index if not exists season_qualifications_top32_idx
    on season_qualifications (season_id, status, rank);

-- season_history: the final Squad Leaderboard snapshot taken at Season
-- Complete (client confirmed 2026-09-23: full squad standings, explicitly
-- NOT a per-member snapshot). `ocean_masters_final_standing` is reserved for
-- Milestone 2 to fill in later — inert (always null) until that ships.
create table if not exists season_history (
    id uuid primary key default gen_random_uuid(),
    season_id uuid not null references season_state(id),
    squad_id  uuid not null references squads(id),
    final_rank integer not null,
    final_season_xp bigint not null,
    lifetime_xp_at_completion bigint not null,
    qualified_top32 boolean not null default false,
    ocean_masters_final_standing text,
    created_at timestamptz not null default now(),
    unique (season_id, squad_id)
);

create index if not exists season_history_season_idx on season_history (season_id, final_rank);
