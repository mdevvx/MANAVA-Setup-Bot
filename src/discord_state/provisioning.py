from __future__ import annotations

import logging
import re
from collections.abc import Iterable

import discord

from src.discord_state.role_resolver import ResolvedGuildState
from src.errors import DiscordSetupError
from src.models.squad import NewSquadDiscordObjects, Squad, SquadRole

logger = logging.getLogger(__name__)

_SLUG_COLLAPSE = re.compile(r"-+")
_SLUG_STRIP = re.compile(r"[\s_]+")


def _slugify(name: str) -> str:
    slug = _SLUG_STRIP.sub("-", name.strip().lower())
    slug = _SLUG_COLLAPSE.sub("-", slug)
    return slug.strip("-")


# Matches discord.py's Mapping[Role | Member | Object, PermissionOverwrite] parameter
# type on create_text_channel/create_voice_channel exactly — Mapping's key type is
# invariant, so this has to be the same union, not just a subset of it.
_OverwriteTarget = discord.Role | discord.Member | discord.Object


def _staff_overwrite() -> discord.PermissionOverwrite:
    # Explicit moderation permissions for authorized staff (Admin, MANAVA Team,
    # Senior Moderator, Moderator) — enough to view and moderate squad
    # channels, but deliberately NOT Manage Channel/Permissions/Roles/Webhooks,
    # which stay bot/DB-governed so Discord state never drifts from what's
    # tracked in the database.
    return discord.PermissionOverwrite(
        view_channel=True,
        send_messages=True,
        read_message_history=True,
        manage_messages=True,
        connect=True,
        speak=True,
        move_members=True,
    )


def _base_overwrites(state: ResolvedGuildState) -> dict[_OverwriteTarget, discord.PermissionOverwrite]:
    # The bot itself MUST get an explicit member-level overwrite here. Without
    # it, the @everyone deny below blocks the bot too (View Channel is a
    # prerequisite for every other channel action in Discord's permission
    # model) — it could create channels but then be unable to manage, or even
    # delete, the very channels it just created.
    bot_member = state.guild.me
    if bot_member is None:
        raise DiscordSetupError("Could not resolve the bot's own member object in this server.")

    overwrites: dict[_OverwriteTarget, discord.PermissionOverwrite] = {
        state.guild.default_role: discord.PermissionOverwrite(view_channel=False),
        bot_member: discord.PermissionOverwrite(
            view_channel=True,
            manage_channels=True,
            manage_permissions=True,
            send_messages=True,
            read_message_history=True,
            connect=True,
            speak=True,
            move_members=True,
        ),
    }
    for role in state.roles.staff_roles:
        overwrites[role] = _staff_overwrite()
    return overwrites


async def apply_category_baseline_permissions(state: ResolvedGuildState) -> None:
    """Lock down the SQUADS categories' own base permissions to the same
    staff-only baseline used on every squad channel. Not load-bearing for the
    bot's own channels (they always get explicit overwrites at creation time,
    never inherited from the category) — this is defense-in-depth for the
    case a channel ever gets manually created inside one of these categories,
    or a channel's permissions get manually re-synced to its parent."""
    overwrites = _base_overwrites(state)
    for category in state.squad_categories:
        await category.edit(overwrites=overwrites, reason="Baseline SQUADS category permissions")


def build_member_channel_overwrites(
    state: ResolvedGuildState, squad_role: discord.Role
) -> dict[_OverwriteTarget, discord.PermissionOverwrite]:
    """Member Text/Voice access is keyed off the squad's own unique role only —
    every current member (including the Leader/Officers) holds this role."""
    overwrites = _base_overwrites(state)
    overwrites[squad_role] = discord.PermissionOverwrite(view_channel=True)
    return overwrites


def build_officer_channel_overwrites(
    state: ResolvedGuildState, authorized_members: Iterable[discord.Member]
) -> dict[_OverwriteTarget, discord.PermissionOverwrite]:
    """Officer Text/Voice access is keyed off individual member-ID overwrites for
    that squad's Leader + Officers, NOT the shared global Squad Officer role —
    this is what keeps Squad A's officers from ever seeing Squad B's channels."""
    overwrites = dict(_base_overwrites(state))
    for member in authorized_members:
        overwrites[member] = discord.PermissionOverwrite(view_channel=True)
    return overwrites


