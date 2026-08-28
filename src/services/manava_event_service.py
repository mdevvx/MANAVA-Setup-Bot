"""The MANAVA event processing pipeline, exactly the sequence from the spec:
authenticate (web layer, before this module) -> validate payload shape ->
check event_id against processed_events -> reject if duplicate -> resolve
linked Discord user -> apply configured XP -> update Personal Lifetime/Season
XP -> update Squad Lifetime/Season XP if in a squad -> persist event_id as
processed -> log.

"Refresh cached leaderboard state" from the spec is a no-op here: leaderboard
queries run live against indexed tables rather than through a cache layer,
which is efficient enough at the ~70-squad scale this needs to support.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

import asyncpg

from src import constants
from src.db.repositories import audit_logs as audit_repo
from src.db.repositories import personal_xp as personal_xp_repo
from src.db.repositories import processed_events as processed_events_repo
from src.db.repositories import xp_config as xp_config_repo
from src.models.xp import ManavaEvent, ManavaEventOutcome, ManavaEventValidationError
from src.services import xp_service

logger = logging.getLogger(__name__)

_REQUIRED_FIELDS = ("event_id", "manava_user_id", "event_type", "game", "timestamp")


def parse_event(raw: dict[str, Any]) -> ManavaEvent | ManavaEventValidationError:
    """Validates payload shape per the spec's minimum field list. Returns a
    validated ManavaEvent, or a ManavaEventValidationError describing what's wrong."""
    missing = [f for f in _REQUIRED_FIELDS if not raw.get(f)]
    if missing:
        return ManavaEventValidationError(f"Missing required field(s): {', '.join(missing)}")

    event_type = raw["event_type"]
    if event_type not in constants.ALL_MANAVA_EVENT_TYPES:
        return ManavaEventValidationError(
            f"Unknown event_type {event_type!r}. Expected one of: {', '.join(constants.ALL_MANAVA_EVENT_TYPES)}"
        )

    raw_timestamp = raw["timestamp"]
    if not isinstance(raw_timestamp, str):
        return ManavaEventValidationError("timestamp must be an ISO-8601 string")
    try:
        timestamp = datetime.fromisoformat(raw_timestamp.replace("Z", "+00:00"))
    except ValueError:
        return ManavaEventValidationError("timestamp is not valid ISO-8601")

    placement_raw = raw.get("placement")
    placement: int | None = None
    if placement_raw is not None:
        try:
            placement = int(placement_raw)
        except (TypeError, ValueError):
            return ManavaEventValidationError("placement must be an integer if provided")

    return ManavaEvent(
        event_id=str(raw["event_id"]),
        manava_user_id=str(raw["manava_user_id"]),
        event_type=event_type,
        game=str(raw["game"]),
        timestamp=timestamp,
        match_id=str(raw["match_id"]) if raw.get("match_id") is not None else None,
        tournament_id=str(raw["tournament_id"]) if raw.get("tournament_id") is not None else None,
        result=str(raw["result"]) if raw.get("result") is not None else None,
        placement=placement,
    )


async def _compute_xp(conn: asyncpg.Connection, event: ManavaEvent) -> int:
    config = await xp_config_repo.get_all(conn)
    if event.event_type == constants.MANAVA_EVENT_SKILL_MATCH_COMPLETED:
        return config.get(constants.XP_CONFIG_KEY_SKILL_MATCH, 0)

    if event.event_type == constants.MANAVA_EVENT_TOURNAMENT_PARTICIPATED:
        return config.get(constants.XP_CONFIG_KEY_TOURNAMENT_PARTICIPATION, 0)

    if event.event_type == constants.MANAVA_EVENT_TOURNAMENT_PLACEMENT:
        base = config.get(constants.XP_CONFIG_KEY_TOURNAMENT_PARTICIPATION, 0)
        bonus_key = {
            1: constants.XP_CONFIG_KEY_PLACEMENT_1ST,
            2: constants.XP_CONFIG_KEY_PLACEMENT_2ND,
            3: constants.XP_CONFIG_KEY_PLACEMENT_3RD,
        }.get(event.placement or 0)
        bonus = config.get(bonus_key, 0) if bonus_key else 0
        return base + bonus

    return 0


async def process_event(conn: asyncpg.Connection, event: ManavaEvent) -> ManavaEventOutcome:
    # Dedupe FIRST, before any XP is computed or granted — this is what makes
    # a retried/duplicate event_id a hard-guaranteed no-op, not just "unlikely".
    claimed = await processed_events_repo.reserve(
        conn, event_id=event.event_id, manava_user_id=event.manava_user_id, event_type=event.event_type
    )
    if not claimed:
        logger.info("Duplicate MANAVA event %s rejected (already processed)", event.event_id)
        return ManavaEventOutcome(event_id=event.event_id, status="duplicate", xp_granted=0, discord_user_id=None)

    discord_user_id = await personal_xp_repo.get_discord_user_id_by_manava_id(conn, event.manava_user_id)
    if discord_user_id is None:
        logger.warning(
            "MANAVA event %s: manava_user_id=%s has no linked Discord account — no XP granted",
            event.event_id,
            event.manava_user_id,
        )
        await processed_events_repo.finalize(conn, event_id=event.event_id, discord_user_id=None, xp_granted=0)
        return ManavaEventOutcome(
            event_id=event.event_id, status="unresolved_user", xp_granted=0, discord_user_id=None
        )

    xp_amount = await _compute_xp(conn, event)
    if xp_amount > 0:
        await xp_service.grant_personal_xp(conn, discord_user_id, xp_amount)

    await processed_events_repo.finalize(
        conn, event_id=event.event_id, discord_user_id=discord_user_id, xp_granted=xp_amount
    )
    await audit_repo.record(
        conn,
        actor_id=discord_user_id,
        action="manava_event.processed",
        target_type="manava_event",
        target_id=event.event_id,
        new_value={"event_type": event.event_type, "xp_granted": xp_amount, "game": event.game},
    )
    logger.info("Processed MANAVA event %s: granted %s XP to %s", event.event_id, xp_amount, discord_user_id)
    return ManavaEventOutcome(
        event_id=event.event_id, status="processed", xp_granted=xp_amount, discord_user_id=discord_user_id
    )
