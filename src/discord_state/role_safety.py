"""Single choke point for the bot adding/removing roles on a member.

Every path that grants a role — squad provisioning, application approvals —
should go through here so the protected-role deny-list (Admin, MANAVA Team,
Senior Moderator, Moderator) is enforced in exactly one place, and a missing
"Manage Roles" permission turns into a friendly message instead of a raw
traceback.
"""

from __future__ import annotations

import logging

import discord

from src.discord_state.role_resolver import ResolvedGuildState
from src.errors import DiscordSetupError

logger = logging.getLogger(__name__)


async def assign_role(
    state: ResolvedGuildState, member: discord.Member, role: discord.Role, *, reason: str
) -> None:
    state.ensure_assignable(role)  # hard guard: refuses protected staff roles even on a caller bug
    if role in member.roles:
        return
    try:
        await member.add_roles(role, reason=reason)
    except discord.Forbidden as exc:
        logger.error("Missing permission to add role %s to %s", role.name, member.id)
        raise DiscordSetupError(
            f"The bot can't assign the **{role.name}** role — check its permissions and role position. Contact staff."
        ) from exc


async def remove_role(
    state: ResolvedGuildState, member: discord.Member, role: discord.Role, *, reason: str
) -> None:
    if role not in member.roles:
        return
    try:
        await member.remove_roles(role, reason=reason)
    except discord.Forbidden as exc:
        logger.error("Missing permission to remove role %s from %s", role.name, member.id)
        raise DiscordSetupError(
            f"The bot can't remove the **{role.name}** role — check its permissions and role position. Contact staff."
        ) from exc
