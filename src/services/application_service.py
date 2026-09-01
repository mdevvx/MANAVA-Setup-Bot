"""Application review workflow — DB state transitions, history trail, and audit
logging. Discord side effects (assigning roles, posting the review embed,
DMing the applicant) live in the applications cog / views; this module stays
DB-pure so the whole lifecycle is unit-testable.

Status lifecycle:
    (none) --submit--> pending
    pending --request more info--> more_info_requested
    more_info_requested --applicant replies--> pending
    pending / more_info_requested --approve--> approved   (terminal)
    pending / more_info_requested --reject--> rejected     (terminal)
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from uuid import UUID

import asyncpg

from src import constants
from src.db.repositories import application_history as history_repo
from src.db.repositories import applications as applications_repo
from src.db.repositories import audit_logs as audit_repo
from src.errors import (
    ApplicationAlreadyDecidedError,
    ApplicationCooldownError,
    ApplicationNotFoundError,
    BotUserError,
    DuplicateApplicationError,
)
from src.models.application import (
    Application,
    AppStatus,
    AppType,
    HistoryActorRole,
    validate_fields,
)

logger = logging.getLogger(__name__)


def _audit_public_view(app: Application) -> dict[str, object]:
    """Only ever non-PII fields — application `fields` (which hold contact
    email etc.) never go into audit_logs."""
    return {"app_type": app.app_type.value, "applicant_id": app.applicant_id}


async def assert_can_apply(conn: asyncpg.Connection, applicant_id: int, app_type: AppType) -> None:
    """Raises if the user can't start a new application of this type right now:
    either one is already active (also enforced by a unique index at insert),
    or they're inside the 30-day post-rejection cooldown."""
    active = await applications_repo.get_active_for_user(conn, applicant_id, app_type)
    if active is not None:
        raise DuplicateApplicationError(app_type.label)

    last_reject = await applications_repo.last_rejection(conn, applicant_id, app_type)
    if last_reject is not None and last_reject.decided_at is not None:
        elapsed = datetime.now(timezone.utc) - last_reject.decided_at
        days_left = constants.APPLICATION_REJECT_COOLDOWN_DAYS - elapsed.days
        if days_left > 0:
            raise ApplicationCooldownError(app_type.label, days_left)


async def submit(
    conn: asyncpg.Connection,
    *,
    applicant_id: int,
    applicant_username: str,
    app_type: AppType,
    fields: dict[str, str],
) -> Application:
    async with conn.transaction():
        await assert_can_apply(conn, applicant_id, app_type)

        # Authoritative content check — can't be bypassed by racing the form.
        # A malformed contact email in particular must never create an
        # application (the form does a pre-check too, this is the backstop).
        problems = validate_fields(app_type, fields)
        if problems:
            raise BotUserError("Your application wasn't submitted:\n• " + "\n• ".join(problems))

        app = await applications_repo.insert(
            conn,
            applicant_id=applicant_id,
            applicant_username=applicant_username,
            app_type=app_type,
            fields=fields,
        )
        await history_repo.record(
            conn,
            application_id=app.id,
            old_status=None,
            new_status=AppStatus.PENDING,
            actor_id=applicant_id,
            actor_role=HistoryActorRole.APPLICANT,
        )
        await audit_repo.record(
            conn,
            actor_id=applicant_id,
            action="application.submit",
            target_type="application",
            target_id=str(app.id),
            new_value=_audit_public_view(app),
        )
    logger.info("Application %s submitted (%s) by %s", app.id, app_type.value, applicant_id)
    return app


async def _get_or_404(conn: asyncpg.Connection, application_id: UUID) -> Application:
    app = await applications_repo.get(conn, application_id)
    if app is None:
        raise ApplicationNotFoundError()
    return app


async def approve(
    conn: asyncpg.Connection, *, application_id: UUID, reviewer_id: int
) -> Application:
    async with conn.transaction():
        app = await _get_or_404(conn, application_id)
        if app.status.is_decided:
            raise ApplicationAlreadyDecidedError()
        updated = await applications_repo.set_status(
            conn, application_id, new_status=AppStatus.APPROVED, decided_by=reviewer_id
        )
        await history_repo.record(
            conn,
            application_id=application_id,
            old_status=app.status,
            new_status=AppStatus.APPROVED,
            actor_id=reviewer_id,
            actor_role=HistoryActorRole.REVIEWER,
        )
        await audit_repo.record(
            conn,
            actor_id=reviewer_id,
            action="application.approve",
            target_type="application",
            target_id=str(application_id),
            old_value={"status": app.status.value},
            new_value={"status": AppStatus.APPROVED.value, **_audit_public_view(app)},
        )
    logger.info("Application %s approved by %s", application_id, reviewer_id)
    return updated


