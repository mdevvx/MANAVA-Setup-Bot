"""MANAVA account-linking — the bot's read-only view of it.

Discord<->MANAVA linking/unlinking happens entirely in the main MANAVA
application (per gateway-diagram-en.html); the bot never performs a link. It
only needs two facts about a Discord user: their MANAVA player id (to attribute
incoming events) and whether they're a verified player (email confirmed — feeds
the squad-creation gate).

Resolution order:
  1. If Gateway mode is on, ask the Gateway (`GET /internal/identity/:discordId`)
     and cache the answer into personal_xp.
  2. Otherwise, or if the Gateway call fails, use the cached / manually-set
     personal_xp columns (`/admin set-verified`, `/admin link-manava-account`),
     which stay available as a support fallback either way.
"""

from __future__ import annotations

import logging

import asyncpg

from src.db.repositories import personal_xp as personal_xp_repo
from src.errors import GatewayError
from src.models.gateway import GatewayIdentity, LinkState
from src.services.gateway_client import GatewayClient

logger = logging.getLogger(__name__)


async def refresh_from_gateway(
    conn: asyncpg.Connection, gateway: GatewayClient | None, discord_user_id: int
) -> GatewayIdentity | None:
    """Query the Gateway for this user and cache manava_user_id + verified_player
    into personal_xp. Returns the identity, or None if Gateway mode is off or the
    call failed (caller falls back to cached values)."""
    if gateway is None or not gateway.enabled:
        return None
    try:
        identity = await gateway.get_identity(discord_user_id)
    except GatewayError as exc:
        logger.warning("Gateway identity lookup for %s failed, using cached data: %s", discord_user_id, exc)
        return None

    if identity.linked and identity.manava_user_id:
        await personal_xp_repo.set_manava_user_id(conn, discord_user_id, identity.manava_user_id)
    await personal_xp_repo.set_verified_player(conn, discord_user_id, identity.verified_player)
    return identity


async def link_state(
    conn: asyncpg.Connection, discord_user_id: int, *, gateway: GatewayClient | None = None
) -> LinkState:
    """Linked/verified status for the squad-creation gate. In Gateway mode this
    distinguishes "not linked" from "linked but email not verified" (the
    Gateway returns both facts). In stub mode only the cached `verified_player`
    boolean exists, so a failing check always reports NOT_VERIFIED."""
    identity = await refresh_from_gateway(conn, gateway, discord_user_id)
    if identity is not None:
        return identity.link_state
    cached = await personal_xp_repo.get_verified_player(conn, discord_user_id)
    return LinkState.OK if cached else LinkState.NOT_VERIFIED


async def is_verified(
    conn: asyncpg.Connection, discord_user_id: int, *, gateway: GatewayClient | None = None
) -> bool:
    """Boolean form of link_state — True only when linked AND email-verified."""
    return (await link_state(conn, discord_user_id, gateway=gateway)) is LinkState.OK


async def link_account(conn: asyncpg.Connection, discord_user_id: int, manava_user_id: str) -> None:
    """Manual override: record a Discord<->MANAVA id mapping directly (same as
    `/admin link-manava-account`). Support fallback only — normally this comes
    from the Gateway. Does not mark the user verified; that's a separate step."""
    await personal_xp_repo.set_manava_user_id(conn, discord_user_id, manava_user_id)


async def set_verified(conn: asyncpg.Connection, discord_user_id: int, verified: bool) -> None:
    """Manual verified-player override — support fallback that stays available
    even with Gateway mode on."""
    await personal_xp_repo.set_verified_player(conn, discord_user_id, verified)
