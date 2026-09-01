"""The applicant's "Respond" button, DM'd to them when a reviewer clicks
Request More Info.

Implemented as a DynamicItem so it survives a bot restart: the application id
is encoded in the button's custom_id and parsed back out by `from_custom_id`,
with no in-memory view state to lose. Registered once via
`bot.add_dynamic_items(MoreInfoRespondButton)` in setup_hook.
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING
from uuid import UUID

import discord

from src.errors import BotUserError

if TYPE_CHECKING:
    from src.bot import ManavaBot

logger = logging.getLogger(__name__)

_TEMPLATE = re.compile(r"app:moreinfo:respond:(?P<app_id>[0-9a-fA-F-]{36})")


class MoreInfoResponseModal(discord.ui.Modal, title="Respond to the review team"):
    response: discord.ui.TextInput["MoreInfoResponseModal"] = discord.ui.TextInput(
        label="Your response",
        style=discord.TextStyle.paragraph,
        max_length=1500,
        required=True,
    )

    def __init__(self, application_id: UUID) -> None:
        super().__init__()
        self.application_id = application_id

    async def on_submit(self, interaction: discord.Interaction) -> None:
        bot: "ManavaBot" = interaction.client  # type: ignore[assignment]
        from src.services import application_actions, application_service

        await interaction.response.defer(ephemeral=True, thinking=True)
        async with bot.db_pool.acquire() as conn:
            app = await application_service.submit_more_info(
                conn,
                application_id=self.application_id,
                applicant_id=interaction.user.id,
                response=str(self.response),
            )
        await application_actions.apply_more_info_response(bot, app=app, response=str(self.response))
        await interaction.followup.send(
            "Thanks — your response has been sent to the review team.", ephemeral=True
        )

    # Modal.on_error is (interaction, error) at runtime; mypy resolves to the View base.
    async def on_error(self, interaction: discord.Interaction, error: Exception) -> None:  # type: ignore[override]
        message = error.user_message if isinstance(error, BotUserError) else (
            "Something went wrong sending that. Please try again, or contact staff."
        )
        if not isinstance(error, BotUserError):
            logger.exception("Error handling more-info response", exc_info=error)
        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)


class MoreInfoRespondButton(
    discord.ui.DynamicItem[discord.ui.Button],
    template=_TEMPLATE,
):
    def __init__(self, application_id: UUID) -> None:
        self.application_id = application_id
        super().__init__(
            discord.ui.Button(
                label="Respond",
                style=discord.ButtonStyle.primary,
                custom_id=f"app:moreinfo:respond:{application_id}",
            )
        )

    @classmethod
    async def from_custom_id(  # type: ignore[override]  # narrower `item` type than the base's Item[Any]
        cls,
        interaction: discord.Interaction,
        item: discord.ui.Button,
        match: re.Match[str],
    ) -> "MoreInfoRespondButton":
        return cls(UUID(match["app_id"]))

    async def callback(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_modal(MoreInfoResponseModal(self.application_id))


def build_more_info_view(application_id: UUID) -> discord.ui.View:
    view = discord.ui.View(timeout=None)
    view.add_item(MoreInfoRespondButton(application_id))
    return view
