# Logging & audit

Two layers:

1. **Application log** — Python `logging`, `LOG_LEVEL` (default `INFO`), stdout
   in the format `%(asctime)s %(levelname)s %(name)s: %(message)s`. Operational
   detail; goes to the platform's log aggregation. `discord.client` is pinned
   to `ERROR` to silence the harmless "voice not supported" startup noise.
2. **Audit trail** — the `audit_logs` table (`src/db/repositories/audit_logs.py`).
   Every administrative / lifecycle change, queryable, permanent.

## What lands in `audit_logs`

Each row: `actor_id`, `action` (dotted string), `target_type`, `target_id`,
`old_value` / `new_value` (jsonb), `reason`, `created_at`.

| Area | `action` values |
|---|---|
| Squad lifecycle | `squad.create`, `squad.disband` |
| Membership | `squad.join_request.submit` / `.approve` / `.reject`, `squad.member.invite` / `.leave` / `.remove` / `.promote` / `.demote`, `squad.leadership.transfer` |
| Seasons | `season.start`, `season.end`, `season.start_new` (with reset counts) |
| MANAVA events | `manava_event.processed` (event type, xp granted, game) |
| Applications | `application.submit`, `application.approve`, `application.reject` (with reason), `application.request_more_info` |
| XP / config admin | `admin.add_xp` (old/new lifetime, amount, reason), `admin.set_verified`, `admin.link_manava_account`, `xpconfig.set_xp`, `xpconfig.set_threshold`, `xpconfig.exclude_channel` |
| Gateway | `manava_event.processed` (see above); identity re-fetches log at INFO, not audited |

`squad_status_history` and `application_history` are additional append-only
trails specific to those flows.

## PII rules

- Application `fields` (contact email, etc.) are **never** written to
  `audit_logs` — application audit rows carry only `application_id`, status
  transition, actor, and (for rejects) the reviewer's reason.
  `application_service._audit_public_view` is the single place that decides
  what's safe.
- Application `fields` and `application_history.note` (which can contain the
  applicant's own free-text reply) only ever leave the DB inside the private
  `#applications-review` flow — the review embed (staff-only channel) and the
  applicant's own DMs. Never a public channel, never the application log.
- The MANAVA Gateway never sends the bot email/phone/name/financial/KYC data,
  so none can be logged.
- Secrets (tokens, API keys, signing secret) are read from the environment
  and never logged, echoed to Discord, or stored in `bot_config`.

## Errors

- User-facing errors are always friendly plain text (`BotUserError` subclasses).
  Anything else is caught by the tree / view / modal error handlers, logged
  with a full traceback, and shown to the user only as a generic message —
  never a stack trace, file path, or token.
- Transient DB errors during webhook processing are logged and answered with
  `503` so the Gateway re-delivers.
- Failed applicant DMs (DMs closed) are logged at `WARNING` and surfaced to the
  acting reviewer ("⚠️ Couldn't DM the applicant"), not treated as failures.
