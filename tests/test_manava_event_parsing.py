"""parse_event accepts the MANAVA Gateway's camelCase payloads, normalises the
renamed event types, and pulls out place / wonPrizeSlot."""

from __future__ import annotations

from src import constants
from src.models.xp import ManavaEvent, ManavaEventValidationError
from src.services.manava_event_service import parse_event


def test_parses_gateway_match_completed_payload() -> None:
    out = parse_event(
        {
            "eventId": "cs2:match-end:srv7:9182",
            "eventType": "match_completed",
            "manavaUserId": "65a1f8c9e4b0d2f3a1234567",
            "game": "cs2",
            "timestamp": "2026-08-27T18:04:33.000Z",
            "matchId": "cs2-match-9182",
        }
    )
    assert isinstance(out, ManavaEvent)
    assert out.event_id == "cs2:match-end:srv7:9182"
    assert out.event_type == constants.MANAVA_EVENT_MATCH_COMPLETED
    assert out.manava_user_id == "65a1f8c9e4b0d2f3a1234567"
    assert out.match_id == "cs2-match-9182"


def test_parses_gateway_placement_payload_with_prize_slot() -> None:
    out = parse_event(
        {
            "eventId": "trn-place:t4501:u65a1f8",
            "eventType": "tournament_placement",
            "manavaUserId": "65a1f8c9e4b0d2f3a1234567",
            "game": "swag",
            "timestamp": "2026-08-27T21:45:20.000Z",
            "tournamentId": "trn-4501",
            "place": 3,
            "wonPrizeSlot": True,
        }
    )
    assert isinstance(out, ManavaEvent)
    assert out.place == 3
    assert out.won_prize_slot is True
    assert out.tournament_id == "trn-4501"


def test_parses_tournament_participated_payload() -> None:
    """The "actual participation" event (client decision, 2026-09-16; live on
    MANAVA's side 2026-09-16 as tournament_participated) — fires once per
    player, right before tournament_placement, for players who played the
    tournament to the end."""
    out = parse_event(
        {
            "eventId": "trn-part:t4501:u65a1f8",
            "eventType": "tournament_participated",
            "manavaUserId": "65a1f8c9e4b0d2f3a1234567",
            "game": "swag",
            "timestamp": "2026-08-27T20:00:00.000Z",
            "tournamentId": "trn-4501",
        }
    )
    assert isinstance(out, ManavaEvent)
    assert out.event_type == constants.MANAVA_EVENT_TOURNAMENT_PARTICIPATED


def test_legacy_tournament_completed_placeholder_still_normalises() -> None:
    """"tournament_completed" was this codebase's placeholder name before the
    real event went live — kept as an accepted alias, still normalises to the
    same canonical type."""
    out = parse_event(
        {
            "eventId": "e1",
            "eventType": "tournament_completed",
            "manavaUserId": "m1",
            "game": "swag",
            "timestamp": "2026-08-27T20:00:00.000Z",
        }
    )
    assert isinstance(out, ManavaEvent)
    assert out.event_type == constants.MANAVA_EVENT_TOURNAMENT_PARTICIPATED


def test_legacy_snake_case_and_renamed_types_still_accepted() -> None:
    out = parse_event(
        {
            "event_id": "e1",
            "event_type": "skill_match_completed",  # legacy alias
            "manava_user_id": "m1",
            "game": "cs2",
            "timestamp": "2026-08-27T18:04:33Z",
        }
    )
    assert isinstance(out, ManavaEvent)
    assert out.event_type == constants.MANAVA_EVENT_MATCH_COMPLETED


def test_missing_required_field_is_rejected() -> None:
    out = parse_event({"eventType": "match_completed", "game": "cs2", "timestamp": "2026-08-27T18:04:33Z"})
    assert isinstance(out, ManavaEventValidationError)
    assert "eventId" in out.reason and "manavaUserId" in out.reason


def test_unknown_event_type_is_rejected() -> None:
    out = parse_event(
        {
            "eventId": "e1",
            "eventType": "player_banned",
            "manavaUserId": "m1",
            "game": "cs2",
            "timestamp": "2026-08-27T18:04:33Z",
        }
    )
    assert isinstance(out, ManavaEventValidationError)
