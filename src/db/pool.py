from __future__ import annotations

import asyncpg

from src.config import BotConfig


async def create_pool(config: BotConfig) -> asyncpg.Pool:
    # statement_cache_size=0: required when DATABASE_URL points at Supabase's
    # transaction pooler (PgBouncer in transaction mode) — it doesn't support
    # asyncpg's default server-side prepared statement caching, and leaving it
    # on causes intermittent "prepared statement already exists" errors.
    # Harmless no-op against a direct/session-pooler connection.
    # ssl="require": Supabase's pooler refuses unencrypted connections.
    # search_path: all bot-owned tables live in the `discord_bot` schema
    # (migration 0008) so they can't collide with other MANAVA services
    # sharing this database. `public` stays on the path for shared objects
    # (pgcrypto etc.).
    return await asyncpg.create_pool(
        dsn=config.database_url,
        min_size=1,
        max_size=10,
        statement_cache_size=0,
        ssl="require",
        server_settings={"search_path": "discord_bot, public"},
    )
