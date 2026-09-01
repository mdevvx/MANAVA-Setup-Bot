-- Move every bot-owned table out of `public` into a dedicated `discord_bot`
-- schema.
--
-- Why: this bot shares its Postgres database with other MANAVA services.
-- Several of its table names are generic (`applications`, `audit_logs`,
-- `bot_config`, `season_state`, `processed_events`, `personal_xp`). If another
-- service later created a table of the same name in `public`, this bot's
-- `create table if not exists` would silently no-op and its code would then
-- read/write the wrong table. A private schema removes that whole class of
-- collision.
--
-- The bot connects with `search_path = discord_bot, public` (see
-- src/db/pool.py) and the migration runner does the same (see
-- scripts/run_migrations.py), so every unqualified table reference in the code
-- resolves here. `public` stays on the path only so shared objects
-- (pgcrypto, etc.) still resolve. `schema_migrations` is relocated by the
-- runner itself, not here, so a from-scratch clone still ends up consistent.
--
-- `set schema` is a metadata-only operation (instant, transactional, no data
-- rewrite). `if exists` makes each line a no-op if the table was already
-- moved or never existed.

create schema if not exists discord_bot;

alter table if exists public.personal_xp          set schema discord_bot;
alter table if exists public.squads               set schema discord_bot;
alter table if exists public.squad_memberships    set schema discord_bot;
alter table if exists public.squad_join_requests  set schema discord_bot;
alter table if exists public.squad_status_history set schema discord_bot;
alter table if exists public.audit_logs           set schema discord_bot;
alter table if exists public.squad_xp             set schema discord_bot;
alter table if exists public.xp_config            set schema discord_bot;
alter table if exists public.level_thresholds     set schema discord_bot;
alter table if exists public.processed_events     set schema discord_bot;
alter table if exists public.bot_config           set schema discord_bot;
alter table if exists public.applications         set schema discord_bot;
alter table if exists public.application_history  set schema discord_bot;
alter table if exists public.season_state         set schema discord_bot;
