from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class LinkState(str, Enum):
    """Outcome of an identity check, mapped to what the applicant should be told
    (see the Gateway's identity-check.md)."""

    OK = "ok"  # linked and email-verified — proceed
    NOT_LINKED = "not_linked"  # tell them to link their MANAVA account
    NOT_VERIFIED = "not_verified"  # linked, but email not confirmed


@dataclass(frozen=True, slots=True)
class GatewayIdentity:
    """Response of GET /internal/identity/:discordId.

    Discord<->MANAVA account linking happens in the main MANAVA application, not
    the Gateway and not this bot — this is a read-only status lookup.
    """

    linked: bool
    manava_user_id: str | None
    verified_player: bool

    @classmethod
    def from_payload(cls, payload: dict[str, object]) -> "GatewayIdentity":
        linked = bool(payload.get("linked"))
        raw_id = payload.get("manavaUserId")
        return cls(
            linked=linked,
            manava_user_id=str(raw_id) if linked and raw_id else None,
            verified_player=bool(payload.get("verifiedPlayer")) if linked else False,
        )

    @property
    def link_state(self) -> LinkState:
        if not self.linked:
            return LinkState.NOT_LINKED
        return LinkState.OK if self.verified_player else LinkState.NOT_VERIFIED
