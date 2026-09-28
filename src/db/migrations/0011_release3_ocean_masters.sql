-- Release 3, Milestone 2: Ocean Masters tournament module.
-- Deployed disabled by default (every tournament starts in 'draft'; nothing
-- here changes existing behavior) — client confirmed this can ship and be
-- QA'd while not publicly launched.

-- One Ocean Masters tournament per season: the spec consistently talks about
-- "the current Ocean Masters" as a singular thing per season, not a list.
create table if not exists ocean_masters (
    id uuid primary key default gen_random_uuid(),
    season_id uuid not null references season_state(id),
    mode text not null check (mode in ('single_game', 'cross_game')),
    games text[] not null,
    min_squads_required integer,
    status text not null default 'draft'
        check (status in ('draft', 'launched', 'completed')),
    launched_at timestamptz,
    launched_by bigint,
    completed_at timestamptz,
    winner_squad_id uuid references squads(id),
    created_by bigint not null,
    created_at timestamptz not null default now(),
    unique (season_id)
);

-- One row per bracket matchup. `seed_a`/`seed_b` are carried forward across
-- rounds (a round-2 match's seeds are whichever seeds its two round-1 winners
-- originally held) purely for display — advancement itself is driven by
-- `winner_squad_id`, not by seed arithmetic.
create table if not exists ocean_masters_matches (
    id uuid primary key default gen_random_uuid(),
    tournament_id uuid not null references ocean_masters(id),
    round integer not null,
    seed_a integer not null,
    seed_b integer not null,
    squad_a_id uuid references squads(id),
    squad_b_id uuid references squads(id),
    per_discipline_results jsonb not null default '{}'::jsonb,
    winner_squad_id uuid references squads(id),
    status text not null default 'pending'
        check (status in ('pending', 'completed', 'technical_loss', 'no_show', 'disqualified', 'forfeit')),
    decided_by bigint,
    decided_at timestamptz,
    decided_reason text,
    created_at timestamptz not null default now(),
    unique (tournament_id, round, seed_a)
);

create index if not exists ocean_masters_matches_tournament_idx
    on ocean_masters_matches (tournament_id, round);