async def create_squad_objects(
    state: ResolvedGuildState,
    *,
    squad_name: str,
    leader: discord.Member,
    category_id: int,
) -> NewSquadDiscordObjects:
    category = discord.utils.get(state.squad_categories, id=category_id)
    if category is None:
        raise RuntimeError(f"Resolved category id {category_id} is not a known squad category")

    slug = _slugify(squad_name)
    role: discord.Role | None = None
    created_channels: list[discord.abc.GuildChannel] = []
    try:
        role = await state.guild.create_role(
            name=f"Squad {squad_name}",
            mentionable=False,
            reason=f"Squad created by {leader} ({leader.id})",
        )

        member_overwrites = build_member_channel_overwrites(state, role)
        officer_overwrites = build_officer_channel_overwrites(state, [leader])

        member_text = await category.create_text_channel(
            name=f"{slug}-chat", overwrites=member_overwrites, reason="Squad member text channel"
        )
        created_channels.append(member_text)

        member_voice = await category.create_voice_channel(
            name=f"{squad_name} Voice", overwrites=member_overwrites, reason="Squad member voice channel"
        )
        created_channels.append(member_voice)

        officer_text = await category.create_text_channel(
            name=f"{slug}-officers", overwrites=officer_overwrites, reason="Squad officer text channel"
        )
        created_channels.append(officer_text)

        officer_voice = await category.create_voice_channel(
            name=f"{squad_name} Officer Voice", overwrites=officer_overwrites, reason="Squad officer voice channel"
        )
        created_channels.append(officer_voice)

        await leader.add_roles(role, state.roles.squad_leader, reason="Squad creation")

        return NewSquadDiscordObjects(
            role_id=role.id,
            category_id=category.id,
            member_text_channel_id=member_text.id,
            member_voice_channel_id=member_voice.id,
            officer_text_channel_id=officer_text.id,
            officer_voice_channel_id=officer_voice.id,
        )
    except discord.DiscordException:
        logger.exception(
            "Failed while provisioning squad Discord objects for %r; rolling back partial creation", squad_name
        )
        for channel in created_channels:
            try:
                await channel.delete(reason="Rollback: squad creation failed")
            except discord.DiscordException:
                logger.exception("Failed to roll back channel %s during squad creation cleanup", channel.id)
        if role is not None:
            try:
                await role.delete(reason="Rollback: squad creation failed")
            except discord.DiscordException:
                logger.exception("Failed to roll back role %s during squad creation cleanup", role.id)
        raise


async def rollback_new_objects(state: ResolvedGuildState, objects: NewSquadDiscordObjects) -> None:
    """Compensating cleanup when Discord objects were created but the DB insert failed."""
    guild = state.guild
    for channel_id in (
        objects.member_text_channel_id,
        objects.member_voice_channel_id,
        objects.officer_text_channel_id,
        objects.officer_voice_channel_id,
    ):
        channel = guild.get_channel(channel_id)
        if channel is not None:
            try:
                await channel.delete(reason="Rollback: squad DB insert failed")
            except discord.DiscordException:
                logger.exception("Failed to roll back channel %s", channel_id)
    role = guild.get_role(objects.role_id)
    if role is not None:
        try:
            await role.delete(reason="Rollback: squad DB insert failed")
        except discord.DiscordException:
            logger.exception("Failed to roll back role %s", objects.role_id)


async def teardown_squad_discord_objects(state: ResolvedGuildState, squad: Squad) -> None:
    """Best-effort physical deletion of a disbanded squad's channels once the
    30-day archive window has elapsed. The role is normally already gone by
    this point (see revoke_all_member_access), so this mainly cleans up channels."""
    guild = state.guild
    for channel_id in (
        squad.member_text_channel_id,
        squad.member_voice_channel_id,
        squad.officer_text_channel_id,
        squad.officer_voice_channel_id,
    ):
        channel = guild.get_channel(channel_id)
        if channel is not None:
            try:
                await channel.delete(reason="Squad archive window elapsed")
            except discord.DiscordException:
                logger.exception("Failed to delete channel %s for archived squad %s", channel_id, squad.id)
    role = guild.get_role(squad.role_id)
    if role is not None:
        try:
            await role.delete(reason="Squad archive window elapsed")
        except discord.DiscordException:
            logger.exception("Failed to delete role %s for archived squad %s", squad.role_id, squad.id)


async def revoke_all_member_access(state: ResolvedGuildState, squad: Squad) -> None:
    """On disband: revoke access immediately, but leave physical channel deletion
    for the 30-day purge job. See docs/archive-model.md for the reasoning."""
    guild = state.guild
    role = guild.get_role(squad.role_id)
    rank_roles = (state.roles.squad_leader, state.roles.squad_officer, state.roles.squad_member)
    if role is not None:
        # Strip the shared Squad Leader/Officer/Member rank roles from everyone
        # in this squad BEFORE deleting the squad-specific role (deleting that
        # one is auto-removed from members by Discord, but the shared rank roles
        # are not).
        for squad_member in list(role.members):
            to_remove = [r for r in rank_roles if r in squad_member.roles]
            if to_remove:
                try:
                    await squad_member.remove_roles(*to_remove, reason="Squad disbanded")
                except discord.DiscordException:
                    logger.exception("Failed to strip rank roles from %s on disband", squad_member.id)
        try:
            await role.delete(reason="Squad disbanded — revoke member access immediately")
        except discord.DiscordException:
            logger.exception(
                "Failed to delete role %s while revoking access for disbanded squad %s", squad.role_id, squad.id
            )
    for channel_id in (squad.officer_text_channel_id, squad.officer_voice_channel_id):
        channel = guild.get_channel(channel_id)
        if channel is not None:
            for target in list(channel.overwrites.keys()):
                if isinstance(target, discord.Member):
                    try:
                        await channel.set_permissions(target, overwrite=None, reason="Squad disbanded")
                    except discord.DiscordException:
                        logger.exception("Failed to clear overwrite for %s on channel %s", target.id, channel_id)


