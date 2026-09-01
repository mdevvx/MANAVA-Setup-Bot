# MANAVA Gateway integration

Verified against MANAVA's Gateway source (`backend-gateway`, NestJS + Prisma) —
`docs/events.md`, `docs/identity-check.md`, `docs/bot-webhooks.md`,
`core/hmac/hmac-signer.ts`, `core/guards/*`, `events/*`.

- **demo**: `https://discord-server-backend-gateway-demo.manava.io` (their `dev` branch)
- **prod**: `https://discord-server-backend-gateway.manava.io` (their `v*` tags)

There are exactly **two** contact points. Discord ⇄ MANAVA account **linking**
happens in the main MANAVA frontend — the Gateway and this bot only *read* link
status; neither talks to Discord's account-linking flow.

## Turning it on

Gateway mode is active only when **both** `MANAVA_GATEWAY_BASE_URL` and
`DISCORD_BACKEND_API_KEY` are set (`config.gateway_enabled`).

| Env var | Purpose |
|---|---|
| `MANAVA_GATEWAY_BASE_URL` | `…-gateway-demo.manava.io` for demo, `…-gateway.manava.io` for prod. No trailing slash needed. |
| `DISCORD_BACKEND_API_KEY` | sent as `x-api-key` on the identity call. Per the Gateway's guards this key opens **only** the identity endpoint. |
| `WEBHOOK_SIGNING_SECRET` | HMAC-SHA256 key to verify `x-manava-signature` on inbound events. If set, supersedes the legacy `MANAVA_WEBHOOK_SECRET`. |

With none set, the bot runs in **stub mode**: verified-player status and
`manava_user_id` come from `/admin set-verified` + `/admin
link-manava-account`; the webhook endpoint returns `503` (but `/healthz` stays
up).

## Channel 1 — bot → Gateway: identity lookup

```
GET  {MANAVA_GATEWAY_BASE_URL}/internal/identity/:discordId
     header  x-api-key: <DISCORD_BACKEND_API_KEY>
```

```json
{ "linked": true, "manavaUserId": "65a1f8c9e4b0d2f3a1234567", "verifiedPlayer": true }
```

- `linked` — Discord account connected to a MANAVA account. Unknown Discord id
  → `{ "linked": false, "manavaUserId": null, "verifiedPlayer": false }` (still
  HTTP 200). A non-2xx means the Gateway or its `marketing-api` upstream is
  down.
- `manavaUserId` — MANAVA player id; every event about the player carries it.
- `verifiedPlayer` — the player has confirmed their email.

