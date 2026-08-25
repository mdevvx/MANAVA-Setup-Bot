from __future__ import annotations

import asyncpg
import discord

from src import constants
from src.db.repositories import memberships as memberships_repo
from src.db.repositories import personal_xp as xp_repo
from src.db.repositories import squads as squads_repo
from src.discord_state.role_resolver import ResolvedGuildState
from src.models.squad import EligibilityFailure, EligibilityResult


def validate_squad_name(name: str) -> str | None:
    """Returns a human-readable error reason if invalid, otherwise None."""
    stripped = name.strip()
    if not (constants.SQUAD_NAME_MIN_LEN <= len(stripped) <= constants.SQUAD_NAME_MAX_LEN):
        return f"must be between {constants.SQUAD_NAME_MIN_LEN} and {constants.SQUAD_NAME_MAX_LEN} characters"
    if not constants.SQUAD_NAME_PATTERN.match(stripped):
        return "can only contain letters, numbers, spaces, hyphens, and underscores"
    return None


async def check_eligibility(
    conn: asyncpg.Connection,
    *,
    member: discord.Member,
    state: ResolvedGuildState,
    squad_name: str,
) -> EligibilityResult:
    failures: list[EligibilityFailure] = []

    # Decision (2026-08-25): onboarding-complete collapses into "Member role present".
    if state.roles.member not in member.roles:
        failures.append(EligibilityFailure("member_role", "You need the **Member** role first."))

    # STUB: replaced by full Unified XP system in Phase 2
    lifetime_xp = await xp_repo.get_lifetime_xp(conn, member.id)
    if lifetime_xp < constants.WAVE_XP_GATE:
        failures.append(
            EligibilityFailure(
                "lifetime_xp",
                f"You need at least {constants.WAVE_XP_GATE} lifetime XP (you have {lifetime_xp}).",
            )
        )

    # STUB: replaced by MANAVA account-linking integration in Phase 3
    verified = await xp_repo.get_verified_player(conn, member.id)
    if not verified:
        failures.append(
            EligibilityFailure("verified_player", "Your MANAVA account must be verified/linked first.")
        )

    existing_membership = await memberships_repo.get_active_membership(conn, member.id)
    if existing_membership is not None:
        failures.append(
            EligibilityFailure(
                "already_in_squad", "You're already in a squad. Leave it before creating a new one."
            )
        )

    name_reason = validate_squad_name(squad_name)
    if name_reason is not None:
        failures.append(EligibilityFailure("invalid_name", f"Squad name {name_reason}."))
    elif await squads_repo.name_is_taken(conn, squad_name.strip()):
        failures.append(
            EligibilityFailure("duplicate_name", f"A squad named **{squad_name.strip()}** already exists.")
        )

    return EligibilityResult(eligible=not failures, failures=tuple(failures))
