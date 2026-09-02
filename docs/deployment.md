# Deployment

Deployment (CI/CD + VPS) is owned by MANAVA's DevOps. This document is the
**runtime contract** their pipeline needs, plus the one-time Discord/server
setup that only someone with server admin can do.

## Runtime contract

- **One process, one instance.** `python -m src.main` runs the Discord gateway
  client and the aiohttp MANAVA webhook receiver together, listening on
  `$PORT` (default `8080`). No workers, no cron, no local file writes. Running
  two instances against the same bot token would double-process — there is no
  leader election.
- **Python 3.11+** (the image pins 3.12).
- **All configuration via environment variables** (table below). Secrets never
  live in source, in `bot_config`, or in Discord messages.
- **Container**: build from `./Dockerfile`. It does *not* run migrations.
- **Health check**: `GET /healthz` on `$PORT` (no auth), always available even
  before the Gateway is configured. The Dockerfile wires this as a
  `HEALTHCHECK`.
- **Stateless** apart from two in-memory caches rebuilt on boot (the 60s
  text-XP cooldown map; the resolved roles/categories/application state).
  Persistent views are re-registered on boot and keep working on messages sent
  before a restart.

### What the pipeline must do, per release

1. Build the image from `./Dockerfile`.
2. Run **`python -m scripts.run_migrations`** against the target database
   (idempotent, safe to re-run; needs `DATABASE_URL` in the job env). Do this
   before starting the new container.
3. Run the container (`CMD` is already `python -m src.main`).
4. Ensure only one replica.

`.gitlab-ci.yml` in the repo defines a `quality` stage (pytest + mypy) only —
build/migrate/deploy stages are for DevOps to add.

## Environment variables

| Variable | Required | Purpose |
|---|---|---|
| `DISCORD_BOT_TOKEN` | ✅ | Bot token. Needs the **Server Members** and **Message Content** privileged intents enabled in the Developer Portal. |
| `DISCORD_GUILD_ID` | ✅ | The MANAVA Multiverse server id. |
| `DATABASE_URL` | ✅ | Postgres connection string. On Supabase use the **session pooler** URI (port 5432, `aws-0-<region>.pooler.supabase.com`) — not the REST URL, not the IPv6-only `db.<ref>.supabase.co` host. Percent-encode special chars in the password. |
| `PORT` | | webhook/health port. Default `8080`. Most platforms inject this. |
| `LOG_LEVEL` | | default `INFO` |
| `SQUAD_ARCHIVE_DAYS` | | default `30` |
| `MANAVA_GATEWAY_BASE_URL` | Gateway mode | e.g. `https://discord-server-backend-gateway-demo.manava.io` |
| `DISCORD_BACKEND_API_KEY` | Gateway mode | `x-api-key` sent on bot → Gateway calls (identity + webhook management) |
| `WEBHOOK_SIGNING_SECRET` | Gateway mode | HMAC-SHA256 key that verifies `x-manava-signature` on inbound events |
| `MANAVA_LINK_URL` | | Public URL of MANAVA's account/connections page. Shown to members who fail the squad gate for not being linked/verified. Optional — messages fall back to generic wording. |
| `MANAVA_WEBHOOK_SECRET` | | DEPRECATED legacy bearer-token webhook auth; used only when `WEBHOOK_SIGNING_SECRET` is unset |
| `MANAVA_POLL_URL` / `MANAVA_POLL_API_KEY` / `MANAVA_POLL_INTERVAL_SECONDS` | | dormant REST-polling fallback transport (only if `bot_config.manava_integration_mode = "polling"`) |

"Gateway mode" turns on only when **both** `MANAVA_GATEWAY_BASE_URL` and
`DISCORD_BACKEND_API_KEY` are set. Without them the bot runs in stub mode
(manual `/admin set-verified` + `/admin link-manava-account`; legacy or
disabled webhook auth). The event endpoint returns `503` until a webhook
secret is configured; `/healthz` is up regardless. See
`manava-gateway-integration.md`.

`.env.example` lists every variable with placeholders. **Reconcile the exact
names with the set MANAVA provided (Sergey) before first deploy.**

## Database schema

All bot tables live in a dedicated **`discord_bot`** Postgres schema (migration
`0008`) — the database is shared with other MANAVA services, so nothing goes in
`public`. The app pool and the migration runner both connect with
`search_path = discord_bot, public`; no manual schema setup is needed, just run
`python -m scripts.run_migrations`.

## One-time Discord / server setup

1. **Discord app**: enable the **Server Members** and **Message Content**
   privileged intents. Invite the bot with scopes `bot` +
   `applications.commands` and permissions: Manage Roles, Manage Channels, Send
   Messages, Read Message History, Embed Links. Move the bot's role **above**
   `Squad Leader/Officer/Member`, the per-squad roles, and the four application
   roles so it can assign them.
2. **Server objects** (exact names in `README.md`): the 8 roles (`Admin`,
   `MANAVA Team`, `Senior Moderator`, `Moderator`, `Squad Leader`,
   `Squad Officer`, `Squad Member`, `Member`) and the 7 `⚔️〔SQUADS 0N〕`
   categories must exist. The 4 application roles (`Developer Pending`,
   `Developer`, `Creator`, `Streamer`) and `#applications-review` are
   **auto-created** by the bot on first boot / `!sync`.
3. After first deploy, run **`!sync`** in Discord (message command, Admin /
   MANAVA Team) to register slash commands and re-check
   roles/categories/permissions.
4. **Gateway**: set `MANAVA_GATEWAY_BASE_URL` + `DISCORD_BACKEND_API_KEY` +
   `WEBHOOK_SIGNING_SECRET`, then give MANAVA the public URL
   `https://<host>/webhooks/manava` so they can register it on the Gateway
   (their side — the bot can't self-register). `manava-gateway-integration.md`
   has the details.

## Restart

Just restart the process/container. On boot the bot re-resolves guild state,
re-creates any missing application objects, restarts the archived-squad purge
loop, and starts the webhook server. Run `!sync` afterwards only if a
role/category changed or slash commands look stale. No migration is needed for
a plain restart — only after new migration files land.

## Recovery

`recovery.md` covers Discord ↔ database drift: manually deleted
channels/roles, lost leadership, a stuck archive, duplicate-name collisions,
and a stale Gateway identity cache.

## Reference — running it directly on a VPS (no container)

Not the intended path (DevOps uses the container), but for a manual bring-up:

```ini
# /etc/systemd/system/manava-bot.service
[Unit]
Description=MANAVA Multiverse Discord bot
After=network-online.target

[Service]
WorkingDirectory=/opt/manava-bot
EnvironmentFile=/opt/manava-bot/.env
ExecStart=/opt/manava-bot/.venv/bin/python -m src.main
Restart=always
RestartSec=5
User=manava

[Install]
WantedBy=multi-user.target
```

Deploy = `git pull` → `pip install -r requirements.txt` →
`python -m scripts.run_migrations` → `systemctl restart manava-bot`.

**Webhook exposure**: terminate TLS at a reverse proxy
(`https://<host>/webhooks/manava`) forwarding to `127.0.0.1:$PORT`. The bot
verifies the HMAC signature itself over the raw body, so the proxy must pass
the body and headers through unmodified (no rebuffering that alters bytes).
