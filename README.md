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
   - `MANAVA_GATEWAY_BASE_URL` + `DISCORD_BACKEND_API_KEY` +
     `WEBHOOK_SIGNING_SECRET` — the real MANAVA Gateway integration (identity
     lookup + HMAC-signed event webhooks). Set all three to enable "Gateway
     mode"; leave unset for stub mode (manual admin overrides + legacy webhook
     auth). See `docs/manava-gateway-integration.md`.
   - `MANAVA_WEBHOOK_SECRET` — DEPRECATED legacy bearer-token webhook auth,
     used only if `WEBHOOK_SIGNING_SECRET` is unset. The webhook server starts
     if either is set.
   - `PORT` — what the webhook/health server listens on. Most hosts inject
     this; only needed locally to override the 8080 default.
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

The application roles (`Developer Pending`, `Developer`, `Creator`,
`Streamer`) and the `applications-review` channel are **auto-created by the
bot** on startup / `!sync` if missing (needs Manage Roles + Manage Channels).
The channel is locked to Admin + MANAVA Team; Moderator and Senior Moderator
are explicitly denied.

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
    role_resolver.py       # name-lookup + cache of required roles/categories
    applications_setup.py   # resolve/CREATE application roles + #applications-review
    capacity.py             # SQUADS category assignment
    provisioning.py         # channel/role creation, permission overwrites, teardown
    role_safety.py          # single choke point for granting roles (protected-role deny-list)
    xp_channel_filter.py    # which channels grant Discord text XP + cooldown check
    staff_check.py          # shared Admin/MANAVA Team permission check
  services/
    squad_eligibility.py, squad_lifecycle.py, squad_membership.py
    xp_service.py            # Unified Personal XP — the single XP grant choke point
    squad_xp_service.py      # squad level + member-capacity enforcement
    manava_event_service.py  # the MANAVA event processing pipeline
    leaderboard_service.py   # global + per-squad leaderboard queries
    season_service.py        # start/end/new-season + transactional season reset
    application_service.py    # application state transitions (DB-pure, audited)
    application_actions.py    # application Discord side effects (roles, embed, DMs)
    account_linking.py        # verified/linked status — Gateway-backed or stub
    gateway_client.py         # HTTP client for the MANAVA Gateway (identity + webhook mgmt)
  web/
    webhook_server.py     # aiohttp MANAVA event receiver (POST /webhooks/manava), HMAC-verified
    polling.py              # REST-polling fallback, behind a config flag
  cogs/
    squads.py, admin.py, xp.py, seasons.py, applications.py, help.py
  ui/
    confirm_view.py, paginated_view.py
    squad_apply_view.py            # persistent squad join-request Approve/Reject
    application_apply_view.py      # applicant select+modal submission flow
    application_review_view.py     # persistent Approve/Reject/Request-More-Info
    application_moreinfo_view.py   # persistent applicant "Respond" button
    application_render.py          # review-embed rendering
  models/
    squad.py, xp.py, season.py, application.py, gateway.py
docs/
  schema.md, deployment.md, recovery.md, command-reference.md, logging.md,
  manava-gateway-integration.md, capacity-calculation.md, archive-model.md,
  known-limitations.md, deferred-items.md, qa-report.md
scripts/
  run_migrations.py
```

## Integration status & known stubs

- **MANAVA Gateway** (`docs/manava-gateway-integration.md`): the real contract
  is implemented behind a flag. Set `MANAVA_GATEWAY_BASE_URL` +
  `DISCORD_BACKEND_API_KEY` + `WEBHOOK_SIGNING_SECRET` for Gateway mode —
  identity lookups populate `verified_player` / `manava_user_id`, and inbound
  event webhooks are verified by HMAC `x-manava-signature`. Without them the
  bot runs in **stub mode**: `verified_player` and `manava_user_id` come from
  `/admin set-verified` and `/admin link-manava-account` (kept as support
  fallbacks in Gateway mode too), and the webhook uses the legacy
  `MANAVA_WEBHOOK_SECRET` bearer token. `/xpconfig simulate-manava-event`
  exercises the full pipeline either way. Client still owes the real key
  values.
- The REST-polling fallback (`src/web/polling.py`) is structurally complete
  but untested — the Gateway pushes webhooks, so this is a dormant fallback
  transport.
- The Discord text-XP 60-second cooldown is tracked in-memory, not
  DB-persisted — resets on bot restart (acceptable tradeoff, not a bug).
- Persistent views (application review buttons, squad join-request
  Approve/Reject, applicant "Respond" button) survive a restart — registered
  in `setup_hook`, state carried in `custom_id` / resolved from the DB.

See `docs/` (listed in Layout above) for schema, deployment, recovery,
command reference, logging, the Gateway contract, QA report, and the
known-limitations / deferred-items lists.
