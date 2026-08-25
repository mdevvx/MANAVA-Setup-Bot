# Squad disband / archive model

## The requirement

On disband, the spec asks for two things that are slightly in tension:

1. A squad's Discord channels stay alive for a 30-day archive window before
   being physically deleted (presumably to let staff review activity,
   recover from an accidental disband, etc.).
2. Access must be revoked *immediately* on disband, not after 30 days.
3. The 70-active-squad capacity target (see `capacity-calculation.md`) has to
   hold even while squads are sitting in that 30-day window.

Keeping 40 live, fully-permissioned channels around per disbanded squad for a
month, on top of the 70-active-squad load, would eat into the channel
headroom fast under any real churn.

## What's implemented instead

**Immediate, on disband (`squad_lifecycle.disband_squad`):**

- DB: `squads.status` flips to `'disbanded'`, `disbanded_at` and
  `archive_purge_after` (= now + `SQUAD_ARCHIVE_DAYS`, default 30) are set,
  every active `squad_memberships` row is closed (`left_at = now()`), and the
  squad drops out of every "active squad" query — including the leaderboard,
  once that exists in Phase 2.
- Discord: the squad's unique role is deleted outright (this alone removes
  everyone's access to Member Text/Voice, since that role is the only thing
  gating those channels). The Officer Text/Voice channels' individual
  member-ID overwrites (Leader + Officers) are explicitly cleared too, since
  those don't depend on the role.
- The channels themselves are **not** deleted yet — they're left in place,
  inaccessible to everyone except staff (whose access is a role-based
  overwrite on the channel itself, untouched by this).

**After the 30-day window (`ManavaBot.purge_archived_squads`, a daily
background task):**

- Queries `squads` for rows where `status = 'disbanded'`,
  `archive_purge_after <= now()`, and `discord_objects_purged_at is null`.
- Deletes the 4 leftover channels (and the role, if it somehow still exists)
  via `provisioning.teardown_squad_discord_objects`.
- Stamps `discord_objects_purged_at` so the purge never re-runs for that
  squad.

## Why this satisfies both requirements

- Access revocation is immediate (role deletion + overwrite clearing happens
  synchronously as part of the disband command, not on a delay).
- The squad record, XP history, and audit trail are never deleted — only the
  four Discord channel objects and the role, both of which are cheap to
  recreate if ever needed and carry no data of their own.
- The channel-count risk from the tension above is gone: an inaccessible,
  role-stripped channel costs the same toward Discord's 500-channel guild
  limit as a fully active one, but it costs **nothing** in terms of exposure
  — nobody but staff can see it during the 30-day wait. The capacity math in
  `capacity-calculation.md` already reserves headroom for this (~26 squads'
  worth of channels can sit in this state simultaneously before the purge
  job needs to catch up).
- The squad's name stays permanently reserved the entire time (and forever
  after), because `squads` rows are never hard-deleted and the
  `name_lower` unique index applies across every status.
