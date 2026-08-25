from __future__ import annotations

import logging
from dataclasses import dataclass

import discord

from src import constants
from src.errors import DiscordSetupError

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ResolvedRoles:
    admin: discord.Role
    manava_team: discord.Role
    senior_moderator: discord.Role
    moderator: discord.Role
    squad_leader: discord.Role
    squad_officer: discord.Role
    squad_member: discord.Role
    member: discord.Role

    @property
    def staff_roles(self) -> tuple[discord.Role, ...]:
        return (self.admin, self.manava_team, self.senior_moderator, self.moderator)

    @property
    def protected_role_ids(self) -> frozenset[int]:
        return frozenset({self.admin.id, self.manava_team.id, self.senior_moderator.id, self.moderator.id})


@dataclass(frozen=True, slots=True)
class ResolvedGuildState:
    guild: discord.Guild
    roles: ResolvedRoles
    squad_categories: tuple[discord.CategoryChannel, ...]

    def ensure_assignable(self, role: discord.Role) -> None:
        """Hard guard: refuse to grant any protected staff role, even if calling code has a bug."""
        if role.id in self.roles.protected_role_ids:
            raise DiscordSetupError(
                f"Refused to assign protected role '{role.name}' — this is a bot safety guard, not user error."
            )


def _find_role_ci(guild: discord.Guild, name: str) -> discord.Role | None:
    target = name.casefold()
    return discord.utils.find(lambda r: r.name.casefold() == target, guild.roles)


def _find_category_ci(guild: discord.Guild, name: str) -> discord.CategoryChannel | None:
    target = name.casefold()
    return discord.utils.find(lambda c: c.name.casefold() == target, guild.categories)


def resolve_guild_state(guild: discord.Guild) -> ResolvedGuildState:
    """Resolve all Discord objects the bot needs by case-insensitive exact name
    lookup at startup (case-insensitive since real server role/category casing
    doesn't always match a written spec exactly — this isn't fuzzy matching,
    still a full match, just casing-tolerant).

    Raises DiscordSetupError (and logs loudly) if anything required is missing,
    rather than failing per-command later. Callers should disable squad-related
    features entirely when this raises.
    """
    missing: list[str] = []
    resolved_roles: dict[str, discord.Role] = {}

    for name in constants.ALL_RESOLVED_ROLE_NAMES:
        role = _find_role_ci(guild, name)
        if role is None:
            missing.append(f"role '{name}'")
        else:
            resolved_roles[name] = role

    categories: list[discord.CategoryChannel] = []
    for name in constants.SQUAD_CATEGORY_NAMES:
        category = _find_category_ci(guild, name)
        if category is None:
            missing.append(f"category '{name}'")
        else:
            categories.append(category)

    if missing:
        message = "Missing required Discord roles/categories: " + ", ".join(missing)
        logger.error(message)
        raise DiscordSetupError(message)

    roles = ResolvedRoles(
        admin=resolved_roles[constants.ROLE_NAME_ADMIN],
        manava_team=resolved_roles[constants.ROLE_NAME_MANAVA_TEAM],
        senior_moderator=resolved_roles[constants.ROLE_NAME_SENIOR_MODERATOR],
        moderator=resolved_roles[constants.ROLE_NAME_MODERATOR],
        squad_leader=resolved_roles[constants.ROLE_NAME_SQUAD_LEADER],
        squad_officer=resolved_roles[constants.ROLE_NAME_SQUAD_OFFICER],
        squad_member=resolved_roles[constants.ROLE_NAME_SQUAD_MEMBER],
        member=resolved_roles[constants.ROLE_NAME_MEMBER],
    )
    return ResolvedGuildState(guild=guild, roles=roles, squad_categories=tuple(categories))
