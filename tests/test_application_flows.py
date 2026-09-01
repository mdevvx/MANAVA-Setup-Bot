"""Application workflow: submit records history + audit (no PII in audit),
approve/reject are one-way, the more-info round-trip attaches to the same
record, and approval role mapping is correct."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from src.errors import (
    ApplicationAlreadyDecidedError,
    ApplicationNotFoundError,
    BotUserError,
    DuplicateApplicationError,
)
from src.models.application import Application, AppStatus, AppType
from src.services import application_service


class _FakeTxn:
    async def __aenter__(self) -> "_FakeTxn":
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None


class _FakeConn:
    def transaction(self) -> _FakeTxn:
        return _FakeTxn()


def _app(
    *,
    status: AppStatus = AppStatus.PENDING,
    app_type: AppType = AppType.DEVELOPER,
    fields: dict[str, str] | None = None,
    applicant_id: int = 1,
) -> Application:
    return Application(
        id=uuid4(),
        applicant_id=applicant_id,
        applicant_username="user#1",
        app_type=app_type,
        status=status,
        fields=fields or {"contact_email": "a@b.com"},
        review_channel_id=None,
        review_message_id=None,
        submitted_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        decided_at=None,
        decided_by=None,
    )


_VALID_DEV_FIELDS = {
    "company_studio": "ACME",
    "project_game": "Widget Wars",
    "website_url": "https://acme.example",
    "integration_interest": "API integration",
    "relevant_experience": "shipped things",
    "contact_email": "secret@example.com",
}


@pytest.mark.asyncio
async def test_submit_records_history_and_keeps_pii_out_of_audit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(application_service.applications_repo, "get_active_for_user", AsyncMock(return_value=None))
    monkeypatch.setattr(application_service.applications_repo, "last_rejection", AsyncMock(return_value=None))
    monkeypatch.setattr(application_service.applications_repo, "insert", AsyncMock(return_value=_app()))
    history = AsyncMock()
    audit = AsyncMock()
    monkeypatch.setattr(application_service.history_repo, "record", history)
    monkeypatch.setattr(application_service.audit_repo, "record", audit)

    await application_service.submit(
        _FakeConn(),  # type: ignore[arg-type]
        applicant_id=1,
        applicant_username="user#1",
        app_type=AppType.DEVELOPER,
        fields=dict(_VALID_DEV_FIELDS),
    )

    _, hk = history.await_args
    assert hk["new_status"] is AppStatus.PENDING
    assert hk["actor_role"].value == "applicant"

    _, ak = audit.await_args
    assert "secret@example.com" not in str(ak)
    assert "ACME" not in str(ak)


@pytest.mark.asyncio
async def test_submit_rejects_bad_email_and_creates_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(application_service.applications_repo, "get_active_for_user", AsyncMock(return_value=None))
    monkeypatch.setattr(application_service.applications_repo, "last_rejection", AsyncMock(return_value=None))
    insert = AsyncMock()
    monkeypatch.setattr(application_service.applications_repo, "insert", insert)
    monkeypatch.setattr(application_service.history_repo, "record", AsyncMock())
    monkeypatch.setattr(application_service.audit_repo, "record", AsyncMock())

    for bad in (
        dict(_VALID_DEV_FIELDS, contact_email="nope-not-an-email"),
        dict(_VALID_DEV_FIELDS, website_url="just-text"),
    ):
        with pytest.raises(BotUserError):
            await application_service.submit(
                _FakeConn(),  # type: ignore[arg-type]
                applicant_id=1,
                applicant_username="user#1",
                app_type=AppType.DEVELOPER,
                fields=bad,
            )
    insert.assert_not_awaited()


@pytest.mark.asyncio
async def test_submit_blocked_by_existing_active(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        application_service.applications_repo, "get_active_for_user", AsyncMock(return_value=_app())
    )
    with pytest.raises(DuplicateApplicationError):
        await application_service.submit(
            _FakeConn(),  # type: ignore[arg-type]
            applicant_id=1,
            applicant_username="user#1",
            app_type=AppType.DEVELOPER,
            fields={},
        )


@pytest.mark.asyncio
async def test_approve_is_one_way(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(application_service.history_repo, "record", AsyncMock())
    monkeypatch.setattr(application_service.audit_repo, "record", AsyncMock())
    monkeypatch.setattr(
        application_service.applications_repo,
        "set_status",
        AsyncMock(return_value=_app(status=AppStatus.APPROVED)),
    )

    pending = _app(status=AppStatus.PENDING)
    monkeypatch.setattr(application_service.applications_repo, "get", AsyncMock(return_value=pending))
    updated = await application_service.approve(_FakeConn(), application_id=pending.id, reviewer_id=7)  # type: ignore[arg-type]
    assert updated.status is AppStatus.APPROVED

    monkeypatch.setattr(
        application_service.applications_repo, "get", AsyncMock(return_value=_app(status=AppStatus.APPROVED))
    )
    with pytest.raises(ApplicationAlreadyDecidedError):
        await application_service.approve(_FakeConn(), application_id=pending.id, reviewer_id=7)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_more_info_round_trip(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(application_service.history_repo, "record", AsyncMock())
    monkeypatch.setattr(application_service.audit_repo, "record", AsyncMock())

    waiting = _app(status=AppStatus.MORE_INFO_REQUESTED, applicant_id=1)
    monkeypatch.setattr(application_service.applications_repo, "get", AsyncMock(return_value=waiting))
    monkeypatch.setattr(
        application_service.applications_repo,
        "set_status",
        AsyncMock(return_value=_app(status=AppStatus.PENDING, applicant_id=1)),
    )

    # The real applicant can respond...
    out = await application_service.submit_more_info(
        _FakeConn(), application_id=waiting.id, applicant_id=1, response="here you go"  # type: ignore[arg-type]
    )
    assert out.status is AppStatus.PENDING

    # ...someone else cannot.
    with pytest.raises(ApplicationNotFoundError):
        await application_service.submit_more_info(
            _FakeConn(), application_id=waiting.id, applicant_id=2, response="nope"  # type: ignore[arg-type]
        )


def test_roles_for_approval_and_pending_role() -> None:
    assert application_service.pending_role_name(AppType.DEVELOPER) == "Developer Pending"
    assert application_service.pending_role_name(AppType.CREATOR_STREAMER) is None

    assert application_service.roles_for_approval(_app(app_type=AppType.DEVELOPER)) == ("Developer",)

    def creator(profile_type: str) -> Application:
        return _app(app_type=AppType.CREATOR_STREAMER, fields={"profile_type": profile_type})

    assert application_service.roles_for_approval(creator("Creator")) == ("Creator",)
    assert application_service.roles_for_approval(creator("Streamer")) == ("Streamer",)
    assert application_service.roles_for_approval(creator("Both")) == ("Creator", "Streamer")
    assert application_service.roles_for_approval(creator("")) == ()
