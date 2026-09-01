-- Phase 3 / MANAVA Gateway: one new admin-editable XP amount.
--
-- prize_slot_bonus_xp — extra XP granted on a tournament_placement event whose
-- payload has wonPrizeSlot=true (the player landed in a paid prize-pool slot,
-- not necessarily 1st). Seeded to 0 so it changes nothing until an admin sets
-- it via /xpconfig set-xp.

insert into xp_config (key, value) values
    ('prize_slot_bonus_xp', 0)
on conflict (key) do nothing;
