from __future__ import annotations

from types import SimpleNamespace

from src.discord_state.xp_channel_filter import is_message_xp_eligible, is_within_cooldown


def test_no_prior_grant_is_never_on_cooldown() -> None:
    assert is_within_cooldown(None, now_monotonic=1000.0, cooldown_seconds=60) is False


def test_blocked_within_cooldown_window() -> None:
    assert is_within_cooldown(1000.0, now_monotonic=1030.0, cooldown_seconds=60) is True


def test_allowed_once_cooldown_elapses() -> None:
    assert is_within_cooldown(1000.0, now_monotonic=1061.0, cooldown_seconds=60) is False


def test_allowed_exactly_at_boundary() -> None:
    # now - last == cooldown exactly: not LESS than cooldown, so allowed.
    assert is_within_cooldown(1000.0, now_monotonic=1060.0, cooldown_seconds=60) is False


def _fake_message(channel_id: int, category_id: int | None) -> SimpleNamespace:
    category = SimpleNamespace(id=category_id) if category_id is not None else None
    channel = SimpleNamespace(id=channel_id, category=category)
    return SimpleNamespace(channel=channel)


def test_channel_directly_excluded() -> None:
    message = _fake_message(channel_id=111, category_id=222)
    assert is_message_xp_eligible(message, excluded_channel_ids={111}) is False  # type: ignore[arg-type]


def test_category_excluded_blocks_channel_inside_it() -> None:
    message = _fake_message(channel_id=111, category_id=222)
    assert is_message_xp_eligible(message, excluded_channel_ids={222}) is False  # type: ignore[arg-type]


def test_unrelated_exclusions_do_not_block() -> None:
    message = _fake_message(channel_id=111, category_id=222)
    assert is_message_xp_eligible(message, excluded_channel_ids={999}) is True  # type: ignore[arg-type]


def test_no_category_and_not_excluded_is_eligible() -> None:
    message = _fake_message(channel_id=111, category_id=None)
    assert is_message_xp_eligible(message, excluded_channel_ids=set()) is True  # type: ignore[arg-type]
