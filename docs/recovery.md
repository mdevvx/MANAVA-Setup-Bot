# Recovery procedures

For when Discord state and Supabase state drift apart. Supabase is the source
of truth for all bot-owned data; Discord objects are reconstructable.

## Bot won't start / crashes on boot

| Symptom (in logs) | Cause | Fix |
|---|---|---|
| `Configuration error: Missing required environment variable` | env var unset | set it, redeploy |
| `Missing required Discord roles/categories` | a required role/category was renamed or deleted | recreate it with the exact name (`README.md`), then `!sync` |
| gateway/DB connection errors on boot | wrong `DATABASE_URL` (used the direct host or REST URL) | use the **session pooler** URI, port 5432 |
| "PrivilegedIntentsRequired" | Message Content / Server Members intent off | enable both in the Developer Portal |

Squad features disable themselves (rather than crashing the whole bot) if guild
state can't be resolved; the applications feature disables itself independently.
Fix the underlying object and run `!sync`.

## A squad channel or role was manually deleted

The squad row still exists and points at dead Discord ids.

- **Officer/member channel deleted**: membership actions that touch it will
  raise a friendly "channel is missing — contact staff" error. Options: (a)
  recreate the channel manually and `UPDATE squads SET officer_text_channel_id
  = <new id> WHERE id = '<uuid>'`, or (b) disband the squad (`/squad disband`)
  and have the leader recreate it.
- **Squad role deleted**: members lose access to member channels. Recreate the
  role, `UPDATE squads SET role_id = <new id>`, and re-add the role to current
  members (query `squad_memberships WHERE squad_id = '<uuid>' AND left_at IS
  NULL`). Then run `!sync` to re-apply category baseline permissions.

## Lost leadership (a squad with no `leader` membership row)

Should be impossible (leave/transfer/disband all guard it), but to repair:

```sql
-- pick the new leader (e.g. an existing officer)
UPDATE squad_memberships SET squad_role = 'leader'
 WHERE squad_id = '<uuid>' AND discord_user_id = <user> AND left_at IS NULL;
UPDATE squads SET leader_user_id = <user> WHERE id = '<uuid>';
```

Then give that member the **Squad Leader** rank role and officer-channel
access in Discord (or have them run any leader command, which re-syncs rank).

## Recover an accidentally disbanded squad

While the squad is still inside its 30-day archive window (channels not yet
purged — `discord_objects_purged_at IS NULL`):

```
/admin restore-squad squad_name:<exact name>       (Admin / MANAVA Team)
```

This recreates the squad-specific role that was deleted at disband, flips the
record back to `active`, reopens every membership the disband closed, and
re-grants Discord access (member/officer channels + rank roles). The 4 channels
themselves were never deleted, so they come back with their content.

Not restored automatically:
- Former members who have since **joined another squad** (they'd break the
  one-squad-per-user rule) — the command reports these; they must leave the
  other squad, then be re-added with `/squad invite`.
- If the **former Leader** is now in another squad, the command refuses
  entirely until that's resolved.

Once `discord_objects_purged_at` is set (archive window elapsed, channels
gone), auto-restore is no longer possible — the name stays reserved forever;
rename the old row if it genuinely must be freed (see below).

## Archived squad stuck (Discord objects never purged)

The daily `purge_archived_squads` task deletes objects once
`archive_purge_after <= now()`. If the task hasn't run (bot was down) it
catches up on the next start. To force one squad now: delete its 4 channels +
role in Discord manually, then
`UPDATE squads SET discord_objects_purged_at = now() WHERE id = '<uuid>'`.

## Duplicate squad name rejected but no visible squad

Names are reserved **forever**, including for disbanded/archived squads
(`squads` rows are never deleted). This is intended. If a name genuinely must
be freed (support decision), rename the old row:
`UPDATE squads SET name = name || ' (archived 2026)' WHERE id = '<uuid>'`.

## XP looks wrong

- **Double-granted from a MANAVA event**: check `processed_events` for the
  `event_id` — if present with `xp_granted > 0` once, the dedup worked. The
  pipeline reserves `event_id` before granting, so a true double-grant would
  be a bug — capture the event payload and `audit_logs` rows and report it.
- **Season XP didn't reset**: confirm `/season new` (not `/season start`) was
  run; check the `season.start_new` audit row for the reset counts.
- **Manual correction**: `/admin add-xp` (grants only; no negative). To reduce
  XP, do it directly in `personal_xp` and add an `audit_logs` row by hand
  noting the actor and reason.

## Gateway / identity cache is stale

`personal_xp.verified_player` / `manava_user_id` are cached from the Gateway on
lookup. If a player's MANAVA status changed and the bot hasn't re-queried:
`/admin gateway refresh-identity user:<@user>`. In stub mode, use
`/admin set-verified` / `/admin link-manava-account`.

## Supabase outage

- The bot keeps running; commands that hit the DB fail with a friendly error
  until it recovers. No restart needed.
- Inbound MANAVA webhooks return `503` during the outage; the Gateway
  re-delivers, and dedup makes the retry safe.
- Discord text-XP grants during the outage are lost (best-effort, logged) —
  acceptable, not corrective.

## Discord API rate limits

discord.py handles 429s automatically (queues and retries). Bulk operations
(e.g. mass role changes) may just be slow. No action needed.

## Full re-sync

`!sync` is the catch-all: re-registers slash commands, re-resolves
roles/categories, re-applies SQUADS category permissions, re-creates missing
application objects, refreshes caches. Safe to run anytime.
