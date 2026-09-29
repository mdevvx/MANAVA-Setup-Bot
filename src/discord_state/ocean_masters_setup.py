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


_NAME_CHARS = frozenset("abcdefghijklmnopqrstuvwxyz0123456789-_")


def _matches_decorated(channel_name: str, target: str) -> bool:
    """True if `channel_name` is `target`, optionally behind a decorative prefix.

    The live server styles channels as e.g. "🌊丨ocean-masters-info" or
    "🌊ua丨ocean-masters-info-ua", so an exact-name match never hits. We accept a
    name that ENDS with the target as long as the character right before it isn't
    part of a channel-name word — so "🌊丨ocean-masters-info" matches, while
    "ocean-masters-info-ua" and "old-premier-news" don't.
    """
    name = channel_name.casefold()
    if not name.endswith(target):
        return False
    if len(name) == len(target):
        return True
    return name[-len(target) - 1] not in _NAME_CHARS


def _find_text_channel(guild: discord.Guild, name: str) -> discord.TextChannel | None:
    target = name.casefold()
    exact = discord.utils.find(lambda c: c.name.casefold() == target, guild.text_channels)
    if exact is not None:
        return exact
    candidates = [c for c in guild.text_channels if _matches_decorated(c.name, target)]
    if len(candidates) > 1:
        raise DiscordSetupError(
            f"Ambiguous Ocean Masters channel #{name}: "
            + ", ".join(f"#{c.name}" for c in candidates)
        )
    return candidates[0] if candidates else None


def missing_post_permissions(channel: discord.TextChannel) -> list[str]:
    """Permissions the bot lacks for a plain-text post into `channel` (empty = OK)."""
    perms = channel.permissions_for(channel.guild.me)
    missing: list[str] = []
    if not perms.view_channel:
        missing.append("View Channel")
    if not perms.send_messages:
        missing.append("Send Messages")
    return missing


def resolve_ocean_masters_channels(guild: discord.Guild) -> ResolvedOceanMastersState:
    resolved: dict[str, discord.TextChannel] = {}
    missing: list[str] = []
    for name in constants.OCEAN_MASTERS_CHANNEL_NAMES:
        channel = _find_text_channel(guild, name)
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