async def reject(
    conn: asyncpg.Connection, *, application_id: UUID, reviewer_id: int, reason: str | None
) -> Application:
    async with conn.transaction():
        app = await _get_or_404(conn, application_id)
        if app.status.is_decided:
            raise ApplicationAlreadyDecidedError()
        updated = await applications_repo.set_status(
            conn, application_id, new_status=AppStatus.REJECTED, decided_by=reviewer_id
        )
        await history_repo.record(
            conn,
            application_id=application_id,
            old_status=app.status,
            new_status=AppStatus.REJECTED,
            actor_id=reviewer_id,
            actor_role=HistoryActorRole.REVIEWER,
            note=reason,
        )
        await audit_repo.record(
            conn,
            actor_id=reviewer_id,
            action="application.reject",
            target_type="application",
            target_id=str(application_id),
            old_value={"status": app.status.value},
            new_value={"status": AppStatus.REJECTED.value, **_audit_public_view(app)},
            reason=reason,
        )
    logger.info("Application %s rejected by %s", application_id, reviewer_id)
    return updated


async def request_more_info(
    conn: asyncpg.Connection, *, application_id: UUID, reviewer_id: int, question: str
) -> Application:
    async with conn.transaction():
        app = await _get_or_404(conn, application_id)
        if app.status.is_decided:
            raise ApplicationAlreadyDecidedError()
        updated = await applications_repo.set_status(
            conn, application_id, new_status=AppStatus.MORE_INFO_REQUESTED
        )
        await history_repo.record(
            conn,
            application_id=application_id,
            old_status=app.status,
            new_status=AppStatus.MORE_INFO_REQUESTED,
            actor_id=reviewer_id,
            actor_role=HistoryActorRole.REVIEWER,
            note=question,
        )
        await audit_repo.record(
            conn,
            actor_id=reviewer_id,
            action="application.request_more_info",
            target_type="application",
            target_id=str(application_id),
            old_value={"status": app.status.value},
            new_value={"status": AppStatus.MORE_INFO_REQUESTED.value},
        )
    logger.info("Application %s: more info requested by %s", application_id, reviewer_id)
    return updated


async def submit_more_info(
    conn: asyncpg.Connection, *, application_id: UUID, applicant_id: int, response: str
) -> Application:
    """The applicant's reply to a Request More Info. Attaches to the SAME
    application record (never a new one) and moves it back to pending for the
    reviewers."""
    async with conn.transaction():
        app = await _get_or_404(conn, application_id)
        if app.applicant_id != applicant_id:
            raise ApplicationNotFoundError()
        if app.status is not AppStatus.MORE_INFO_REQUESTED:
            raise ApplicationAlreadyDecidedError()
        updated = await applications_repo.set_status(conn, application_id, new_status=AppStatus.PENDING)
        await history_repo.record(
            conn,
            application_id=application_id,
            old_status=AppStatus.MORE_INFO_REQUESTED,
            new_status=AppStatus.PENDING,
            actor_id=applicant_id,
            actor_role=HistoryActorRole.APPLICANT,
            note=response,
        )
    logger.info("Application %s: applicant %s supplied more info", application_id, applicant_id)
    return updated


# --- Pure helpers for the Discord side (role names; resolved to discord.Role by the cog) ---


def pending_role_name(app_type: AppType) -> str | None:
    """The role assigned on submit and removed on decision. Only Developer has
    one — Creator/Streamer applications get no 'Pending' role (spec)."""
    return constants.ROLE_NAME_DEVELOPER_PENDING if app_type is AppType.DEVELOPER else None


def roles_for_approval(app: Application) -> tuple[str, ...]:
    """Role name(s) to grant when an application is approved."""
    if app.app_type is AppType.DEVELOPER:
        return (constants.ROLE_NAME_DEVELOPER,)
    profile_type = (app.fields.get("profile_type") or "").strip().lower()
    if profile_type == "creator":
        return (constants.ROLE_NAME_CREATOR,)
    if profile_type == "streamer":
        return (constants.ROLE_NAME_STREAMER,)
    if profile_type == "both":
        return (constants.ROLE_NAME_CREATOR, constants.ROLE_NAME_STREAMER)
    # Unrecognised / missing Profile Type: grant nothing rather than guessing.
    logger.warning("Application %s approved with unrecognised profile_type %r", app.id, profile_type)
    return ()
