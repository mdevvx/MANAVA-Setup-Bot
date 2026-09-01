# QA report

`pytest` — **75 passing** (`pytest.ini` sets `asyncio_mode = auto`). Unit-level:
service logic, permission-overwrite construction, event parsing/dedup, and
signature verification, using mocked repositories / Discord objects rather than
a live gateway or DB. Run: `pip install -r requirements-dev.txt && pytest`.

## Coverage vs the acceptance checklist

### Squads

| Item | Coverage |
|---|---|
| Eligible creation | `test_eligibility.py` (name validation); creation gate logic in `squad_eligibility.check_eligibility` — **manual** end-to-end (needs live guild) |
| Every individual ineligible gate | `squad_eligibility` builds one `EligibilityFailure` per failed gate; name gates in `test_eligibility.py`. Member-role / XP / verified / already-in-squad gates — **manual** |
| Duplicate name rejection | `errors.DuplicateSquadNameError` + `squads_repo` unique index; name-taken check in `check_eligibility` — **manual** live |
| Second-squad-attempt rejection | partial unique index `squad_memberships_one_active_per_user`; `AlreadyInSquadError` paths in `test_membership_flows.py` |
| Apply / Invite / Approve / Reject | `test_membership_flows.py` (approve/invite one-active-squad + capacity re-check); Reject path — **manual** |
| Leave / Remove | `test_membership_flows.py` (`leave` blocked for leader, `remove` blocked on leader target) |
| Promote / Demote | `test_membership_flows.py` (officer limit, officer-can't-promote) |
| Transfer Leadership | `test_membership_flows.py` (outgoing-role calc) — full swap **manual** |
| Disband / archive | `archive-model.md` documents the model; purge task — **manual** |
| Category capacity enforcement | `test_capacity.py` (distribution, per-category cap, 70 max) |
| **Permission isolation between two squads** | `test_permission_isolation.py` — officer-channel overwrites are per-member, proving Squad A officers can't see Squad B |

### XP

| Item | Coverage |
|---|---|
| Valid text message grants XP | `test_discord_xp_cooldown.py` |
| Too-short text does not | `test_discord_xp_cooldown.py` |
| Cooldown enforced | `test_discord_xp_cooldown.py` |
| MANAVA event grants XP correctly | `test_manava_event_dedup.py` (first delivery → 50 XP); `test_manava_event_parsing.py` (Gateway payloads parse) |
| **Duplicate MANAVA event doesn't double-grant** | `test_manava_event_dedup.py` — `grant` awaited exactly once across two deliveries of the same `event_id` |
| Member vs non-member contribution | `test_squad_xp_contribution.py` |
| Leave-then-join-another-squad XP | `test_squad_xp_contribution.py` (contribution stays with the squad; new stint starts at 0) |
| Wave 1500 gate | `check_eligibility` lifetime-XP gate — **manual** live |
| `wonPrizeSlot` / prize-slot bonus | `test_manava_event_parsing.py` parses it; `_compute_xp` adds `prize_slot_bonus_xp` (default 0) |

### Seasons

| Item | Coverage |
|---|---|
| Start / End / Reset behaviour | `test_season_reset.py` (start-new resets both counters; no-active-season path; end-with-none raises) |
| **Lifetime XP persists across a season reset** | `test_season_reset.py` — reset touches only `season_xp`; audit payload asserts no "lifetime" values move |
| Actor recorded | `test_season_reset.py` |

### Applications

| Item | Coverage |
|---|---|
| Submission | `test_application_flows.py` (history + audit written, PII kept out of audit) |
| Developer Pending assignment | `application_service.pending_role_name` + `application_actions.finalize_submission` — **manual** live (role add) |
| Request More Information round-trip | `test_application_flows.py` (status → more_info_requested → back to pending; only the real applicant can respond) |
| Approve / Reject | `test_application_flows.py` (one-way; second decision raises `ApplicationAlreadyDecidedError`) |
| 30-day retry enforcement | `test_application_cooldown.py` (active blocks; recent reject in cooldown; past-cooldown allows; no prior reject allows) |
| Correct role assignment | `test_application_flows.py::test_roles_for_approval_and_pending_role` (Developer; Creator/Streamer/Both mapping) |
| **Reviewer-permission boundaries (Mod / Senior Mod blocked)** | `test_application_permissions.py` — `is_elevated_staff` False for Mod/Senior Mod, True for Admin/MANAVA Team; `#applications-review` overwrites also deny them (`applications_setup`) |

### Security

| Item | Coverage |
|---|---|
| **Bot never grants a protected role** | `test_protected_role_guard.py` — `ensure_assignable` raises for Admin/MANAVA Team/Senior Mod/Mod; `role_safety.assign_role` refuses before any Discord call |
| Secrets only in env | `config.py` reads all secrets from env; none in `bot_config` / source |
| PII not in generic logs | `logging.md`; `application_service._audit_public_view`; `test_application_flows.py` asserts email/company absent from the audit payload |

### Failure scenarios

| Item | Coverage |
|---|---|
| MANAVA / Gateway unavailable | `test_gateway_identity.py` — `link_state` falls back to the cached `verified_player` on `GatewayError`; `link_state` distinguishes NOT_LINKED vs NOT_VERIFIED from the Gateway response |
| Supabase unavailable | `db/retry.with_db_retry` + webhook returns `503` (Gateway re-delivers). Command-path failures surface as friendly errors — **manual** to exercise |
| Bot restart mid-flow | Persistent views (`ApplicationReviewView`, `SquadJoinDecisionButton`, `MoreInfoRespondButton`) re-registered in `setup_hook`; `custom_id`/message-id lookup carries no in-memory state — **manual** (redeploy + click an old button) |
| Discord permissions removed mid-operation | `role_safety` maps `discord.Forbidden` → friendly `DiscordSetupError` — **manual** |
| Discord rate limits | handled by discord.py automatically — no test |
| **Duplicate webhook delivery** | `test_manava_event_dedup.py`; `test_gateway_signature.py` (tampered body rejected) |
| Inbound signature verification | `test_gateway_signature.py` — valid passes; tampered / wrong-secret / missing header fail; signing secret beats legacy bearer |

## Manual test checklist (needs a live server + DB)

Run these once against a staging guild after deploy (see `README.md` "Track B"):

1. Eligible `/squad create`; then each gate individually (remove Member role /
   set XP < 1500 / set unverified / already in a squad / duplicate name).
2. `/squad apply` → approve via the DM buttons → **restart the bot** → apply
   again → approve after restart (proves persistent views).
3. Two squads, two officers: confirm officer A cannot open squad B's officer
   channel.
4. `/squad disband` → access gone immediately → squad off the leaderboard.
5. Text XP: ≥10-char message grants; repeat within 60s doesn't; <10 chars
   doesn't; excluded channel doesn't.
6. `/xpconfig simulate-manava-event` with a fixed `event_id` twice → second is
   `duplicate`, `xp_granted=0`.
7. `/season new` → Personal Season XP and Season Squad XP zeroed, Lifetime
   unchanged; `audit_logs` has the `season.start_new` row.
8. `/apply developer` → Developer Pending assigned → Approve → Pending removed,
   Developer added, applicant DM'd. Repeat immediately → blocked (active).
   After a Reject, `/apply developer` → blocked with the 30-day message.
9. As a Moderator, try the review buttons → blocked.
10. Gateway (once credentialed + MANAVA has registered the `/webhooks/manava`
    URL): trigger a real event from the Gateway → confirm XP granted +
    `processed_events` row; have it redelivered → no double grant. Check
    `/admin gateway refresh-identity` returns the expected linked/verified.
