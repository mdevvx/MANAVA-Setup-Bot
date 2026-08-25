from __future__ import annotations

import logging
from typing import TYPE_CHECKING
from uuid import UUID

import discord

from src.errors import BotUserError
from src.services import squad_membership

if TYPE_CHECKING:
    from src.bot import ManavaBot

logger = logging.getLogger(__name__)


class ApplyDecisionView(discord.ui.View):
    """Approve/Reject buttons sent via DM to a squad's Leader/Officers when
    someone applies. Known Phase 1 limitation: this view is not registered as a
    Discord.py persistent view, so buttons on already-sent DMs stop working
    across a bot restart — the applicant would need to reapply. Full restart
    resilience is Phase 3 reliability scope."""

    def __init__(self, *, bot: "ManavaBot", request_id: UUID, applicant_id: int, squad_name: str) -> None:
        super().__init__(timeout=None)
        self._bot = bot
        self._request_id = request_id
        self._applicant_id = applicant_id
        self._squad_name = squad_name

    @discord.ui.button(label="Approve", style=discord.ButtonStyle.success)
    async def approve(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._decide(interaction, approved=True)

    @discord.ui.button(label="Reject", style=discord.ButtonStyle.danger)
    async def reject(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._decide(interaction, approved=False)

    async def _decide(self, interaction: discord.Interaction, *, approved: bool) -> None:
        for child in self.children:
            if isinstance(child, discord.ui.Button):
                child.disabled = True
        await interaction.response.edit_message(view=self)

        guild = self._bot.get_guild(self._bot.config.guild_id)
        if guild is None:
            await interaction.followup.send("Couldn't reach the server to process this. Contact staff.", ephemeral=True)
            return
        approver = guild.get_member(interaction.user.id)
        applicant = guild.get_member(self._applicant_id)
        if approver is None or applicant is None:
            await interaction.followup.send(
                "Couldn't find the members involved — they may have left the server.", ephemeral=True
            )
            return

        try:
            state = self._bot.require_guild_state()
            async with self._bot.db_pool.acquire() as conn:
                if approved:
                    await squad_membership.approve_join_request(
                        conn, state=state, request_id=self._request_id, approver=approver, applicant=applicant
                    )
                else:
                    await squad_membership.reject_join_request(conn, request_id=self._request_id, approver=approver)
        except BotUserError as exc:
            await interaction.followup.send(exc.user_message, ephemeral=True)
            return
        except Exception:
            logger.exception("Failed to process join request decision %s", self._request_id)
            await interaction.followup.send("Something went wrong processing that. Contact staff.", ephemeral=True)
            return

        verb = "approved" if approved else "rejected"
        await interaction.followup.send(
            f"You {verb} {applicant.mention}'s application to **{self._squad_name}**.", ephemeral=True
        )
        self.stop()
