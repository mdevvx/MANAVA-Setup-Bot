from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


class ConfigError(Exception):
    pass


def _require(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise ConfigError(f"Missing required environment variable: {name}")
    return value


def _optional_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ConfigError(f"Environment variable {name} must be an integer, got: {raw!r}") from exc


def _optional(name: str) -> str | None:
    value = os.environ.get(name)
    return value if value else None


@dataclass(frozen=True, slots=True)
class BotConfig:
    discord_token: str
    guild_id: int
    database_url: str
    log_level: str
    squad_archive_days: int
    # DEPRECATED legacy stub: shared-secret bearer token. Superseded by
    # webhook_signing_secret (HMAC per the MANAVA Gateway contract). Still
    # honoured if set and webhook_signing_secret is not, for a clean cutover.
    manava_webhook_secret: str | None
    webhook_port: int
    manava_poll_url: str | None
    manava_poll_api_key: str | None
    manava_poll_interval_seconds: int

    # --- MANAVA Gateway integration (real contract, 2026-08-31) ---
    # Gateway mode is "on" only when both the base URL and the API key are set;
    # otherwise the bot keeps the pre-Gateway stub behaviour (manual
    # verified_player / manava_user_id overrides, legacy webhook auth).
    manava_gateway_base_url: str | None
    discord_backend_api_key: str | None  # x-api-key header, bot -> Gateway
    webhook_signing_secret: str | None  # HMAC-SHA256 key, verifies x-manava-signature on inbound events

    @property
    def gateway_enabled(self) -> bool:
        return bool(self.manava_gateway_base_url and self.discord_backend_api_key)

    @classmethod
    def from_env(cls) -> "BotConfig":
        return cls(
            discord_token=_require("DISCORD_BOT_TOKEN"),
            guild_id=int(_require("DISCORD_GUILD_ID")),
            database_url=_require("DATABASE_URL"),
            log_level=os.environ.get("LOG_LEVEL", "INFO"),
            squad_archive_days=_optional_int("SQUAD_ARCHIVE_DAYS", 30),
            manava_webhook_secret=_optional("MANAVA_WEBHOOK_SECRET"),
            webhook_port=_optional_int("PORT", 8080),
            manava_poll_url=_optional("MANAVA_POLL_URL"),
            manava_poll_api_key=_optional("MANAVA_POLL_API_KEY"),
            manava_poll_interval_seconds=_optional_int("MANAVA_POLL_INTERVAL_SECONDS", 300),
            manava_gateway_base_url=_normalise_base_url(_optional("MANAVA_GATEWAY_BASE_URL")),
            discord_backend_api_key=_optional("DISCORD_BACKEND_API_KEY"),
            webhook_signing_secret=_optional("WEBHOOK_SIGNING_SECRET"),
        )


def _normalise_base_url(url: str | None) -> str | None:
    return url.rstrip("/") if url else None
