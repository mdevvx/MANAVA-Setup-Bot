# MANAVA Multiverse Bot

Custom Discord bot for the MANAVA Multiverse server: an esports squad system,
unified XP/leaderboard economy, and application review workflows, built in
phases against Supabase (Postgres) and Discord's API.

## Setup

1. Python 3.11+.
2. `pip install -r requirements-dev.txt` (or `requirements.txt` for a
   production-only install).
3. Copy `.env.example` to `.env` and fill in real values:
   - `DISCORD_BOT_TOKEN` — your bot's token.
   - `DISCORD_GUILD_ID` — the MANAVA Multiverse server's ID.
   - `DATABASE_URL` — the Supabase **session pooler connection string**
     (Project Settings → Database → Connection pooling → Session pooler URI).
     This is *not* the Supabase Project URL or the anon/service_role API key —
     this bot talks to Postgres directly via `asyncpg`, not through Supabase's
     REST API, so those aren't used anywhere. Use the pooler host
     (`aws-0-<region>.pooler.supabase.com`), not the direct
     `db.<ref>.supabase.co` host — the direct host is IPv6-only and was
     unreachable in testing from a plain IPv4 network. Session pooler (port
     5432), not transaction pooler (6543), since this bot holds a persistent
     connection pool for its whole runtime rather than short-lived connections.
   - `MANAVA_WEBHOOK_SECRET` — shared-secret bearer token the MANAVA webhook
     endpoint checks for (STUB auth until MANAVA provides their real
     integration contract — see `docs/manava-webhook-contract.md`). If unset,
     the webhook server just doesn't start.
   - `PORT` — what the webhook server listens on. Railway sets this
     automatically in production; only needed locally to override the 8080
     default.
4. Apply the schema: `python -m scripts.run_migrations` (tracks what's
   already applied in a `schema_migrations` table, safe to re-run). This
   includes enabling Row Level Security (no policies) on every table —
   the bot's direct Postgres connection is unaffected (RLS doesn't restrict
   the table owner), but it blocks Supabase's REST API from touching this
   data if the anon/service key is ever used anywhere else.
5. Run the bot: `python -m src.main`.

Use `!sync` (message command, not slash — Admin/MANAVA Team only) any time to
re-sync slash commands, re-check required Discord roles/categories,
re-apply category permissions, and refresh the XP-exclusion/MANAVA-mode
cache, all without restarting the bot.

## Required Discord setup

The bot resolves the following by name (case-insensitive) at startup and
refuses to enable squad features if any are missing (see
`src/discord_state/role_resolver.py`):

- Roles: `Admin`, `MANAVA Team`, `Senior Moderator`, `Moderator`,
  `Squad Leader`, `Squad Officer`, `Squad Member`, `Member`.
- Categories (create manually, styled to match the server's existing
  emoji-bracket category naming convention — see `src/constants.py`):
  `⚔️〔SQUADS 01〕`, `⚔️〔SQUADS 02〕`, `⚔️〔SQUADS 03〕`, `⚔️〔SQUADS 04〕`,
  `⚔️〔SQUADS 05〕`, `⚔️〔SQUADS 06〕`, `⚔️〔SQUADS 07〕`.

All of these are assumed to already exist on the server per the project spec
(roles) or are created manually by staff (the 7 SQUADS categories).

## Running tests

```
pytest
```

Tests are unit-level (service logic + permission-overwrite construction +
event-processing/dedup logic), using mocked repositories/Discord objects
rather than a live DB or gateway connection — see `tests/`.

## Layout

```
src/
  config.py, constants.py, errors.py, bot.py, main.py
  db/
    pool.py, migrations/, repositories/      # asyncpg data access
  discord_state/
    role_resolver.py     # name-lookup + cache of required roles/categories
    capacity.py           # SQUADS category assignment
    provisioning.py       # channel/role creation, permission overwrites, teardown
    xp_channel_filter.py  # which channels grant Discord text XP + cooldown check
    staff_check.py        # shared Admin/MANAVA Team permission check
  services/
    squad_eligibility.py, squad_lifecycle.py, squad_membership.py
    xp_service.py          # Unified Personal XP — the single XP grant choke point
    squad_xp_service.py     # squad level + member-capacity enforcement
    manava_event_service.py # the MANAVA event processing pipeline
    leaderboard_service.py  # global + per-squad leaderboard queries
  web/
    webhook_server.py     # aiohttp MANAVA webhook receiver (POST /webhooks/manava)
    polling.py              # REST-polling fallback, behind a config flag
  cogs/
    squads.py, admin.py, xp.py, help.py       # slash + message commands
  ui/
    confirm_view.py, squad_apply_view.py, paginated_view.py
  models/
    squad.py, xp.py                           # dataclasses/enums
docs/
  capacity-calculation.md, archive-model.md, manava-webhook-contract.md
scripts/
  run_migrations.py
```

## Known stubs (pending real external interfaces)

- `verified_player` is a manual admin override (`/admin set-verified`) until
  MANAVA account-linking lands in Phase 3.
- `manava_user_id` linking is a manual admin override
  (`/admin link-manava-account`) until Phase 3's real MANAVA account-linking
  integration — same pattern as `verified_player`.
- The MANAVA webhook endpoint itself is real and working
  (`POST /webhooks/manava`), but its authentication is a shared-secret
  bearer-token STUB until MANAVA provides their real auth contract. Use
  `/xpconfig simulate-manava-event` to exercise the full pipeline without a
  real webhook call.
- The REST-polling fallback (`src/web/polling.py`) is structurally complete
  but untested — no real MANAVA polling endpoint exists yet.
- `ApplyDecisionView` (the DM Approve/Reject buttons) is not a Discord.py
  *persistent* view — its buttons stop working across a bot restart. Full
  restart resilience is Phase 3 reliability scope.
- The Discord text-XP 60-second cooldown is tracked in-memory, not
  DB-persisted — resets on bot restart (acceptable tradeoff, not a bug).
