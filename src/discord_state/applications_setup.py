"""Resolve — and, per the client's decision, CREATE if missing — the Discord
objects the applications feature needs: the four application roles and the
single private `applications-review` channel.

Unlike the squad/staff roles (assumed to pre-exist; a pure lookup in
role_resolver), these are provisioned by the bot on startup and on `!sync`,
then the review channel's permissions are (re)applied every time so drift gets
corrected. Needs the "Manage Roles" and "Manage Channels" permissions.

A failure here disables ONLY the applications feature — squads and XP keep
working (see ManavaBot.refresh_application_state).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import discord

from src import constants
from src.discord_state.role_resolver import ResolvedGuildState
from src.errors import DiscordSetupError

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ResolvedApplicationState:
    developer_pending: discord.Role
    developer: discord.Role
    creator: discord.Role
    streamer: discord.Role
    review_channel: discord.TextChannel

    def role_by_name(self, name: str) -> discord.Role:
        mapping = {
            constants.ROLE_NAME_DEVELOPER_PENDING: self.developer_pending,
            constants.ROLE_NAME_DEVELOPER: self.developer,
            constants.ROLE_NAME_CREATOR: self.creator,
            constants.ROLE_NAME_STREAMER: self.streamer,
        }
        return mapping[name]


def _find_role_ci(guild: discord.Guild, name: str) -> discord.Role | None:
    target = name.casefold()
    return discord.utils.find(lambda r: r.name.casefold() == target, guild.roles)


async def _resolve_or_create_role(guild: discord.Guild, name: str) -> discord.Role:
    existing = _find_role_ci(guild, name)
    if existing is not None:
        return existing
    if not guild.me.guild_permissions.manage_roles:
        raise DiscordSetupError(
            f"The **{name}** role is missing and the bot lacks the 'Manage Roles' permission to create it."
        )
    logger.info("Creating missing application role %r", name)
    return await guild.create_role(name=name, mentionable=False, reason="MANAVA bot: application role")


# Matches discord.py's Mapping key union on create_text_channel/edit exactly.
_OverwriteTarget = discord.Role | discord.Member | discord.Object


def _review_channel_overwrites(
    state: ResolvedGuildState,
) -> dict[_OverwriteTarget, discord.PermissionOverwrite]:
    roles = state.roles
    bot_member = state.guild.me
    reviewer = discord.PermissionOverwrite(
        view_channel=True, send_messages=True, read_message_history=True
    )
    return {
        state.guild.default_role: discord.PermissionOverwrite(view_channel=False),
        bot_member: discord.PermissionOverwrite(
            view_channel=True,
            send_messages=True,
            read_message_history=True,
            manage_messages=True,
            embed_links=True,
        ),
        roles.admin: reviewer,
        roles.manava_team: reviewer,
        # Explicit denies: Moderator / Senior Moderator are staff everywhere
        # else but are deliberately excluded from application review (spec).
        roles.moderator: discord.PermissionOverwrite(view_channel=False),
        roles.senior_moderator: discord.PermissionOverwrite(view_channel=False),
    }


async def _resolve_or_create_channel(state: ResolvedGuildState) -> discord.TextChannel:
    guild = state.guild
    name = constants.CHANNEL_NAME_APPLICATIONS_REVIEW
    overwrites = _review_channel_overwrites(state)

    # Case-insensitive match (same tolerance as role resolution) so a manually
    # created "Applications-Review" isn't missed and duplicated.
    target = name.casefold()
    existing = discord.utils.find(lambda c: c.name.casefold() == target, guild.text_channels)
    if existing is not None:
        try:
            await existing.edit(overwrites=overwrites, reason="MANAVA bot: applications-review baseline permissions")
        except discord.Forbidden as exc:
            raise DiscordSetupError(
                "The bot can't manage the #applications-review channel's permissions. Contact staff."
            ) from exc
        return existing

    if not guild.me.guild_permissions.manage_channels:
        raise DiscordSetupError(
            "The #applications-review channel is missing and the bot lacks the 'Manage Channels' permission to create it."
        )
    logger.info("Creating missing #%s channel", name)
    return await guild.create_text_channel(
        name=name,
        overwrites=overwrites,
        reason="MANAVA bot: private application review channel",
    )


async def apply_review_channel_permissions(
    state: ResolvedGuildState, channel: discord.TextChannel
) -> None:
    """Lock a channel down to the same private baseline as #applications-review
    (Admin + MANAVA Team only; Moderator / Senior Moderator explicitly denied)
    — used when an admin points an application type at a custom channel."""
    await channel.edit(
        overwrites=_review_channel_overwrites(state),
        reason="MANAVA bot: application review channel baseline permissions",
    )


async def ensure_application_state(state: ResolvedGuildState) -> ResolvedApplicationState:
    developer_pending = await _resolve_or_create_role(state.guild, constants.ROLE_NAME_DEVELOPER_PENDING)
    developer = await _resolve_or_create_role(state.guild, constants.ROLE_NAME_DEVELOPER)
    creator = await _resolve_or_create_role(state.guild, constants.ROLE_NAME_CREATOR)
    streamer = await _resolve_or_create_role(state.guild, constants.ROLE_NAME_STREAMER)
    review_channel = await _resolve_or_create_channel(state)
    return ResolvedApplicationState(
        developer_pending=developer_pending,
        developer=developer,
        creator=creator,
        streamer=streamer,
        review_channel=review_channel,
    )
