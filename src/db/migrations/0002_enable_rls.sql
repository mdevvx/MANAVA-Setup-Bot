-- Enable Row Level Security on every bot-owned table, with zero policies.
--
-- This bot never talks to Supabase's REST/PostgREST API — it connects
-- directly to Postgres via asyncpg as the table owner (the `postgres` role).
-- RLS does NOT restrict the table owner by default (only FORCE ROW LEVEL
-- SECURITY would do that, which we are deliberately not setting), so this
-- has zero effect on the bot's own queries.
--
-- What it DOES do: Supabase auto-exposes every public-schema table over its
-- REST API regardless of whether anything actually uses that API. With RLS
-- enabled and no policies defined, PostgREST's anon/authenticated/service
-- roles get a default-deny on these tables — closing off a path that would
-- otherwise let the anon/service key (if it ever leaks or gets reused
-- elsewhere) read or write this data directly, bypassing every eligibility
-- check, permission check, and audit log entry the bot enforces.

alter table personal_xp enable row level security;
alter table squads enable row level security;
alter table squad_memberships enable row level security;
alter table squad_join_requests enable row level security;
alter table squad_status_history enable row level security;
alter table audit_logs enable row level security;
alter table schema_migrations enable row level security;
