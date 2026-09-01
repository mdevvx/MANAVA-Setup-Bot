"""MANAVA webhook receiver — the inbound (Gateway -> bot) half of the
integration contract (gateway-diagram-en.html).

Auth: the MANAVA Gateway signs each request body with HMAC-SHA256 and sends
`x-manava-signature: sha256=<hex>` (key = WEBHOOK_SIGNING_SECRET). If that
secret isn't set, a legacy shared-secret `Authorization: Bearer` check
(MANAVA_WEBHOOK_SECRET) is used instead, for a clean cutover. If neither is
set the event endpoint returns 503, but the server still runs so `GET
/healthz` is always available as a platform health check.

Runs as an aiohttp server inside the bot process, listening on $PORT, so this
stays a single deployable service.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
from typing import TYPE_CHECKING

import asyncpg
from aiohttp import web

from src.db.retry import with_db_retry
from src.models.xp import ManavaEventOutcome, ManavaEventValidationError
from src.services import manava_event_service

if TYPE_CHECKING:
    from src.bot import ManavaBot

logger = logging.getLogger(__name__)

WEBHOOK_PATH = "/webhooks/manava"
HEALTH_PATH = "/healthz"
SIGNATURE_HEADER = "x-manava-signature"


class ManavaWebhookServer:
    def __init__(self, bot: "ManavaBot") -> None:
        self._bot = bot
        self._runner: web.AppRunner | None = None

    def _auth_configured(self) -> bool:
        return bool(self._bot.config.webhook_signing_secret or self._bot.config.manava_webhook_secret)

    async def start(self) -> None:
        # The HTTP server always runs so `GET /healthz` is available as a
        # platform health check regardless of integration state. When no
        # webhook auth is configured, the event endpoint itself returns 503
        # (see _handle_webhook) — use /xpconfig simulate-manava-event to
        # exercise the pipeline in that state.
        app = web.Application()
        app.router.add_post(WEBHOOK_PATH, self._handle_webhook)
        app.router.add_get(HEALTH_PATH, self._handle_health)
        self._runner = web.AppRunner(app)
        await self._runner.setup()
        site = web.TCPSite(self._runner, host="0.0.0.0", port=self._bot.config.webhook_port)
        await site.start()

        if self._bot.config.webhook_signing_secret:
            scheme = "HMAC x-manava-signature"
        elif self._bot.config.manava_webhook_secret:
            scheme = "legacy bearer token"
        else:
            scheme = "event endpoint DISABLED (no webhook secret set) — /healthz only"
        logger.info("MANAVA webhook server listening on port %s (%s)", self._bot.config.webhook_port, scheme)

    async def stop(self) -> None:
        if self._runner is not None:
            await self._runner.cleanup()
            self._runner = None

    async def _handle_health(self, request: web.Request) -> web.Response:
        return web.json_response({"status": "ok"})

    def _authenticate(self, raw_body: bytes, request: web.Request) -> bool:
        signing_secret = self._bot.config.webhook_signing_secret
        if signing_secret:
            header = request.headers.get(SIGNATURE_HEADER, "")
            expected = "sha256=" + hmac.new(signing_secret.encode(), raw_body, hashlib.sha256).hexdigest()
            return hmac.compare_digest(expected, header)

        # Legacy fallback: Authorization: Bearer <MANAVA_WEBHOOK_SECRET>
        legacy = self._bot.config.manava_webhook_secret
        auth_header = request.headers.get("Authorization", "")
        return bool(
            legacy
            and auth_header.startswith("Bearer ")
            and hmac.compare_digest(auth_header.removeprefix("Bearer "), legacy)
        )

    async def _handle_webhook(self, request: web.Request) -> web.Response:
        if not self._auth_configured():
            return web.json_response(
                {"error": "webhook auth not configured on this deployment"}, status=503
            )

        raw_body = await request.read()

        if not self._authenticate(raw_body, request):
            logger.warning("Rejected MANAVA webhook request: missing/invalid signature")
            return web.json_response({"error": "unauthorized"}, status=401)

        try:
            raw = json.loads(raw_body)
        except ValueError:
            return web.json_response({"error": "invalid JSON body"}, status=400)

        if not isinstance(raw, dict):
            return web.json_response({"error": "body must be a JSON object"}, status=400)

        parsed = manava_event_service.parse_event(raw)
        if isinstance(parsed, ManavaEventValidationError):
            logger.warning("Rejected malformed MANAVA event: %s", parsed.reason)
            return web.json_response({"error": parsed.reason}, status=400)

        async def _process() -> ManavaEventOutcome:
            async with self._bot.db_pool.acquire() as conn:
                return await manava_event_service.process_event(conn, parsed)

        try:
            outcome = await with_db_retry(_process, attempts=2)
        except (asyncpg.PostgresConnectionError, asyncpg.InterfaceError, ConnectionError, OSError):
            # Transient DB trouble: tell the sender to retry rather than
            # silently dropping the event. The Gateway re-delivers on non-2xx.
            logger.exception("DB unavailable while processing MANAVA event %s", parsed.event_id)
            return web.json_response({"error": "temporarily unavailable, retry later"}, status=503)

        # 200 even for a duplicate — that's success from the sender's point of
        # view (the event is accounted for), it just didn't grant XP again.
        return web.json_response(
            {"event_id": outcome.event_id, "status": outcome.status, "xp_granted": outcome.xp_granted},
            status=200,
        )
