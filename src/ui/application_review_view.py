"""Persistent Approve / Reject / Request More Info view attached to every
review-channel message.

Persistent = `timeout=None` + static `custom_id`s + registered once via
`bot.add_view(ApplicationReviewView())` in setup_hook, so the buttons keep
working after a restart. The buttons carry no per-application state: the
application is resolved from the message they live on
(`applications_repo.get_by_review_message`).

Interaction timing: the reviewer check is in-memory and runs first; anything
that hits the DB happens only *after* the interaction has been acknowledged
(deferred, or a modal opened), so a slow database can never blow Discord's
3-second response window.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import discord

from src.db.repositories import applications as applications_repo
from src.discord_state.staff_check import is_elevated_staff
from src.errors import ApplicationNotFoundError, BotUserError
from src.models.application import Application

if TYPE_CHECKING:
    from src.bot import ManavaBot


logger = logging.getLogger(__name__)


def _check_reviewer(interaction: discord.Interaction) -> None:
    """In-memory only — safe to call before acknowledging the interaction.
    Moderator / Senior Moderator are explicitly excluded from review (spec)."""
    bot: "ManavaBot" = interaction.client  # type: ignore[assignment]
    if not isinstance(interaction.user, discord.Member) or not is_elevated_staff(bot, interaction.user):
        raise BotUserError("Only Admin / MANAVA Team can review applications.")


async def _resolve_app(interaction: discord.Interaction) -> Application:
    """DB lookup — only call after the interaction has been acknowledged."""
    bot: "ManavaBot" = interaction.client  # type: ignore[assignment]
    if interaction.message is None:
        raise ApplicationNotFoundError()
    async with bot.db_pool.acquire() as conn:
        app = await applications_repo.get_by_review_message(conn, interaction.message.id)
    if app is None:
        raise ApplicationNotFoundError()
    return app


async def _report_error(interaction: discord.Interaction, error: Exception) -> None:
    message = (
        error.user_message
        if isinstance(error, BotUserError)
        else "Something went wrong. Please try again, or contact staff."
    )
    if not isinstance(error, BotUserError):
        logger.exception("Error in application review action", exc_info=error)
    try:
        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)
    except discord.DiscordException:
        logger.warning("Failed to deliver review-action error message", exc_info=True)


class _ReasonModal(discord.ui.Modal):
    _label: str
    _required: bool
    _action: str  # "reject" | "moreinfo"

    text: discord.ui.TextInput["_ReasonModal"]

    def __init__(self, review_message_id: int) -> None:
        super().__init__(title="Reject application" if self._action == "reject" else "Request more information")
        self.review_message_id = review_message_id
        self.text = discord.ui.TextInput(
            label=self._label,
            style=discord.TextStyle.paragraph,
            required=self._required,
            max_length=1000,
        )
        self.add_item(self.text)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        bot: "ManavaBot" = interaction.client  # type: ignore[assignment]
        from src.services import application_actions, application_service

        _check_reviewer(interaction)
        await interaction.response.defer(ephemeral=True, thinking=True)

        async with bot.db_pool.acquire() as conn:
            app = await applications_repo.get_by_review_message(conn, self.review_message_id)
        if app is None:
            raise ApplicationNotFoundError()

        value = str(self.text).strip() or None

        if self._action == "reject":
            async with bot.db_pool.acquire() as conn:
                updated = await application_service.reject(
                    conn, application_id=app.id, reviewer_id=interaction.user.id, reason=value
                )
            await application_actions.apply_rejection(
                bot, app=updated, reviewer_id=interaction.user.id, reason=value
            )
            await interaction.followup.send("Application rejected. The applicant has been notified.", ephemeral=True)
        else:
            async with bot.db_pool.acquire() as conn:
                updated = await application_service.request_more_info(
                    conn,
                    application_id=app.id,
                    reviewer_id=interaction.user.id,
                    question=value or "(no details provided)",
                )
            dmed = await application_actions.apply_more_info_request(
                bot, app=updated, reviewer_id=interaction.user.id, question=value or "(no details provided)"
            )
            note = "" if dmed else "\n\n⚠️ Couldn't DM the applicant (their DMs are closed)."
            await interaction.followup.send(f"Info request recorded.{note}", ephemeral=True)

    # Modal.on_error is (interaction, error) at runtime; mypy resolves to the View base.
    async def on_error(self, interaction: discord.Interaction, error: Exception) -> None:  # type: ignore[override]
        await _report_error(interaction, error)


class RejectModal(_ReasonModal):
    _action = "reject"
    _label = "Reason (optional — shared with the applicant)"
    _required = False


class MoreInfoModal(_ReasonModal):
    _action = "moreinfo"
    _label = "What do you need from the applicant?"
    _required = True


class ApplicationReviewView(discord.ui.View):
    def __init__(self) -> None:
        super().__init__(timeout=None)

    @discord.ui.button(label="Approve", style=discord.ButtonStyle.success, custom_id="app:review:approve")
    async def approve(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        try:
            _check_reviewer(interaction)
            await interaction.response.defer(ephemeral=True, thinking=True)

            bot: "ManavaBot" = interaction.client  # type: ignore[assignment]
            from src.services import application_actions, application_service

            app = await _resolve_app(interaction)
            async with bot.db_pool.acquire() as conn:
                updated = await application_service.approve(
                    conn, application_id=app.id, reviewer_id=interaction.user.id
                )
            await application_actions.apply_approval(bot, app=updated, reviewer_id=interaction.user.id)
            await interaction.followup.send(
                f"Approved **{app.applicant_username}**'s {app.app_type.label} application.", ephemeral=True
            )
        except Exception as exc:  # noqa: BLE001 — surfaced to the reviewer, logged if unexpected
            await _report_error(interaction, exc)

    @discord.ui.button(label="Reject", style=discord.ButtonStyle.danger, custom_id="app:review:reject")
    async def reject(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        try:
            _check_reviewer(interaction)
            if interaction.message is None:
                raise ApplicationNotFoundError()
            await interaction.response.send_modal(RejectModal(interaction.message.id))
        except Exception as exc:  # noqa: BLE001
            await _report_error(interaction, exc)

    @discord.ui.button(
        label="Request More Info", style=discord.ButtonStyle.secondary, custom_id="app:review:moreinfo"
    )
    async def more_info(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        try:
            _check_reviewer(interaction)
            if interaction.message is None:
                raise ApplicationNotFoundError()
            await interaction.response.send_modal(MoreInfoModal(interaction.message.id))
        except Exception as exc:  # noqa: BLE001
            await _report_error(interaction, exc)
