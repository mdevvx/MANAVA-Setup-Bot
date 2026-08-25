from __future__ import annotations

import asyncio
import logging
from pathlib import Path

import asyncpg

from src.config import BotConfig, ConfigError

logging.basicConfig(level="INFO", format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "src" / "db" / "migrations"


async def run() -> None:
    try:
        config = BotConfig.from_env()
    except ConfigError as exc:
        logger.error("Configuration error: %s", exc)
        raise SystemExit(1) from exc

    # statement_cache_size=0: required for Supabase's transaction pooler (PgBouncer
    # transaction mode) — see src/db/pool.py for the full explanation.
    # ssl="require": Supabase's pooler refuses unencrypted connections.
    conn = await asyncpg.connect(dsn=config.database_url, statement_cache_size=0, ssl="require")
    try:
        await conn.execute(
            """
            create table if not exists schema_migrations (
                filename text primary key,
                applied_at timestamptz not null default now()
            )
            """
        )
        applied = {row["filename"] for row in await conn.fetch("select filename from schema_migrations")}
        for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
            if path.name in applied:
                logger.info("Skipping already-applied migration %s", path.name)
                continue
            logger.info("Applying migration %s", path.name)
            sql = path.read_text(encoding="utf-8")
            async with conn.transaction():
                await conn.execute(sql)
                await conn.execute("insert into schema_migrations (filename) values ($1)", path.name)
        logger.info("Migrations complete.")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(run())
