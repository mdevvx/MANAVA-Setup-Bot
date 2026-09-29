"""Ocean Masters channel lookup must tolerate the live server's decorated names
("🌊丨ocean-masters-info") without confusing the language variants
("🌊ua丨ocean-masters-info-ua")."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from src.discord_state.ocean_masters_setup import resolve_ocean_masters_channels
from src.errors import DiscordSetupError


def _guild(*names: str) -> Any:
    channels = [SimpleNamespace(id=i, name=n) for i, n in enumerate(names)]
    return SimpleNamespace(text_channels=channels)


# Exact stored names fetched from the live guild 2026-09-29 (separator is
# U+3021 "〡", language variants use regional-indicator flag emoji).
LIVE_NAMES = (
    "\U0001f30a〡ocean-masters-info",
    "\U0001f30a\U0001f1fa\U0001f1e6〡ocean-masters-info-ua",
    "\U0001f30a\U0001f1f7\U0001f1fa〡ocean-masters-info-ru",
    "\U0001f30a\U0001f1e9\U0001f1ea〡ocean-masters-info-de",
    "\U0001f30a\U0001f1ea\U0001f1f8〡ocean-masters-info-es",
    "\U0001f4ef〡premier-news",
    "\U0001f3df️〡premier-brackets",
    "\U0001f4dc〡premier-history",
)


def test_resolves_decorated_live_names() -> None:
    state = resolve_ocean_masters_channels(_guild(*LIVE_NAMES))
    assert state.info.name == LIVE_NAMES[0]
    assert state.news.name == "\U0001f4ef〡premier-news"
    assert state.brackets.name == "\U0001f3df️〡premier-brackets"
    assert state.history.name == "\U0001f4dc〡premier-history"


def test_plain_names_still_resolve() -> None:
    state = resolve_ocean_masters_channels(
        _guild("ocean-masters-info", "premier-news", "premier-brackets", "premier-history")
    )
    assert state.news.name == "premier-news"


def test_exact_match_wins_over_decorated() -> None:
    state = resolve_ocean_masters_channels(
        _guild(
            "ocean-masters-info", "premier-news", "📣丨premier-news",
            "premier-brackets", "premier-history",
        )
    )
    assert state.news.name == "premier-news"


def test_language_variant_alone_does_not_count() -> None:
    with pytest.raises(DiscordSetupError, match="ocean-masters-info"):
        resolve_ocean_masters_channels(
            _guild("🌊ua丨ocean-masters-info-ua", "premier-news", "premier-brackets", "premier-history")
        )


def test_hyphenated_superset_does_not_match() -> None:
    with pytest.raises(DiscordSetupError, match="premier-news"):
        resolve_ocean_masters_channels(
            _guild("ocean-masters-info", "old-premier-news", "premier-brackets", "premier-history")
        )


def test_two_decorated_candidates_is_ambiguous() -> None:
    with pytest.raises(DiscordSetupError, match="Ambiguous"):
        resolve_ocean_masters_channels(
            _guild(
                "ocean-masters-info", "📣丨premier-news", "🗞丨premier-news",
                "premier-brackets", "premier-history",
            )
        )


def _channel(name: str, *, view: bool = True, send: bool = True) -> Any:
    perms = SimpleNamespace(view_channel=view, send_messages=send)
    return SimpleNamespace(
        name=name, mention=f"<#{name}>", guild=SimpleNamespace(me=object()),
        permissions_for=lambda _m: perms,
    )


def test_admin_status_lines_report_error_when_unresolved() -> None:
    from src.cogs.admin import _ocean_masters_channel_lines

    bot: Any = SimpleNamespace(ocean_masters_state=None, ocean_masters_error="Missing required Ocean Masters channels: #premier-news")
    assert _ocean_masters_channel_lines(bot) == "❌ Missing required Ocean Masters channels: #premier-news"


def test_admin_status_lines_report_per_channel_permissions() -> None:
    from src.cogs.admin import _ocean_masters_channel_lines
    from src.discord_state.ocean_masters_setup import ResolvedOceanMastersState

    state = ResolvedOceanMastersState(
        info=_channel("info", send=False),
        news=_channel("news"),
        brackets=_channel("brackets", send=False),
        history=_channel("history", view=False, send=False),
    )
    lines = _ocean_masters_channel_lines(SimpleNamespace(ocean_masters_state=state)).splitlines()  # type: ignore[arg-type]
    assert lines == [
        "Info → <#info> · static, not posted to",
        "News → <#news> · ✅ can post",
        "Brackets → <#brackets> · ⚠️ missing Send Messages",
        "History → <#history> · ⚠️ missing View Channel, Send Messages",
    ]
