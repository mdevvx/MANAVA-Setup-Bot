-- Per-application-type review channel overrides, set at runtime via
-- /admin set-application-channel. {app_type -> channel id}; a type not present
-- falls back to the default #applications-review channel. Seeded empty so the
-- key is discoverable; bot_config already has RLS from 0004.

insert into bot_config (key, value) values
    ('application_review_channel_ids', '{}'::jsonb)
on conflict (key) do nothing;
