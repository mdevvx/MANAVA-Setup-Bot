from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands

from src.errors import BotUserError
from src.models.application import AppType
from src.services import application_actions, application_service
from src.ui.application_apply_view import ApplyPreFormView

if TYPE_CHECKING:
    from src.bot import ManavaBot

logger = logging.getLogger(__name__)


class ApplicationsCog(commands.Cog):
    def __init__(self, bot: "ManavaBot") -> None:
        self.bot = bot

    apply_group = app_commands.Group(
        name="apply", description="Apply for a MANAVA program role"
    )

    async def _start(self, interaction: discord.Interaction, app_type: AppType) -> None:
        if not isinstance(interaction.user, discord.Member):
            raise BotUserError("Please run this in the MANAVA server, not in DMs.")
        self.bot.require_application_state()  # raises a friendly error if the feature isn't set up

        # Defer first: assert_can_apply hits the DB, which over a remote pooler
        # can exceed Discord's 3-second ACK window on a cold connection.
        await interaction.response.defer(ephemeral=True, thinking=True)
        async with self.bot.db_pool.acquire() as conn:
            await application_service.assert_can_apply(conn, interaction.user.id, app_type)

        view = ApplyPreFormView(self, app_type, interaction.user.id)
        await interaction.followup.send(
            f"**{app_type.label} Application** — choose the options below, then click **Continue** "
            "to fill in the rest.",
            view=view,
            ephemeral=True,
        )

    @apply_group.command(name="developer", description="Submit a Developer application")
    async def apply_developer(self, interaction: discord.Interaction) -> None:
        await self._start(interaction, AppType.DEVELOPER)

    @apply_group.command(name="creator-streamer", description="Submit a Creator / Streamer application")
    async def apply_creator_streamer(self, interaction: discord.Interaction) -> None:
        await self._start(interaction, AppType.CREATOR_STREAMER)

    async def finalize(
        self, interaction: discord.Interaction, app_type: AppType, fields: dict[str, str]
    ) -> None:
        """Shared tail of every submission path (modal submit, or the optional
        comments follow-up). Persists the application, fires the Discord-side
        effects, and confirms to the applicant."""
        if not interaction.response.is_done():
            await interaction.response.defer(ephemeral=True, thinking=True)

        member = interaction.user
        assert isinstance(member, discord.Member)
        async with self.bot.db_pool.acquire() as conn:
            app = await application_service.submit(
                conn,
                applicant_id=member.id,
                applicant_username=str(member),
                app_type=app_type,
                fields=fields,
            )
        await application_actions.finalize_submission(self.bot, applicant=member, app=app)
        await interaction.followup.send(
            f"✅ Your **{app_type.label}** application has been submitted. "
            "You'll get a DM when the review team responds.",
            ephemeral=True,
        )


async def setup(bot: "ManavaBot") -> None:
    await bot.add_cog(ApplicationsCog(bot))
