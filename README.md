# MANAVA Multiverse Bot

Custom Discord bot for the MANAVA Multiverse server:

- **Squads** — create / join / manage esports teams, each with its own role and
  four channels, distributed across the `⚔️〔SQUADS 0N〕` categories.
- **Unified XP economy** — one canonical Personal XP balance (Discord text
  activity + MANAVA gameplay events), Lifetime + Season counters, 1:1 cascade
  into Squad XP, level-based member caps.
- **Leaderboards** — global squad leaderboard (by Season XP, top-32 badge) and
  per-squad member leaderboard, rendered natively.
- **Applications** — Developer and Creator/Streamer review workflows with
  persistent Approve / Reject / Request-More-Info buttons.
- **Seasons** — manual Start / End / Start-New (resets Season XP, keeps
  Lifetime).
- **MANAVA Gateway integration** — identity lookup + HMAC-signed inbound event
  webhooks (`docs/manava-gateway-integration.md`).

Python 3.11+ / discord.py 2.x / Supabase Postgres via `asyncpg`. **89 unit
tests, `mypy src` clean.**

---

## Quick start (local)

```bash
python -m pip install -r requirements-dev.txt   # or requirements.txt for prod-only
cp .env.example .env                             # fill in real values (see below)
python -m scripts.run_migrations                 # apply DB schema (idempotent)
python -m src.main                               # run the bot
```

Then in Discord, run **`!sync`** (prefix message command, Admin / MANAVA Team) —
re-registers slash commands, re-checks required roles/categories, re-applies
SQUADS category permissions, re-creates the application roles + channel, and
refreshes the config cache. Run it any time server objects change; no restart
needed.

`/admin status` shows the full runtime configuration and live counts at a glance.

## Environment variables

Full table with descriptions: **`docs/deployment.md`**. Essentials:

| Variable | Required | Notes |
|---|---|---|
| `DISCORD_BOT_TOKEN` | ✅ | Needs the **Server Members** + **Message Content** privileged intents. |
| `DISCORD_GUILD_ID` | ✅ | The MANAVA Multiverse server id. |
| `DATABASE_URL` | ✅ | Supabase **session pooler** URI (port 5432, `aws-0-<region>.pooler.supabase.com`). Not the REST URL, not the IPv6-only `db.<ref>.supabase.co` host. |
| `MANAVA_GATEWAY_BASE_URL` + `DISCORD_BACKEND_API_KEY` | Gateway mode | Set both to turn on Gateway mode (real identity lookups). |
| `WEBHOOK_SIGNING_SECRET` | Gateway mode | HMAC-SHA256 key verifying `x-manava-signature` on inbound events. |
| `MANAVA_LINK_URL` | | The MANAVA site where members link their account — shown in the squad-gate message. |
| `MANAVA_WEBHOOK_SECRET` | | DEPRECATED legacy bearer webhook auth; used only if `WEBHOOK_SIGNING_SECRET` is unset. |
| `PORT` | | Webhook/health port; default 8080. |
| `LOG_LEVEL`, `SQUAD_ARCHIVE_DAYS` | | defaults `INFO`, `30`. |

**Secrets live only in the environment.** `.env` is gitignored; `.env.example`
holds placeholders only.

**Stub mode** (Gateway vars unset): `verified_player` / `manava_user_id` come
from `/admin set-verified` + `/admin link-manava-account`; the webhook uses the
legacy bearer token (or the event endpoint returns 503 while `/healthz` stays
up). `/xpconfig simulate-manava-event` exercises the full event pipeline either
way.

## Required Discord setup

Resolved by name (case-insensitive) at startup; squad features disable
themselves if any are missing.

- **Roles** (already on the server): `Admin`, `MANAVA Team`, `Senior Moderator`,
  `Moderator`, `Squad Leader`, `Squad Officer`, `Squad Member`, `Member`.
- **Categories** (created manually by staff, exact names): `⚔️〔SQUADS 01〕` …
  `⚔️〔SQUADS 07〕`.
- **Auto-created by the bot** (needs Manage Roles + Manage Channels): the roles
  `Developer Pending`, `Developer`, `Creator`, `Streamer`, and the
  `#applications-review` channel (locked to Admin + MANAVA Team; Moderator /
  Senior Moderator explicitly denied).

The bot's own role must sit **above** the squad/application roles it assigns.
Slash-command groups `/admin`, `/xpconfig`, `/season` are hidden in the picker
from anyone without the Discord **Administrator** permission (a non-Administrator
`MANAVA Team` role can be allowed once under Server Settings → Integrations).

## Operating notes

| Task | How |
|---|---|
| See config + live status | `/admin status` |
| Re-sync after changing roles/channels | `!sync` |
| Recover an accidentally disbanded squad | `/admin restore-squad squad_name:…` (within the 30-day window) |
| Route an application type to a custom channel | `/admin set-application-channel application_type:… [channel]` |
| Point members at MANAVA linking | set `MANAVA_LINK_URL` |
| Test the MANAVA pipeline without the Gateway | `/xpconfig simulate-manava-event …` |
| Recover from Discord ↔ DB drift | `docs/recovery.md` |

## Documentation (handover package)

