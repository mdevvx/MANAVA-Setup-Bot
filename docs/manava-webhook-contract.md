# MANAVA webhook contract (current STUB, pending MANAVA's real contract)

This documents what the bot currently expects. Everything here is a
placeholder until MANAVA provides their actual integration contract — the
intent is that swapping to the real thing is a config/auth change, not a
rewrite of the processing pipeline.

## Endpoint

```
POST https://<this-service>/webhooks/manava
```

Also exposes `GET /healthz` (no auth) for basic uptime checks.

## Authentication (STUB)

A single shared secret, set via the `MANAVA_WEBHOOK_SECRET` environment
variable. Every request must include it as a bearer token:

```
Authorization: Bearer <MANAVA_WEBHOOK_SECRET>
```

Requests with a missing or incorrect header get `401 Unauthorized`. If
`MANAVA_WEBHOOK_SECRET` isn't set at all, the webhook server doesn't start —
use `/xpconfig simulate-manava-event` to exercise the processing pipeline
without it.

**This will need to change** once MANAVA specifies their real scheme (HMAC
request signing, OAuth, mTLS, IP allowlisting, etc.) — only
`src/web/webhook_server.py`'s auth check needs to change, the rest of the
pipeline (`src/services/manava_event_service.py`) is auth-agnostic.

## Request body

JSON object, minimum fields:

| Field | Type | Required | Notes |
|---|---|---|---|
| `event_id` | string | yes | Must be globally unique per event. Retried/duplicate deliveries with the same `event_id` are guaranteed to never grant XP twice. |
| `manava_user_id` | string | yes | Looked up against `personal_xp.manava_user_id` to resolve a Discord user. If no user is linked yet, the event is recorded but grants no XP. |
| `event_type` | string | yes | One of `skill_match_completed`, `tournament_participated`, `tournament_placement`. |
| `game` | string | yes | |
| `timestamp` | string | yes | ISO-8601. |
| `match_id` | string | no | Nullable. |
| `tournament_id` | string | no | Nullable. |
| `result` | string | no | Nullable. |
| `placement` | integer | no | Nullable. Only affects XP for `tournament_placement` events — 1st/2nd/3rd get a configurable bonus on top of the base tournament XP; other placements just get the base amount. |

Example:

```json
{
  "event_id": "evt_8f2c1a",
  "manava_user_id": "manava-12345",
  "event_type": "tournament_placement",
  "game": "Ocean Masters",
  "timestamp": "2026-08-25T21:00:00Z",
  "match_id": null,
  "tournament_id": "trn_991",
  "result": "win",
  "placement": 1
}
```

## Response

- `200` — event accepted. Body: `{"event_id": ..., "status": "processed" | "duplicate" | "unresolved_user", "xp_granted": <int>}`. `duplicate` and `unresolved_user` are still 200s — the sender shouldn't retry either case.
- `400` — malformed payload (missing/invalid fields, unknown `event_type`). Body: `{"error": "<reason>"}`.
- `401` — auth failed.

## Fallback: REST polling

Behind a config flag (`bot_config.manava_integration_mode = "polling"`,
default is `"webhook"`), the bot can instead poll a MANAVA REST endpoint on
an interval (`MANAVA_POLL_URL`, `MANAVA_POLL_API_KEY`,
`MANAVA_POLL_INTERVAL_SECONDS`), expecting the same event shape as above
either as a bare JSON array or `{"events": [...]}`. This is structurally
complete but **untested** — no real MANAVA polling endpoint exists yet to
verify the response shape against.
