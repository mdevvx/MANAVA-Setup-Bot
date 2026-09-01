"""Reapplication rules: one active application per type, and a 30-day cooldown
after a rejection (enforced server-side)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from src.errors import ApplicationCooldownError, DuplicateApplicationError
from src.models.application import Application, AppStatus, AppType
from src.services import application_service


def _rejected(days_ago: float) -> Application:
    return Application(
        id=uuid4(),
        applicant_id=1,
        applicant_username="user#1",
        app_type=AppType.DEVELOPER,
        status=AppStatus.REJECTED,
        fields={},
        review_channel_id=None,
        review_message_id=None,
        submitted_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        decided_at=datetime.now(timezone.utc) - timedelta(days=days_ago),
        decided_by=99,
    )


@pytest.mark.asyncio
async def test_active_application_blocks_new_one(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        application_service.applications_repo,
        "get_active_for_user",
        AsyncMock(return_value=_rejected(0)),  # any row -> blocked
    )
    with pytest.raises(DuplicateApplicationError):
        await application_service.assert_can_apply(object(), 1, AppType.DEVELOPER)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_recent_rejection_is_in_cooldown(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(application_service.applications_repo, "get_active_for_user", AsyncMock(return_value=None))
    monkeypatch.setattr(application_service.applications_repo, "last_rejection", AsyncMock(return_value=_rejected(10)))
    with pytest.raises(ApplicationCooldownError):
        await application_service.assert_can_apply(object(), 1, AppType.DEVELOPER)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_rejection_past_cooldown_allows_reapply(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(application_service.applications_repo, "get_active_for_user", AsyncMock(return_value=None))
    monkeypatch.setattr(application_service.applications_repo, "last_rejection", AsyncMock(return_value=_rejected(31)))
    await application_service.assert_can_apply(object(), 1, AppType.DEVELOPER)  # type: ignore[arg-type]  # no raise


@pytest.mark.asyncio
async def test_no_prior_rejection_allows(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(application_service.applications_repo, "get_active_for_user", AsyncMock(return_value=None))
    monkeypatch.setattr(application_service.applications_repo, "last_rejection", AsyncMock(return_value=None))
    await application_service.assert_can_apply(object(), 1, AppType.DEVELOPER)  # type: ignore[arg-type]  # no raise
