# Squad capacity calculation

## Per-squad Discord object footprint

Every active squad consumes:

- 1 role (the squad-specific role, e.g. "Squad 3X")
- 4 channels (Member Text, Member Voice, Officer Text, Officer Voice)

## Category distribution

Squads are distributed across 7 pre-existing categories named `⚔️〔SQUADS 01〕`
through `⚔️〔SQUADS 07〕` (styled to match the server's existing category
naming convention; see `src/constants.py`). Each category is capped at 10 active squads, i.e. 40
channels (10 × 4), which is comfortably under Discord's 50-channel-per-category
hard limit — the 10-square headroom per category is deliberate slack for the
30-day archive window (see `archive-model.md`).

```
7 categories × 10 squads/category = 70 active squads max
70 squads × 1 role              = 70 squad roles
70 squads × 4 channels          = 280 squad channels
```

Category assignment is purely first-available-by-capacity, in category-name
order (`SQUADS 01` fills before `SQUADS 02`, etc.) — never by leaderboard rank
or any other ranking signal, per the spec.

## Server-wide headroom

The existing server has 43 roles and 115 channels before this bot's objects
are added.

**Roles** — Discord's hard limit is 250 roles per guild.

```
43 existing + 70 squad roles = 113 roles → 137 roles of headroom
```

**Channels** — Discord's hard limit is 500 channels per guild (channels +
categories combined).

```
115 existing + 280 active-squad channels = 395 channels → 105 channels of headroom
```

That 105-channel headroom is the budget for squads sitting in the 30-day
archived-but-not-yet-purged window (see `archive-model.md`) on top of the 70
fully active squads. At 4 channels per archived squad, that's room for **~26
squads disbanding simultaneously** before physical channel deletion catches
up — generous relative to any realistic disband rate at a 70-squad scale.

## Safe maximum

**70 active squads** (7 × 10) is the configured, enforced maximum
(`constants.MAX_ACTIVE_SQUADS`). `find_available_category` raises
`CapacityExceededError` — a friendly, non-technical message — once every
category is full; it never silently overflows a category or falls back to
some other placement rule.

If the server ever needs more headroom, the two levers are: adding an 8th
`SQUADS` category, or lowering the per-category cap to widen archive
headroom. Both are single-constant changes in `src/constants.py`, not schema
or logic changes.
