-- Extend the RLS-with-zero-policies pattern (see 0002_enable_rls.sql) to the
-- 3 tables Phase 3 introduced. Same reasoning: no effect on the bot (which
-- connects as the table owner), but blocks the Supabase REST API from
-- touching this data if the anon/service key is ever used anywhere else.
-- This matters more here than elsewhere: applications hold PII.

alter table applications enable row level security;
alter table application_history enable row level security;
alter table season_state enable row level security;
