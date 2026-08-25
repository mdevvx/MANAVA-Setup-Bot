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


@dataclass(frozen=True, slots=True)
class BotConfig:
    discord_token: str
    guild_id: int
    database_url: str
    log_level: str
    squad_archive_days: int

    @classmethod
    def from_env(cls) -> "BotConfig":
        return cls(
            discord_token=_require("DISCORD_BOT_TOKEN"),
            guild_id=int(_require("DISCORD_GUILD_ID")),
            database_url=_require("DATABASE_URL"),
            log_level=os.environ.get("LOG_LEVEL", "INFO"),
            squad_archive_days=_optional_int("SQUAD_ARCHIVE_DAYS", 30),
        )
