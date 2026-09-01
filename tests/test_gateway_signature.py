"""Inbound webhook auth: HMAC-SHA256 x-manava-signature verification, with the
legacy bearer token as a fallback only when no signing secret is configured."""

from __future__ import annotations

import hashlib
import hmac
from types import SimpleNamespace

from src.web.webhook_server import ManavaWebhookServer


def _server(*, signing_secret: str | None = None, legacy_secret: str | None = None) -> ManavaWebhookServer:
    config = SimpleNamespace(
        webhook_signing_secret=signing_secret,
        manava_webhook_secret=legacy_secret,
        webhook_port=8080,
    )
    return ManavaWebhookServer(SimpleNamespace(config=config))  # type: ignore[arg-type]


def _req(headers: dict[str, str]) -> SimpleNamespace:
    return SimpleNamespace(headers=headers)


def _sign(secret: str, body: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def test_valid_signature_passes() -> None:
    body = b'{"eventId":"e1"}'
    server = _server(signing_secret="topsecret")
    assert server._authenticate(body, _req({"x-manava-signature": _sign("topsecret", body)})) is True


def test_tampered_body_fails() -> None:
    server = _server(signing_secret="topsecret")
    good_sig = _sign("topsecret", b'{"eventId":"e1"}')
    assert server._authenticate(b'{"eventId":"e1","x":1}', _req({"x-manava-signature": good_sig})) is False


def test_wrong_secret_fails() -> None:
    body = b'{"eventId":"e1"}'
    server = _server(signing_secret="topsecret")
    assert server._authenticate(body, _req({"x-manava-signature": _sign("different", body)})) is False


def test_missing_signature_header_fails() -> None:
    server = _server(signing_secret="topsecret")
    assert server._authenticate(b"{}", _req({})) is False


def test_legacy_bearer_used_only_without_signing_secret() -> None:
    server = _server(legacy_secret="legacy123")
    assert server._authenticate(b"{}", _req({"Authorization": "Bearer legacy123"})) is True
    assert server._authenticate(b"{}", _req({"Authorization": "Bearer nope"})) is False


def test_signing_secret_takes_precedence_over_legacy() -> None:
    body = b"{}"
    server = _server(signing_secret="sign", legacy_secret="legacy123")
    # A correct legacy bearer is ignored once a signing secret exists.
    assert server._authenticate(body, _req({"Authorization": "Bearer legacy123"})) is False
    assert server._authenticate(body, _req({"x-manava-signature": _sign("sign", body)})) is True


def test_matches_gateway_signpayload_wire_format() -> None:
    """Mirrors the MANAVA Gateway's hmac-signer.ts exactly:
        'sha256=' + createHmac('sha256', secret).update(rawBody).digest('hex')
    over the JSON string it POSTs. We must verify that byte-for-byte."""
    secret = "shared-webhook-secret"
    # A realistic tournament_placement body as the Gateway would serialise it.
    raw = (
        b'{"eventId":"trn-place:t4501:u65a1f8","eventType":"tournament_placement",'
        b'"manavaUserId":"65a1f8c9e4b0d2f3a1234567","game":"swag",'
        b'"timestamp":"2026-08-27T21:45:20.000Z","tournamentId":"trn-4501",'
        b'"place":3,"wonPrizeSlot":true}'
    )
    gateway_sig = "sha256=" + hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()

    server = _server(signing_secret=secret)
    assert server._authenticate(raw, _req({"x-manava-signature": gateway_sig})) is True
    # Any change to the bytes we hash breaks it (e.g. re-serialising with spaces).
    assert server._authenticate(raw + b" ", _req({"x-manava-signature": gateway_sig})) is False
