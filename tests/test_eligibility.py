from __future__ import annotations

import pytest

from src.models.gateway import LinkState
from src.services.squad_eligibility import _link_failure_message, validate_squad_name


@pytest.mark.parametrize(
    "name,should_be_valid",
    [
        ("Alpha", True),
        ("Team 3X", True),
        ("Team_3X-9", True),
        ("abc", True),
        ("x" * 32, True),
        ("ab", False),  # too short
        ("x" * 33, False),  # too long
        ("Team!", False),  # invalid char
        ("Team#3", False),
        ("", False),
        ("   ", False),  # whitespace-only strips to empty
    ],
)
def test_validate_squad_name(name: str, should_be_valid: bool) -> None:
    reason = validate_squad_name(name)
    assert (reason is None) == should_be_valid


def test_link_failure_message_includes_url_when_configured() -> None:
    url = "https://app.manava.io/settings/connections"

    not_linked = _link_failure_message(LinkState.NOT_LINKED, url)
    assert "Link your MANAVA account" in not_linked and url in not_linked

    not_verified = _link_failure_message(LinkState.NOT_VERIFIED, url)
    assert "Confirm your email" in not_verified and url in not_verified

    # No URL configured -> generic wording, no stray parens/URL.
    generic = _link_failure_message(LinkState.NOT_LINKED, None)
    assert "http" not in generic and "()" not in generic
