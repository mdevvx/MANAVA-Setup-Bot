from __future__ import annotations

import pytest

from src.services.squad_eligibility import validate_squad_name


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
