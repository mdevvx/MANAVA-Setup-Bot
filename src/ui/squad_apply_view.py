"""Approve/Reject buttons DM'd to a squad's Leader/Officers when someone
applies to join.

Persistent across restarts: implemented as DynamicItem buttons whose custom_id
carries the join-request id, so a decision made hours (or a redeploy) after the
DM was sent still works — the applicant, squad and permission checks are all
re-resolved from the DB at click time. Registered once via
`bot.add_dynamic_items(SquadJoinDecisionButton)` in setup_hook.
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING
from uuid import UUID

import discord

from src.db.repositories import join_requests as join_requests_repo
from src.db.repositories import squads as squads_repo
from src.errors import BotUserError
from src.services import squad_membership

if TYPE_CHECKING:
    from src.bot import ManavaBot

logger = logging.getLogger(__name__)

_TEMPLATE = re.compile(r"squad:join:(?P<action>approve|reject):(?P<req_id>[0-9a-fA-F-]{36})")


class SquadJoinDecisionButton(
    discord.ui.DynamicItem[discord.ui.Button],
    template=_TEMPLATE,
):
    def __init__(self, request_id: UUID, action: str) -> None:
        self.request_id = request_id
        self.action = action
        approve = action == "approve"
        super().__init__(
            discord.ui.Button(
                label="Approve" if approve else "Reject",
                style=discord.ButtonStyle.success if approve else discord.ButtonStyle.danger,
                custom_id=f"squad:join:{action}:{request_id}",
            )
        )

    @classmethod
    async def from_custom_id(  # type: ignore[override]  # narrower `item` type than the base's Item[Any]
        cls, interaction: discord.Interaction, item: discord.ui.Button, match: re.Match[str]
    ) -> "SquadJoinDecisionButton":
        return cls(UUID(match["req_id"]), match["action"])

    async def _disable_dm_buttons(self, interaction: discord.Interaction) -> None:
        if interaction.message is None:
            return
        try:
            view = discord.ui.View.from_message(interaction.message)
            for child in view.children:
                if isinstance(child, discord.ui.Button):
                    child.disabled = True
            await interaction.message.edit(view=view)
        except discord.DiscordException:
            logger.debug("Could not disable squad join-request DM buttons", exc_info=True)

    async def callback(self, interaction: discord.Interaction) -> None:
        bot: "ManavaBot" = interaction.client  # type: ignore[assignment]
        approved = self.action == "approve"
        await interaction.response.defer(ephemeral=True, thinking=True)

        guild = bot.get_guild(bot.config.guild_id)
        if guild is None:
            await interaction.followup.send("Couldn't reach the server to process this. Contact staff.", ephemeral=True)
            return
        approver = guild.get_member(interaction.user.id)
        if approver is None:
            await interaction.followup.send("Couldn't find your membership in the server.", ephemeral=True)
            return

        applicant: discord.Member | None = None
        squad_name = "the squad"
        try:
            state = bot.require_guild_state()
            async with bot.db_pool.acquire() as conn:
                request = await join_requests_repo.get_request(conn, self.request_id)
                if request is None:
                    await interaction.followup.send("That join request no longer exists.", ephemeral=True)
                    return
                squad = await squads_repo.get_squad_by_id(conn, request.squad_id)
                squad_name = squad.name
                applicant = guild.get_member(request.applicant_id)

                if approved:
                    if applicant is None:
                        await interaction.followup.send(
                            "The applicant has left the server, so this can't be approved.", ephemeral=True
                        )
                        return
                    await squad_membership.approve_join_request(
                        conn, state=state, request_id=self.request_id, approver=approver, applicant=applicant
                    )
                else:
                    await squad_membership.reject_join_request(
                        conn, request_id=self.request_id, approver=approver
                    )
        except BotUserError as exc:
            await interaction.followup.send(exc.user_message, ephemeral=True)
            return
        except Exception:
            logger.exception("Failed to process squad join decision %s", self.request_id)
            await interaction.followup.send("Something went wrong processing that. Contact staff.", ephemeral=True)
            return

        await self._disable_dm_buttons(interaction)
        verb = "approved" if approved else "rejected"
        who = applicant.mention if applicant is not None else "the applicant"
        await interaction.followup.send(f"You {verb} {who}'s application to **{squad_name}**.", ephemeral=True)


def build_join_decision_view(request_id: UUID) -> discord.ui.View:
    view = discord.ui.View(timeout=None)
    view.add_item(SquadJoinDecisionButton(request_id, "approve"))
    view.add_item(SquadJoinDecisionButton(request_id, "reject"))
    return view
