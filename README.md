# MANAVA Multiverse Bot — Phase 1 (Squad System Core)

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
4. Apply the schema: `python -m scripts.run_migrations` (tracks what's
   already applied in a `schema_migrations` table, safe to re-run). This
   includes enabling Row Level Security (no policies) on every table —
   the bot's direct Postgres connection is unaffected (RLS doesn't restrict
   the table owner), but it blocks Supabase's REST API from touching this
   data if the anon/service key is ever used anywhere else.
5. Run the bot: `python -m src.main`.

Use `/admin sync` (Admin/MANAVA Team only) any time to re-sync slash
commands and re-check that the required Discord roles/categories still
resolve, without restarting the bot.

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

Tests are unit-level (service logic + permission-overwrite construction),
using mocked repositories/Discord objects rather than a live DB or gateway
connection — see `tests/`.

## Layout

```
src/
  config.py, constants.py, errors.py, bot.py, main.py
  db/
    pool.py, migrations/, repositories/      # asyncpg data access
  discord_state/
    role_resolver.py    # name-lookup + cache of required roles/categories
    capacity.py          # SQUADS 01-07 category assignment
    provisioning.py      # channel/role creation, permission overwrites, teardown
  services/
    squad_eligibility.py, squad_lifecycle.py, squad_membership.py, xp_stub_service.py
  cogs/
    squads.py, admin.py                       # slash commands
  ui/
    confirm_view.py, squad_apply_view.py       # buttons
  models/
    squad.py                                  # dataclasses/enums
docs/
  capacity-calculation.md, archive-model.md
scripts/
  run_migrations.py
```

## Known Phase 1 stubs

- `verified_player` is a manual admin override (`/admin set-verified`) until
  MANAVA account-linking lands in Phase 3.
- Personal Lifetime XP is a simple +1-per-Discord-message accumulator (no
  cooldown or content rules) until the full Unified XP system lands in
  Phase 2. `/admin add-xp` exists as a faster test/support utility.
- `ApplyDecisionView` (the DM Approve/Reject buttons) is not a Discord.py
  *persistent* view — its buttons stop working across a bot restart. Full
  restart resilience is Phase 3 reliability scope.
