"""MANAVA webhook receiver — the primary transport for MANAVA event integration.

STUB auth (shared-secret bearer token) until MANAVA provides their real
integration contract — see docs/manava-webhook-contract.md. Runs as an
aiohttp server inside the same process as the Discord bot, listening on
$PORT, so this stays a single Railway service.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from aiohttp import web

from src.models.xp import ManavaEventValidationError
from src.services import manava_event_service

if TYPE_CHECKING:
    from src.bot import ManavaBot

logger = logging.getLogger(__name__)

WEBHOOK_PATH = "/webhooks/manava"
HEALTH_PATH = "/healthz"


class ManavaWebhookServer:
    def __init__(self, bot: "ManavaBot") -> None:
        self._bot = bot
        self._runner: web.AppRunner | None = None

    async def start(self) -> None:
        if not self._bot.config.manava_webhook_secret:
            logger.warning(
                "MANAVA_WEBHOOK_SECRET not set — webhook server not started. "
                "Use /admin simulate-manava-event to test the pipeline instead."
            )
            return

        app = web.Application()
        app.router.add_post(WEBHOOK_PATH, self._handle_webhook)
        app.router.add_get(HEALTH_PATH, self._handle_health)
        self._runner = web.AppRunner(app)
        await self._runner.setup()
        site = web.TCPSite(self._runner, host="0.0.0.0", port=self._bot.config.webhook_port)
        await site.start()
        logger.info("MANAVA webhook server listening on port %s", self._bot.config.webhook_port)

    async def stop(self) -> None:
        if self._runner is not None:
            await self._runner.cleanup()
            self._runner = None

    async def _handle_health(self, request: web.Request) -> web.Response:
        return web.json_response({"status": "ok"})

    async def _handle_webhook(self, request: web.Request) -> web.Response:
        expected = self._bot.config.manava_webhook_secret
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer ") or auth_header.removeprefix("Bearer ") != expected:
            logger.warning("Rejected MANAVA webhook request: missing/invalid Authorization header")
            return web.json_response({"error": "unauthorized"}, status=401)

        try:
            raw = await request.json()
        except ValueError:
            return web.json_response({"error": "invalid JSON body"}, status=400)

        if not isinstance(raw, dict):
            return web.json_response({"error": "body must be a JSON object"}, status=400)

        parsed = manava_event_service.parse_event(raw)
        if isinstance(parsed, ManavaEventValidationError):
            logger.warning("Rejected malformed MANAVA event: %s", parsed.reason)
            return web.json_response({"error": parsed.reason}, status=400)

        async with self._bot.db_pool.acquire() as conn:
            outcome = await manava_event_service.process_event(conn, parsed)

        # 200 even for a duplicate — that's success from the sender's point of
        # view (the event is accounted for), it just didn't grant XP again.
        return web.json_response(
            {"event_id": outcome.event_id, "status": outcome.status, "xp_granted": outcome.xp_granted},
            status=200,
        )
