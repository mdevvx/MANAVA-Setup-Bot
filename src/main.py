from __future__ import annotations

import asyncio
import logging

from src.bot import ManavaBot
from src.config import BotConfig, ConfigError
from src.db.pool import create_pool


def _setup_logging(level: str) -> None:
    logging.basicConfig(level=level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    # This bot has no voice features (explicitly out of scope per the spec),
    # so discord.py's "PyNaCl/davey not installed, voice will NOT be
    # supported" startup warnings are noise, not a real problem — silenced
    # rather than adding an unneeded native voice dependency.
    logging.getLogger("discord.client").setLevel(logging.ERROR)


async def main() -> None:
    try:
        config = BotConfig.from_env()
    except ConfigError as exc:
        logging.basicConfig(level="ERROR")
        logging.getLogger(__name__).error("Configuration error: %s", exc)
        raise SystemExit(1) from exc

    _setup_logging(config.log_level)
    logger = logging.getLogger(__name__)

    pool = await create_pool(config)
    logger.info("Connected to database.")

    bot = ManavaBot(config, pool)
    try:
        await bot.start(config.discord_token)
    finally:
        await pool.close()


if __name__ == "__main__":
    asyncio.run(main())
