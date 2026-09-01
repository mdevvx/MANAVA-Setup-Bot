"""Gateway identity lookup: payload mapping, and account_linking.is_verified
preferring the Gateway but falling back to cached values on failure or when
Gateway mode is off."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from src.errors import GatewayError
from src.models.gateway import GatewayIdentity, LinkState
from src.services import account_linking


def test_identity_from_payload_linked() -> None:
    ident = GatewayIdentity.from_payload(
        {"linked": True, "manavaUserId": "65a1f8", "verifiedPlayer": True}
    )
    assert ident == GatewayIdentity(linked=True, manava_user_id="65a1f8", verified_player=True)
    assert ident.link_state is LinkState.OK


def test_identity_from_payload_not_linked_blanks_other_fields() -> None:
    ident = GatewayIdentity.from_payload({"linked": False, "manavaUserId": "x", "verifiedPlayer": True})
    assert ident.linked is False
    assert ident.manava_user_id is None
    assert ident.verified_player is False
    assert ident.link_state is LinkState.NOT_LINKED


def test_link_state_distinguishes_unverified_from_unlinked() -> None:
    linked_unverified = GatewayIdentity.from_payload(
        {"linked": True, "manavaUserId": "m1", "verifiedPlayer": False}
    )
    assert linked_unverified.link_state is LinkState.NOT_VERIFIED


@pytest.mark.asyncio
async def test_is_verified_uses_gateway_and_caches(monkeypatch: pytest.MonkeyPatch) -> None:
    gateway = AsyncMock()
    gateway.enabled = True
    gateway.get_identity = AsyncMock(
        return_value=GatewayIdentity(linked=True, manava_user_id="m-1", verified_player=True)
    )
    set_manava = AsyncMock()
    set_verified = AsyncMock()
    monkeypatch.setattr(account_linking.personal_xp_repo, "set_manava_user_id", set_manava)
    monkeypatch.setattr(account_linking.personal_xp_repo, "set_verified_player", set_verified)
    monkeypatch.setattr(account_linking.personal_xp_repo, "get_verified_player", AsyncMock(return_value=False))

    result = await account_linking.is_verified(object(), 123, gateway=gateway)  # type: ignore[arg-type]

    assert result is True
    set_manava.assert_awaited_once()
    set_verified.assert_awaited_once()


@pytest.mark.asyncio
async def test_is_verified_falls_back_to_cache_on_gateway_error(monkeypatch: pytest.MonkeyPatch) -> None:
    gateway = AsyncMock()
    gateway.enabled = True
    gateway.get_identity = AsyncMock(side_effect=GatewayError("boom"))
    monkeypatch.setattr(account_linking.personal_xp_repo, "get_verified_player", AsyncMock(return_value=True))

    result = await account_linking.is_verified(object(), 123, gateway=gateway)  # type: ignore[arg-type]
    assert result is True  # from the cached column


@pytest.mark.asyncio
async def test_is_verified_stub_mode_when_no_gateway(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(account_linking.personal_xp_repo, "get_verified_player", AsyncMock(return_value=False))
    result = await account_linking.is_verified(object(), 123, gateway=None)  # type: ignore[arg-type]
    assert result is False


@pytest.mark.asyncio
async def test_link_state_reports_not_verified_from_gateway(monkeypatch: pytest.MonkeyPatch) -> None:
    gateway = AsyncMock()
    gateway.enabled = True
    gateway.get_identity = AsyncMock(
        return_value=GatewayIdentity(linked=True, manava_user_id="m1", verified_player=False)
    )
    monkeypatch.setattr(account_linking.personal_xp_repo, "set_manava_user_id", AsyncMock())
    monkeypatch.setattr(account_linking.personal_xp_repo, "set_verified_player", AsyncMock())

    state = await account_linking.link_state(object(), 1, gateway=gateway)  # type: ignore[arg-type]
    assert state is LinkState.NOT_VERIFIED


@pytest.mark.asyncio
async def test_link_state_reports_not_linked_from_gateway(monkeypatch: pytest.MonkeyPatch) -> None:
    gateway = AsyncMock()
    gateway.enabled = True
    gateway.get_identity = AsyncMock(
        return_value=GatewayIdentity(linked=False, manava_user_id=None, verified_player=False)
    )
    monkeypatch.setattr(account_linking.personal_xp_repo, "set_verified_player", AsyncMock())

    state = await account_linking.link_state(object(), 1, gateway=gateway)  # type: ignore[arg-type]
    assert state is LinkState.NOT_LINKED
