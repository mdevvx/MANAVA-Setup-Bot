from __future__ import annotations

import asyncpg
import discord

from src import constants
from src.db.repositories import memberships as memberships_repo
from src.db.repositories import personal_xp as xp_repo
from src.db.repositories import squads as squads_repo
from src.discord_state.role_resolver import ResolvedGuildState
from src.models.gateway import LinkState
from src.models.squad import EligibilityFailure, EligibilityResult
from src.services import account_linking
from src.services.gateway_client import GatewayClient

_LINK_FAILURE_MESSAGE = {
    LinkState.NOT_LINKED: "Link your MANAVA account first, then try again.",
    LinkState.NOT_VERIFIED: "Confirm your email in MANAVA to become a Verified Player, then try again.",
}


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
    gateway: GatewayClient | None = None,
) -> EligibilityResult:
    failures: list[EligibilityFailure] = []

    # Decision (2026-08-25): onboarding-complete collapses into "Member role present".
    if state.roles.member not in member.roles:
        failures.append(EligibilityFailure("member_role", "You need the **Member** role first."))

    lifetime_xp = await xp_repo.get_lifetime_xp(conn, member.id)
    if lifetime_xp < constants.WAVE_XP_GATE:
        failures.append(
            EligibilityFailure(
                "lifetime_xp",
                f"You need at least {constants.WAVE_XP_GATE} lifetime XP (you have {lifetime_xp}).",
            )
        )

    # Gateway mode: link_state() queries the MANAVA Gateway (and caches the
    # result) so we can tell "not linked" from "email not verified". Stub mode:
    # it reads the manual verified_player override and reports NOT_VERIFIED.
    state_result = await account_linking.link_state(conn, member.id, gateway=gateway)
    if state_result is not LinkState.OK:
        failures.append(
            EligibilityFailure("verified_player", _LINK_FAILURE_MESSAGE[state_result])
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
