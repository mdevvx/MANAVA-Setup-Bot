"""HTTP client for the MANAVA Gateway — the bot -> Gateway direction.

There is exactly one endpoint the Discord bot backend is authorised to call:

    GET /internal/identity/:discordId    (header: x-api-key: <DISCORD_BACKEND_API_KEY>)

The Gateway's own env docs are explicit that this key opens only the identity
endpoint. Webhook registration (`/internal/bot-webhooks`) is guarded by a
separate internal service key that the bot does not hold — MANAVA registers
this deployment's `/webhooks/manava` URL on their side.

The inbound direction (Gateway -> bot event webhooks, verified via
`x-manava-signature`) is handled in src/web/webhook_server.py.

One `aiohttp.ClientSession` is shared for the process lifetime (created lazily
on first use, inside the running loop) and closed by `ManavaBot.close()`.
"""

from __future__ import annotations

import logging

import aiohttp

from src.config import BotConfig
from src.errors import GatewayDisabledError, GatewayError
from src.models.gateway import GatewayIdentity

logger = logging.getLogger(__name__)

_TIMEOUT = aiohttp.ClientTimeout(total=10)


class GatewayClient:
    def __init__(self, config: BotConfig) -> None:
        self._config = config
        self._session: aiohttp.ClientSession | None = None

    @property
    def enabled(self) -> bool:
        return self._config.gateway_enabled

    def _creds(self) -> tuple[str, str]:
        if not self._config.gateway_enabled:
            raise GatewayDisabledError(
                "MANAVA Gateway mode is off — set MANAVA_GATEWAY_BASE_URL and DISCORD_BACKEND_API_KEY."
            )
        assert self._config.manava_gateway_base_url is not None
        assert self._config.discord_backend_api_key is not None
        return self._config.manava_gateway_base_url, self._config.discord_backend_api_key

    def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(timeout=_TIMEOUT)
        return self._session

    async def aclose(self) -> None:
        if self._session is not None and not self._session.closed:
            await self._session.close()
        self._session = None

    async def get_identity(self, discord_user_id: int) -> GatewayIdentity:
        """GET /internal/identity/:discordId. The Gateway returns 200 with
        `{linked: false, ...}` for an unknown Discord id; a non-2xx means the
        Gateway or its upstream is unavailable — the caller falls back to
        cached data on GatewayError."""
        base, api_key = self._creds()
        url = f"{base}/internal/identity/{discord_user_id}"
        try:
            async with self._get_session().get(url, headers={"x-api-key": api_key}) as resp:
                text = await resp.text()
                if resp.status >= 300:
                    raise GatewayError(f"identity lookup -> HTTP {resp.status}: {text[:200]}")
                payload = await resp.json()
        except aiohttp.ClientError as exc:
            raise GatewayError(f"identity lookup failed: {exc}") from exc
        if not isinstance(payload, dict):
            raise GatewayError("identity lookup returned a non-object body")
        return GatewayIdentity.from_payload(payload)
