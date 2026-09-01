"""Discord-side orchestration for the application workflow: role changes, the
review-channel embed, and applicant DMs. The DB state transitions + history +
audit are done first by application_service; this layer applies the visible
effects and is deliberately best-effort about DMs (a closed-DM applicant must
not break a reviewer's decision).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import discord

from src.db.repositories import applications as applications_repo
from src.discord_state import role_safety
from src.models.application import Application, AppType
from src.services import application_service
from src.ui.application_moreinfo_view import build_more_info_view
from src.ui.application_render import render_application_embed

if TYPE_CHECKING:
    from src.bot import ManavaBot

logger = logging.getLogger(__name__)


async def _dm(bot: "ManavaBot", user_id: int, content: str, *, view: discord.ui.View | None = None) -> bool:
    try:
        user = bot.get_user(user_id) or await bot.fetch_user(user_id)
        if view is not None:
            await user.send(content, view=view)
        else:
            await user.send(content)
        return True
    except discord.Forbidden:
        logger.warning("Could not DM user %s (DMs closed)", user_id)
        return False
    except discord.DiscordException:
        logger.exception("Failed to DM user %s", user_id)
        return False


def _member(bot: "ManavaBot", user_id: int) -> discord.Member | None:
    guild = bot.get_guild(bot.config.guild_id)
    return guild.get_member(user_id) if guild is not None else None


async def finalize_submission(bot: "ManavaBot", *, applicant: discord.Member, app: Application) -> None:
    """Post-submit: assign the pending role (Developer only), post the review
    embed, remember its message id, and confirm to the applicant."""
    guild_state = bot.require_guild_state()
    app_state = bot.require_application_state()

    pending_name = application_service.pending_role_name(app.app_type)
    if pending_name is not None:
        await role_safety.assign_role(
            guild_state, applicant, app_state.role_by_name(pending_name), reason="Application submitted"
        )

    from src.ui.application_review_view import ApplicationReviewView

    message = await app_state.review_channel.send(
        embed=render_application_embed(app), view=ApplicationReviewView()
    )
    async with bot.db_pool.acquire() as conn:
        await applications_repo.set_review_message(
            conn, app.id, channel_id=message.channel.id, message_id=message.id
        )

    await _dm(
        bot,
        app.applicant_id,
        f"Your **{app.app_type.label}** application has been submitted and is now with the review team. "
        "You'll be notified here when there's a decision.",
    )


async def _refresh_review_message(
    bot: "ManavaBot", app: Application, *, disable: bool, extra_note: str | None = None
) -> None:
    if app.review_channel_id is None or app.review_message_id is None:
        return
    channel = bot.get_channel(app.review_channel_id)
    if not isinstance(channel, discord.abc.Messageable):
        return
    try:
        message = await channel.fetch_message(app.review_message_id)
    except discord.DiscordException:
        logger.warning("Review message for application %s is gone", app.id)
        return
    from src.ui.application_review_view import ApplicationReviewView

    view = ApplicationReviewView()
    if disable:
        for child in view.children:
            if isinstance(child, discord.ui.Button):
                child.disabled = True
    await message.edit(embed=render_application_embed(app, extra_note=extra_note), view=view)


async def apply_approval(bot: "ManavaBot", *, app: Application, reviewer_id: int) -> None:
    guild_state = bot.require_guild_state()
    app_state = bot.require_application_state()
    member = _member(bot, app.applicant_id)

    if member is not None:
        pending_name = application_service.pending_role_name(app.app_type)
        if pending_name is not None:
            await role_safety.remove_role(
                guild_state, member, app_state.role_by_name(pending_name), reason="Application approved"
            )
        for role_name in application_service.roles_for_approval(app):
            await role_safety.assign_role(
                guild_state, member, app_state.role_by_name(role_name), reason="Application approved"
            )
    else:
        logger.warning("Approved application %s but applicant %s not in guild", app.id, app.applicant_id)

    await _refresh_review_message(bot, app, disable=True)
    await _dm(bot, app.applicant_id, f"🎉 Your **{app.app_type.label}** application has been **approved**!")


async def apply_rejection(bot: "ManavaBot", *, app: Application, reviewer_id: int, reason: str | None) -> None:
    guild_state = bot.require_guild_state()
    app_state = bot.require_application_state()
    member = _member(bot, app.applicant_id)

    if member is not None:
        pending_name = application_service.pending_role_name(app.app_type)
        if pending_name is not None:
            await role_safety.remove_role(
                guild_state, member, app_state.role_by_name(pending_name), reason="Application rejected"
            )

    await _refresh_review_message(bot, app, disable=True)
    tail = f"\n\n> {reason}" if reason else ""
    await _dm(
        bot,
        app.applicant_id,
        f"Your **{app.app_type.label}** application was **not approved** this time.{tail}\n\n"
        "You can reapply after 30 days.",
    )


async def apply_more_info_request(
    bot: "ManavaBot", *, app: Application, reviewer_id: int, question: str
) -> bool:
    await _refresh_review_message(bot, app, disable=False, extra_note=f"ℹ️ Info requested: {question}")
    return await _dm(
        bot,
        app.applicant_id,
        f"The review team needs more information about your **{app.app_type.label}** application:\n\n"
        f"> {question}\n\nUse the button below to respond.",
        view=build_more_info_view(app.id),
    )


async def apply_more_info_response(bot: "ManavaBot", *, app: Application, response: str) -> None:
    await _refresh_review_message(
        bot, app, disable=False, extra_note=f"📥 Applicant responded: {response}"
    )
    app_state = bot.application_state
    if app_state is not None and app.review_message_id is not None:
        jump = (
            f"https://discord.com/channels/{bot.config.guild_id}/"
            f"{app.review_channel_id}/{app.review_message_id}"
        )
        try:
            await app_state.review_channel.send(
                f"📥 <@{app.applicant_id}> responded to the info request on their "
                f"**{app.app_type.label}** application — {jump}"
            )
        except discord.DiscordException:
            logger.exception("Failed to post more-info-response notice for application %s", app.id)


def app_type_from_command(name: str) -> AppType:
    return AppType.DEVELOPER if name == "developer" else AppType.CREATOR_STREAMER
