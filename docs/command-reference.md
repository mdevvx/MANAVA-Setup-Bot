# Command reference

"Elevated staff" = holds the **Admin** or **MANAVA Team** role (a real server
Administrator also passes, as a bootstrap fallback). Squad-scoped permissions
are checked against the caller's role *in that specific squad*.

The `/admin`, `/xpconfig`, and `/season` groups require the Discord
**Administrator** permission, so Discord hides them from everyone else in the
command picker (the runtime `require_elevated_staff` check is still the real
gate). To let a non-Administrator role such as **MANAVA Team** use them, a
server admin allows that role once under **Server Settings → Integrations →
MANAVA Setup Bot → Command Permissions**.

All slash-command replies are ephemeral unless noted.

Name parameters offer a live dropdown as you type: `/squad apply squad_name`
and `/leaderboard squad squad_name` suggest active squads; `/admin
restore-squad squad_name` suggests restorable (disbanded, un-purged) squads.
`/xpconfig set-xp key`, `set-threshold level`, and `simulate-manava-event
event_type` / `game` are fixed dropdowns.

## Squads — `/squad`

| Command | Who | What |
|---|---|---|
| `/squad create name:<3–32 chars>` | Everyone (gated) | Create a squad. Gates: has **Member** role, ≥1500 Personal Lifetime XP, Verified Player, not already in/owning an active squad, valid & unique name. Provisions the squad role + 4 channels in a `SQUADS 0N` category. |
| `/squad apply squad_name:<name>` | Everyone | Request to join. The squad's Leader/Officers get a DM with Approve/Reject buttons (persistent). One-active-squad is re-checked at approval time. |
| `/squad invite user:<@user>` | Leader / Officer | Add a user directly (still one-active-squad checked, still capacity-checked). |
| `/squad leave` | Everyone in a squad | Leave. A Leader must transfer or disband first. |
| `/squad remove user:<@user> [reason]` | Leader / Officer | Remove a member. Confirm step. Can't remove the Leader. |
| `/squad promote user:<@user>` | Leader | Member → Officer (max 2 officers). |
| `/squad demote user:<@user>` | Leader | Officer → Member. Confirm step. |
| `/squad transfer-leadership user:<@user>` | Leader | Hand leadership to another member. Confirm step. Outgoing leader becomes Officer if there's room, else Member. |
| `/squad disband [reason]` | Leader | Disband. Confirm step. Access revoked immediately; Discord objects deleted after the 30-day archive window; record + XP + name kept forever. |
| `/squad info` | Everyone in a squad | Show your squad's roster. |

## Leaderboards — `/leaderboard`

| Command | Who | What |
|---|---|---|
| `/leaderboard squads` | Everyone | Global squad leaderboard by Season Squad XP; top 32 badged (no automatic qualification). |
| `/leaderboard squad [squad_name]` | Everyone | A squad's internal member leaderboard (rank, member, Personal Lifetime/Season XP, contribution). Defaults to your own squad. |

## Applications — `/apply`

| Command | Who | What |
|---|---|---|
| `/apply developer` | Everyone | Developer application: select menu(s) + a 5-field modal + optional comments. Assigns **Developer Pending**, posts to `#applications-review`. |
| `/apply creator-streamer` | Everyone | Creator / Streamer application. No pending role. On approval assigns **Creator** and/or **Streamer** from Profile Type. |

One open application per type at a time; after a rejection, reapply after 30
days. The contact email and website/profile URL are format-checked on submit;
a bad value shows a **Fix & resubmit** button (the modal reopens pre-filled).

**Review actions** (buttons on the `#applications-review` message) — **elevated
staff only; Moderator and Senior Moderator are explicitly blocked**:

- **Approve** — assigns the role(s), removes Pending (Developer), DMs the applicant.
- **Reject** — optional reason modal; removes Pending; DMs the applicant; starts the 30-day clock.
- **Request More Info** — question modal; DMs the applicant a persistent **Respond** button; their reply attaches to the same record and moves it back to pending.

## Seasons — `/season`  (elevated staff)

| Command | What |
|---|---|
| `/season status` | Show the current/last season. |
| `/season start` | Open a new season (fails if one is already active). |
| `/season end` | End the active season (Season XP frozen until the next starts). |
| `/season new` | Confirm step. Ends the current season, resets **all** Personal Season XP + Season Squad XP to 0, opens a fresh season. Lifetime XP and per-member contribution are untouched. Audited with actor + counts. |

## XP configuration — `/xpconfig`  (elevated staff)

| Command | What |
|---|---|
| `/xpconfig view` | Current XP amounts, level thresholds, XP-excluded channels, integration mode. |
| `/xpconfig set-xp key:<…> value:<n>` | Update an XP amount: `skill_match_xp`, `tournament_participation_xp`, `placement_reward_1/2/3`, `prize_slot_bonus_xp`. Audited. |
| `/xpconfig set-threshold level:<2–7> value:<n>` | Lifetime Squad XP required for a level. Audited. |
| `/xpconfig exclude-channel channel:<#ch> excluded:<bool>` | Include/exclude a channel (or category) from granting Discord text XP. Audited. |
| `/xpconfig simulate-manava-event manava_user_id:<id> event_type:<…> [game] [place] [won_prize_slot] [event_id]` | Test harness: run a synthetic event through the real pipeline (dedup, XP, audit). Use a fixed `event_id` twice to prove duplicate handling. |

## Admin — `/admin`  (elevated staff)

| Command | What |
|---|---|
| `/admin set-verified user:<@user> verified:<bool>` | Manual Verified Player override (support fallback; real value comes from the Gateway in Gateway mode). Audited. |
| `/admin add-xp user:<@user> amount:<n> [reason]` | Manually grant Personal Lifetime + Season XP (cascades to the user's squad if any). Audited with reason. |
| `/admin link-manava-account user:<@user> manava_user_id:<id>` | Manual Discord↔MANAVA id map (support fallback). Rejects an id already linked to someone else. Audited. |
| `/admin restore-squad squad_name:<name>` | Recover a squad disbanded within the last 30 days (before its channels are purged): recreates the deleted squad role, re-activates the record, reopens memberships, re-grants access. Skips members now in another squad; refuses if the former Leader is. Audited. See `recovery.md`. |
| `/admin set-application-channel application_type:<Developer\|Creator / Streamer> [channel]` | Route that application type's review posts to a specific channel (locks it to Admin / MANAVA Team, denies Mod / Sr Mod). Leave `channel` empty to reset that type to the default `#applications-review`. Stored in `bot_config`, no redeploy. Audited. |

### `/admin gateway`  (elevated staff, Gateway mode only)

| Command | What |
|---|---|
| `/admin gateway refresh-identity user:<@user>` | Re-fetch the user's MANAVA identity (`linked` / `verifiedPlayer`) from the Gateway and re-cache `manava_user_id` + `verified_player`. |

Webhook registration is a MANAVA-side action (guarded by their
`INTERNAL_SERVICE_KEY`, which the bot doesn't hold) — there is no bot command
for it. See `manava-gateway-integration.md`.

### `!sync`  (message command, not slash — elevated staff)

Re-syncs slash commands, re-resolves required roles/categories, re-applies
SQUADS category permissions, re-resolves/creates the application roles +
`#applications-review`, and refreshes the XP-exclusion / integration-mode cache
— without a restart. Reacts ✅/❌ and posts a status summary.

## Help — `/help`

Everyone. Ephemeral, and **tailored to the caller**: normal members see only
the Squad / Leaderboards / Applications commands; Admin / MANAVA Team members
additionally see the Seasons, Admin, Gateway, and XP-configuration sections in
the same reply.
