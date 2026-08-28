-- Extend the RLS-with-zero-policies pattern (see 0002_enable_rls.sql) to the
-- 5 tables Phase 2 introduced. Same reasoning: doesn't affect the bot (which
-- connects as the table owner), blocks the Supabase REST API from touching
-- this data if the anon/service key is ever used anywhere else.

alter table squad_xp enable row level security;
alter table xp_config enable row level security;
alter table level_thresholds enable row level security;
alter table processed_events enable row level security;
alter table bot_config enable row level security;