| File | Contents |
|---|---|
| `docs/command-reference.md` | Every slash / message command, what it does, who can run it |
| `docs/schema.md` | Every table, columns, relationships, migration list, the `discord_bot` schema isolation |
| `docs/deployment.md` | Runtime contract for CI/CD, full env-var table, container, first-time Discord setup, restart procedure |
| `docs/recovery.md` | Discord ↔ Supabase drift recovery (deleted channels/roles, lost leadership, stuck archive, disband recovery, Gateway cache staleness, outages) |
| `docs/manava-gateway-integration.md` | The MANAVA Gateway contract, verified against their source: identity endpoint, HMAC event webhooks, retry/dedup semantics, what's MANAVA-side |
| `docs/logging.md` | What is logged where; `audit_logs` action list; PII handling rules |
| `docs/capacity-calculation.md` | Discord object footprint per squad, the 70-active-squad ceiling |
| `docs/archive-model.md` | Why disbanded squads keep inaccessible channels for 30 days, then purge |
| `docs/known-limitations.md` | Things that work as designed but a maintainer should know |
| `docs/deferred-items.md` | Explicitly out-of-scope items + deferred work + stubs awaiting external input |
| `docs/qa-report.md` + `docs/MANAVA-Bot-QA-Handover.pdf` | Acceptance checklist mapped to tests; the PDF is the formatted client handover (results, evidence inventory, live-server checklist, sign-off) |
| `docs/manava-webhook-contract.md` | Superseded — historical record of the pre-Gateway stub |

## Deployment

MANAVA's DevOps runs CI/CD in GitLab and deploys to a MANAVA VPS (not Railway).
`docs/deployment.md` is the **runtime contract**: one process
(`python -m src.main`, one instance), all config via env, container from
`./Dockerfile` (which does **not** run migrations — the pipeline runs
`python -m scripts.run_migrations` per release), `/healthz` on `$PORT`.
`.gitlab-ci.yml` carries a quality gate (pytest + mypy); build/deploy stages are
DevOps's.

All bot tables live in a dedicated **`discord_bot`** Postgres schema (migration
`0008`) because the database is shared with other MANAVA services.

## Layout

```
src/
  config.py  constants.py  errors.py  bot.py  main.py
  db/
    pool.py  retry.py  migrations/0001…0009.sql  repositories/   # asyncpg data access
  discord_state/
    role_resolver.py       # name-lookup + cache of required roles/categories
    applications_setup.py   # resolve/CREATE application roles + #applications-review
    capacity.py             # SQUADS category assignment
    provisioning.py         # channel/role creation, overwrites, teardown, disband/restore
    role_safety.py          # single choke point for granting roles (protected-role deny-list)
    xp_channel_filter.py    # which channels grant Discord text XP + cooldown check
    staff_check.py          # shared Admin/MANAVA Team permission check
  services/
    squad_eligibility.py  squad_lifecycle.py  squad_membership.py
    xp_service.py            # Unified Personal XP — the single grant choke point
    squad_xp_service.py      # squad level + member-capacity enforcement
    manava_event_service.py  # the MANAVA event processing pipeline
    leaderboard_service.py   # global + per-squad leaderboard queries
    season_service.py        # start/end/new-season + transactional season reset
    application_service.py    # application state transitions (DB-pure, audited)
    application_actions.py    # application Discord side effects (roles, embed, DMs)
    account_linking.py        # linked/verified status — Gateway-backed or stub
    gateway_client.py         # HTTP client for the MANAVA Gateway (identity lookup)
  web/
    webhook_server.py     # aiohttp event receiver (POST /webhooks/manava), HMAC-verified, /healthz
    polling.py              # dormant REST-polling fallback, behind a config flag
  cogs/
    squads.py  admin.py  xp.py  seasons.py  applications.py  help.py
  ui/
    confirm_view.py  paginated_view.py
    squad_apply_view.py            # persistent squad join-request Approve/Reject
    application_apply_view.py      # applicant select+modal submission flow
    application_review_view.py     # persistent Approve/Reject/Request-More-Info
    application_moreinfo_view.py   # persistent applicant "Respond" button
    application_render.py          # review-embed rendering
  models/
    squad.py  xp.py  season.py  application.py  gateway.py
docs/            # handover documentation (table above)
scripts/run_migrations.py
Dockerfile  .dockerignore  .gitlab-ci.yml  mypy.ini  pytest.ini
```

## Tests

```bash
pytest              # 89 tests
mypy src            # clean
```

Unit-level: service logic, permission-overwrite construction, event
parsing/dedup, HMAC signature verification, cross-squad isolation, disband
cleanup + recovery, application flows/cooldown/permissions, season reset,
protected-role guard. Mocked repositories / Discord objects — no live DB or
gateway connection. `docs/qa-report.md` maps every acceptance-test item to its
coverage and lists the manual (live-server) checklist.

## Known stubs / outstanding

- **Gateway credentials** — `DISCORD_BACKEND_API_KEY` + `WEBHOOK_SIGNING_SECRET`
  come from MANAVA; until set, the bot runs in stub mode.
- **MANAVA registers the bot's `/webhooks/manava` URL** on their side (guarded by
  their internal key — not something the bot does).
- **`prize_slot_bonus_xp`** defaults to `0` (so `wonPrizeSlot` is inert) until an
  admin sets it via `/xpconfig set-xp`.
- **Live end-to-end QA** on a staging guild — checklist in `docs/qa-report.md`.
- Full list: `docs/known-limitations.md`, `docs/deferred-items.md`.
