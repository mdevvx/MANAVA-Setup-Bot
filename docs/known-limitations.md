# Known limitations

Things that work as designed but a maintainer should be aware of.

## MANAVA Gateway

- **Event → Discord user resolution needs a warm cache.** Inbound events are
  keyed by `manavaUserId`. The bot resolves that to a Discord user via
  `personal_xp.manava_user_id`, which is populated only when the bot has done
  an identity lookup for that user (squad-creation gate, `/admin gateway
  refresh-identity`). An event for a player the bot has never looked up is
  recorded as `unresolved_user` and grants no XP. Mitigation options for
  later: a periodic sweep calling identity for all guild members, or an
  identity call on first message from a member.
- **`prize_slot_bonus_xp` defaults to 0**, so `wonPrizeSlot` currently changes
  nothing. Hunter needs to decide the value and set it via `/xpconfig set-xp`.
- **Webhook registration is MANAVA-side.** Their `/internal/bot-webhooks`
  endpoints are guarded by `INTERNAL_SERVICE_KEY`, which the bot doesn't hold —
  MANAVA registers this deployment's `/webhooks/manava` URL. If the URL
  changes (e.g. new host), they must re-register.
- **A malformed authenticated event → `400`**, which the Gateway retries 10×
  then dead-letters. Their DTO validation should make this impossible; the
  400 surfaces a Gateway bug rather than silently accepting garbage.
- **Real credentials pending.** `DISCORD_BACKEND_API_KEY` and
  `WEBHOOK_SIGNING_SECRET` come from MANAVA. Until then the bot runs in stub
  mode.

## Applications

- **Modal field split.** Discord caps a modal at 5 inputs and a message at 5
  action rows, so each application is a 3-step flow (select menus → 5-field
  modal → optional comments). The "Additional Comments" field is always the
  optional follow-up step.
- **Field validation is format-only, and post-submit.** Discord modals can't
  validate inline or disable their Submit button, so `contact_email` (`x@y.z`)
  and the website/profile URL (`http(s)://host.tld`) are checked *after*
  Submit. A bad value blocks the application and shows a **Fix & resubmit**
  button that reopens the modal pre-filled. No deliverability / reachability
  checks — that's the reviewer's call. `application_service.submit` re-checks
  server-side as the authoritative gate.
- **Unrecognised Profile Type grants no role.** If a Creator/Streamer
  application's `profile_type` isn't exactly `Creator` / `Streamer` / `Both`
  (only possible via manual DB edits — the form is a fixed dropdown), approval
  logs a warning and assigns nothing.
- **Review view resolves the application by message id.** If the
  `#applications-review` message is deleted, its buttons stop working; the
  application still exists and can be decided by editing `applications.status`
  directly (and assigning roles by hand) if needed.

## Seasons

- **No per-season history/snapshots.** A season reset zeroes the counters and
  records the reset (actor + row counts) in `audit_logs`, but final standings
  aren't snapshotted anywhere. Export the leaderboard before `/season new` if
  a record is wanted.
- **`contributed_xp` is not seasonal.** Per the spec it isn't reset by a
  season reset, so the member leaderboard's "contribution" column is
  lifetime-of-stint, not per-season.

## XP

- **Discord text-XP cooldown is in-memory.** The 60-second per-user cooldown
  resets on restart — a user could get one extra grant right after a redeploy.
  Accepted tradeoff.
- **No Voice XP** — explicitly out of scope.
- **Text-XP grants are best-effort during a DB outage** — logged and dropped,
  not queued.

## Squads

- **Capacity ceiling is 70 active squads** (7 categories × 10). See
  `capacity-calculation.md`. Creation past that fails with a friendly
  "at capacity, contact staff" message.
- **Archived squads keep their (inaccessible) channels for 30 days** before
  the purge job deletes them. See `archive-model.md`.

## Operational

- **Single instance only.** Running two bot processes against the same token
  would double-process. No leader election.
- **Deployment is owned by MANAVA DevOps** — CI/CD in GitLab, deployed to a
  MANAVA VPS. This repo provides the container (`Dockerfile`), a quality-gate
  `.gitlab-ci.yml`, and the runtime contract in `deployment.md`.
