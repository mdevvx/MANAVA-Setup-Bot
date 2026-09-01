# Deferred & out-of-scope items

## Explicitly out of scope (never to be built here)

Per the project brief — do not build any of this in this bot:

Paidia; tournament brackets / registration / check-in / seeding; the Ocean
Masters tournament flow; automatic Top-32 qualification or bracket sync; ELO
(player or team); game-specific leaderboards; competitive-team slots /
management; discipline-specific analytics; Voice XP; buy-in multiplier;
offline finals; founder/officer monetization; any integration with
guildmanager.app or scoreboards.dev; Featured-Creator anything (no role, no
automation — removed, not deferred).

## Deferred (sensible later work, intentionally not done now)

| Item | Notes |
|---|---|
| Proactive MANAVA identity cache warming | The `manavaUserId → Discord user` map is populated lazily (squad gate / `/admin gateway refresh-identity`). A periodic sweep or first-message hook would let events for never-looked-up players grant XP. Client confirmed lazy is fine for launch. See `known-limitations.md`. |
| DB-persisted Discord text-XP cooldown | In-memory today; resets on restart. |
| Season standings snapshots | No historical record of final leaderboard positions per season. |
| REST-polling ingestion (`src/web/polling.py`) | Structurally complete, behind `bot_config.manava_integration_mode = "polling"`, untested against a real endpoint. The Gateway pushes webhooks, so this stays a dormant fallback transport. |
| Reducing `#applications-review` fragility | Review buttons resolve the application from the message id; a deleted message orphans the buttons (recoverable via DB). |
| CI/CD build + deploy stages | `.gitlab-ci.yml` has the quality gate only; MANAVA DevOps owns build/migrate/deploy on their VPS. |

## Stubs still awaiting external input

| Stub | Unblocked by |
|---|---|
| Gateway mode credentials | MANAVA (Sergey) provided the env vars — wire `DISCORD_BACKEND_API_KEY` + `WEBHOOK_SIGNING_SECRET` into the deploy env |
| MANAVA registers the prod `/webhooks/manava` URL | done on their side once the VPS host is known |
| `prize_slot_bonus_xp` value | Hunter decides the XP amount (currently `0` = no effect) |
| Production Supabase + VPS access | MANAVA provisioning (≈next day per 2026-08-31 call) |
| End-to-end run against the demo Gateway | needs the keys in a running deployment |