async def reapply_restored_squad_access(
    state: ResolvedGuildState, squad: Squad, reopened: list[tuple[int, str]]
) -> None:
    """Undo the Discord side of a disband: `squad.role_id` is the freshly
    recreated squad role. Re-key the member channels off it and re-grant every
    reopened member their squad role + rank role (+ officer-channel overwrite
    for the Leader/Officers). The 4 channels themselves still exist — only
    their old role-scoped overwrites were lost when the role was deleted."""
    guild = state.guild
    role = guild.get_role(squad.role_id)
    if role is None:
        raise DiscordSetupError("The restored squad's role is missing on the server. Contact staff.")

    for channel_id in (squad.member_text_channel_id, squad.member_voice_channel_id):
        channel = guild.get_channel(channel_id)
        if channel is not None:
            try:
                await channel.set_permissions(role, view_channel=True, reason="Squad restored")
            except discord.DiscordException:
                logger.exception("Failed to re-permission channel %s on restore", channel_id)

    for user_id, squad_role_value in reopened:
        member = guild.get_member(user_id)
        if member is None:
            logger.warning("Restored squad %s: member %s is no longer in the server", squad.id, user_id)
            continue
        rank = SquadRole(squad_role_value)
        try:
            await member.add_roles(role, reason="Squad restored")
            await set_squad_rank_role(state, member, rank)
            if rank in (SquadRole.LEADER, SquadRole.OFFICER):
                await grant_officer_channel_access(state, squad, member)
        except discord.DiscordException:
            logger.exception("Failed to restore access for %s in squad %s", user_id, squad.id)


async def grant_squad_membership_access(state: ResolvedGuildState, squad: Squad, member: discord.Member) -> None:
    role = state.guild.get_role(squad.role_id)
    if role is None:
        raise DiscordSetupError("This squad's role is missing on the server. Contact staff.")
    await member.add_roles(role, reason="Joined squad")
    await set_squad_rank_role(state, member, SquadRole.MEMBER)


async def revoke_squad_membership_access(state: ResolvedGuildState, squad: Squad, member: discord.Member) -> None:
    guild = state.guild
    role = guild.get_role(squad.role_id)
    rank_roles = (state.roles.squad_leader, state.roles.squad_officer, state.roles.squad_member)
    to_remove = [r for r in ((role,) if role else ()) + rank_roles if r in member.roles]
    if to_remove:
        try:
            await member.remove_roles(*to_remove, reason="Left/removed from squad")
        except discord.DiscordException:
            logger.exception("Failed to remove squad roles from %s", member.id)
    await revoke_officer_channel_access(state, squad, member)


async def grant_officer_channel_access(state: ResolvedGuildState, squad: Squad, member: discord.Member) -> None:
    guild = state.guild
    for channel_id in (squad.officer_text_channel_id, squad.officer_voice_channel_id):
        channel = guild.get_channel(channel_id)
        if channel is None:
            raise DiscordSetupError("This squad's officer channel is missing on the server. Contact staff.")
        await channel.set_permissions(member, view_channel=True, reason="Promoted to officer/leader")


async def revoke_officer_channel_access(state: ResolvedGuildState, squad: Squad, member: discord.Member) -> None:
    guild = state.guild
    for channel_id in (squad.officer_text_channel_id, squad.officer_voice_channel_id):
        channel = guild.get_channel(channel_id)
        if channel is not None:
            try:
                await channel.set_permissions(member, overwrite=None, reason="Demoted/removed from officer role")
            except discord.DiscordException:
                logger.exception("Failed to revoke officer channel overwrite for %s on %s", member.id, channel_id)


async def set_squad_rank_role(state: ResolvedGuildState, member: discord.Member, rank: SquadRole) -> None:
    """Rank roles (Squad Leader/Officer/Member) are purely a cosmetic label —
    actual channel access is controlled by the squad-specific role and the
    per-member officer-channel overwrites above, not by these global roles."""
    rank_roles = {
        SquadRole.LEADER: state.roles.squad_leader,
        SquadRole.OFFICER: state.roles.squad_officer,
        SquadRole.MEMBER: state.roles.squad_member,
    }
    target_role = rank_roles[rank]
    to_remove = [r for key, r in rank_roles.items() if key is not rank and r in member.roles]
    if to_remove:
        try:
            await member.remove_roles(*to_remove, reason="Squad rank changed")
        except discord.DiscordException:
            logger.exception("Failed to remove old rank roles from %s", member.id)
    if target_role not in member.roles:
        await member.add_roles(target_role, reason="Squad rank changed")
