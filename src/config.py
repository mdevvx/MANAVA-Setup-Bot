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
    # STUB: real endpoint/credentials pending from MANAVA. If unset, the
    # webhook server simply doesn't start (see src/web/webhook_server.py) —
    # the /admin simulate-manava-event test harness works regardless.
    manava_webhook_secret: str | None
    webhook_port: int
    manava_poll_url: str | None
    manava_poll_api_key: str | None
    manava_poll_interval_seconds: int

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
        )
