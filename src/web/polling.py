"""REST-polling fallback for MANAVA event integration, behind the
bot_config "manava_integration_mode" flag (default: webhook, not polling).

STUB: structurally complete but untestable until MANAVA provides a real
polling endpoint and confirms its response shape. Assumes the endpoint
returns either a JSON array of events, or {"events": [...]}, each item
shaped the same as a webhook payload.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

import aiohttp

from src.models.xp import ManavaEventValidationError
from src.services import manava_event_service

if TYPE_CHECKING:
    from src.bot import ManavaBot

logger = logging.getLogger(__name__)


class ManavaPollingTask:
    def __init__(self, bot: "ManavaBot") -> None:
        self._bot = bot
        self._task: asyncio.Task[None] | None = None

    def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        if not self._bot.config.manava_poll_url:
            logger.warning("Polling mode enabled but MANAVA_POLL_URL is not set — polling not started.")
            return
        self._task = asyncio.create_task(self._run())
        logger.info(
            "MANAVA REST-polling fallback started (interval=%ss)", self._bot.config.manava_poll_interval_seconds
        )

    def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            self._task = None

    async def _run(self) -> None:
        interval = max(self._bot.config.manava_poll_interval_seconds, 30)
        while True:
            try:
                await self._poll_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("MANAVA polling iteration failed")
            await asyncio.sleep(interval)

    async def _poll_once(self) -> None:
        url = self._bot.config.manava_poll_url
        if not url:
            return
        headers = {}
        if self._bot.config.manava_poll_api_key:
            headers["Authorization"] = f"Bearer {self._bot.config.manava_poll_api_key}"

        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                if resp.status != 200:
                    logger.warning("MANAVA poll endpoint returned status %s", resp.status)
                    return
                payload = await resp.json()

        events = payload if isinstance(payload, list) else payload.get("events", [])
        async with self._bot.db_pool.acquire() as conn:
            for raw_event in events:
                parsed = manava_event_service.parse_event(raw_event)
                if isinstance(parsed, ManavaEventValidationError):
                    logger.warning("Skipping malformed polled event: %s", parsed.reason)
                    continue
                await manava_event_service.process_event(conn, parsed)
