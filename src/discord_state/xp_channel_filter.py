from __future__ import annotations

import discord


def is_message_xp_eligible(message: discord.Message, excluded_channel_ids: set[int]) -> bool:
    """Channel-level gate for Discord text XP. The excluded set is meant to
    hold staff/service/moderation/log/bot/applications-review channels —
    configured via /admin (stored in bot_config), not hardcoded, per the spec.
    """
    channel_id = message.channel.id
    if channel_id in excluded_channel_ids:
        return False
    category = getattr(message.channel, "category", None)
    if category is not None and category.id in excluded_channel_ids:
        return False
    return True


def is_within_cooldown(last_grant_monotonic: float | None, now_monotonic: float, cooldown_seconds: int) -> bool:
    """True if a new grant should be BLOCKED (still on cooldown)."""
    if last_grant_monotonic is None:
        return False
    return (now_monotonic - last_grant_monotonic) < cooldown_seconds