**Where it's used** — `src/services/account_linking.py`:
`link_state(conn, discord_user_id, gateway=…)` calls the Gateway, caches
`manavaUserId` + `verifiedPlayer` into `personal_xp`, and returns `OK` /
`NOT_LINKED` / `NOT_VERIFIED`. On any Gateway error it logs and falls back to
the cached `personal_xp.verified_player` (reported as `NOT_VERIFIED` when
false, since stub mode can't tell the two failure cases apart).
`squad_eligibility.check_eligibility` uses this to show the applicant the right
message ("link your account" vs "confirm your email"). Staff can force a
re-fetch with `/admin gateway refresh-identity <user>`.

## Channel 2 — Gateway → bot: event webhooks

```
POST  https://<this-deployment>/webhooks/manava
      header  x-manava-signature: sha256=<hex>
      header  x-manava-event-id: <eventId>          (convenience dedup hint)
      header  Content-Type: application/json
```

`x-manava-signature` = `"sha256=" + HMAC_SHA256(raw_request_body,
WEBHOOK_SIGNING_SECRET)`, lowercase hex — matching the Gateway's
`hmac-signer.ts` byte-for-byte. Verified in `src/web/webhook_server.py`
against the **raw** body bytes *before* JSON parsing, with `hmac.compare_digest`
(`test_gateway_signature.py::test_matches_gateway_signpayload_wire_format`
locks in wire compatibility). Bad/missing signature → `401`.

Three event types (camelCase payloads):

| `eventType` | Fields (besides `eventId`, `eventType`, `manavaUserId`, `game`, `timestamp`) | XP granted |
|---|---|---|
| `match_completed` | `matchId` | `skill_match_xp` |
| `tournament_registered` | `tournamentId` | `tournament_participation_xp` |
| `tournament_placement` | `tournamentId`, `place` (int, 1-based), `wonPrizeSlot` (bool) | `tournament_participation_xp` + placement bonus (`placement_reward_1/2/3` for `place` 1/2/3) + `prize_slot_bonus_xp` if `wonPrizeSlot` |

`game` is one of `cs2` / `swag` / `billiard` (the bot stores whatever it's
sent, no gate). `prize_slot_bonus_xp` is seeded to **0** (migration `0007`), so
`wonPrizeSlot` changes nothing until an admin sets it via `/xpconfig set-xp`.

`manava_event_service.parse_event` accepts the camelCase Gateway keys *and* the
pre-Gateway snake_case keys, normalising the old event-type names
(`skill_match_completed` → `match_completed`, `tournament_participated` →
`tournament_registered`) via `constants.MANAVA_EVENT_TYPE_ALIASES`, so the
`/xpconfig simulate-manava-event` harness still works.

### Retry / dedup (matches the Gateway's outbox)

- The Gateway retries any **non-2xx** response: attempt 1 immediate, then 5s,
  10s, 20s, … doubling, **up to 10 attempts** (~42 min before the last), then
  the event is dead-lettered. 10s per-delivery timeout.
- Our responses: **200** for `processed` / `duplicate` / `unresolved_user`
  (all "accounted for" — no retry wanted); **503** for a transient DB error
  (retry — the event lands on a later attempt once the DB recovers); **400**
  for a malformed body (the Gateway's DTO validation should make this
  impossible; a 400 will retry then dead-letter, surfacing the bug).
- Redeliveries are expected whenever our ack is lost in transit. `eventId` is
  reserved in `processed_events` *before* any XP is computed, so a redelivery
  is a guaranteed no-op (`test_manava_event_dedup.py`).
- If MANAVA is fully down, nothing to do on our side — their outbox drains when
  they recover, with retry semantics intact.

### Processing pipeline

authenticate → parse/validate → `processed_events` reserve → resolve Discord
user from `manavaUserId` (cached mapping) → compute XP → grant (Personal
Lifetime+Season, and Squad Lifetime+Season if in a squad) → finalize
`processed_events` → audit log.

An event for a `manavaUserId` the bot has never resolved (no cached mapping) is
recorded as `unresolved_user` and grants no XP — acceptable for launch (see
`known-limitations.md`). The mapping fills in whenever that user hits the squad
gate or a `/admin gateway refresh-identity`.

## Webhook registration — MANAVA-side

`POST/GET/DELETE /internal/bot-webhooks` on the Gateway are guarded by
MANAVA's `INTERNAL_SERVICE_KEY`, **not** `DISCORD_BACKEND_API_KEY`. The bot
backend does not hold that key, so there is no bot command for this. MANAVA
registers this deployment's `https://<host>/webhooks/manava` URL on their side:

```
POST /internal/bot-webhooks
x-api-key: <INTERNAL_SERVICE_KEY>
{ "url": "https://<this-deployment>/webhooks/manava" }
```

To change the URL they delete and re-create (no update endpoint). A webhook
only receives events emitted after it was registered.

## What the bot never receives

Email / phone / real name, balances / transactions / NAVA, KYC data,
tournament buy-in or prize amounts, match statistics, Discord IDs of accounts
not linked to MANAVA, or any historical (pre-registration) events.

## Still outstanding

- Real `DISCORD_BACKEND_API_KEY` + `WEBHOOK_SIGNING_SECRET` in the deploy env
  (from Sergey).
- MANAVA registers the prod `/webhooks/manava` URL once the VPS host is known.
- End-to-end run against the demo Gateway.
