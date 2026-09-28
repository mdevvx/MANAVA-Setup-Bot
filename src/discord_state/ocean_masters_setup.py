"""Resolve the 4 existing Ocean Masters channels by name — a pure lookup, like
role_resolver's squad/staff roles, NOT a create-if-missing flow like
applications_setup (client confirmed 2026-09-17 these already exist; the spec
explicitly says not to create new channels for this release).

A failure here disables ONLY Ocean Masters posting — squads, XP, applications
and the season/Top-32 commands are all unaffected.
"""

from __future__ import annotations

from dataclasses import dataclass

import discord

from src import constants
from src.errors import DiscordSetupError


@dataclass(frozen=True, slots=True)
class ResolvedOceanMastersState:
    info: discord.TextChannel
    news: discord.TextChannel
    brackets: discord.TextChannel
    history: discord.TextChannel


def _find_text_channel_ci(guild: discord.Guild, name: str) -> discord.TextChannel | None:
    target = name.casefold()
    return discord.utils.find(lambda c: c.name.casefold() == target, guild.text_channels)


def resolve_ocean_masters_channels(guild: discord.Guild) -> ResolvedOceanMastersState:
    resolved: dict[str, discord.TextChannel] = {}
    missing: list[str] = []
    for name in constants.OCEAN_MASTERS_CHANNEL_NAMES:
        channel = _find_text_channel_ci(guild, name)
        if channel is None:
            missing.append(f"#{name}")
        else:
            resolved[name] = channel

    if missing:
        raise DiscordSetupError(
            "Missing required Ocean Masters channels: " + ", ".join(missing)
        )

    return ResolvedOceanMastersState(
        info=resolved[constants.CHANNEL_NAME_OCEAN_MASTERS_INFO],
        news=resolved[constants.CHANNEL_NAME_PREMIER_NEWS],
        brackets=resolved[constants.CHANNEL_NAME_PREMIER_BRACKETS],
        history=resolved[constants.CHANNEL_NAME_PREMIER_HISTORY],
    )
