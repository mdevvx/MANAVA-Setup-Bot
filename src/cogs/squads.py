from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING
from uuid import UUID

import discord
from discord import app_commands
from discord.ext import commands

from src.db.repositories import memberships as memberships_repo
from src.db.repositories import squads as squads_repo
from src.errors import BotUserError
from src.models.squad import Squad, SquadMembership, SquadRole
from src.services import squad_eligibility, squad_lifecycle, squad_membership
from src.ui.confirm_view import ConfirmView
from src.ui.squad_apply_view import build_join_decision_view

if TYPE_CHECKING:
    from src.bot import ManavaBot

logger = logging.getLogger(__name__)

_DM_CLOSED_HELP = (
    "I can't send you a direct message, and squad decisions are delivered by DM. "
    "Right-click the server icon → **Privacy Settings** → enable **Direct Messages**, then run this again."
)


async def _try_dm(member: discord.Member, content: str) -> bool:
    """Send a DM; return False if the member's DMs are closed."""
    try:
        await member.send(content)
        return True
    except (discord.Forbidden, discord.HTTPException):
        return False


class SquadsCog(commands.Cog):
    def __init__(self, bot: "ManavaBot") -> None:
        self.bot = bot

    squad_group = app_commands.Group(name="squad", description="Squad management commands")

    def _member(self, interaction: discord.Interaction) -> discord.Member:
        if not isinstance(interaction.user, discord.Member):
            raise BotUserError("This command can only be used in the server.")
        return interaction.user

    @squad_group.command(name="create", description="Create a new squad")
    @app_commands.describe(name="The squad's name (3-32 characters)")
    async def create(self, interaction: discord.Interaction, name: str) -> None:
        member = self._member(interaction)
        state = self.bot.require_guild_state()
        await interaction.response.defer(ephemeral=True, thinking=True)
        async with self.bot.db_pool.acquire() as conn:
            result = await squad_eligibility.check_eligibility(
                conn,
                member=member,
                state=state,
                squad_name=name,
                gateway=self.bot.gateway,
                link_url=self.bot.config.manava_link_url,
            )
            if not result.eligible:
                reasons = "\n".join(f"- {f.message}" for f in result.failures)
                await interaction.followup.send(f"You can't create a squad right now:\n{reasons}", ephemeral=True)
                return
            squad = await squad_lifecycle.create_squad(conn, state=state, leader=member, squad_name=name)
        await interaction.followup.send(f"Squad **{squad.name}** created! You're the Leader.", ephemeral=True)
        # Not a hard requirement — but the Leader needs open DMs to receive
        # join-request notifications, so warn if they're closed.
        if not await _try_dm(
            member,
            f"You're the Leader of **{squad.name}**. Members' join requests will arrive here as DMs.",
        ):
            await interaction.followup.send(
                "⚠️ Your DMs appear to be closed, so you won't get join-request notifications. "
                "Enable **Direct Messages** for this server (right-click the server icon → Privacy Settings).",
                ephemeral=True,
            )

    async def _active_squad_autocomplete(
        self, interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        try:
            async with self.bot.db_pool.acquire() as conn:
                names = await squads_repo.search_squad_names(conn, active=True, name_contains=current)
        except Exception:  # noqa: BLE001 — autocomplete must never raise
            logger.exception("squad autocomplete failed")
            return []
        return [app_commands.Choice(name=n, value=n) for n in names]

    @squad_group.command(name="apply", description="Apply to join a squad")
    @app_commands.describe(squad_name="The squad to apply to")
    @app_commands.autocomplete(squad_name=_active_squad_autocomplete)
    async def apply(self, interaction: discord.Interaction, squad_name: str) -> None:
        member = self._member(interaction)
        await interaction.response.defer(ephemeral=True, thinking=True)
        async with self.bot.db_pool.acquire() as conn:
            squad = await squads_repo.get_active_squad_by_name(conn, squad_name)
            if squad is None:
                raise BotUserError(f"No active squad named **{squad_name}** was found.")
            if await memberships_repo.get_active_membership(conn, member.id) is not None:
                raise BotUserError("You're already in a squad. Leave it before applying to another.")

            # Verify the applicant can be DM'd before creating the request —
            # the decision comes back by DM, and this doubles as the receipt.
            if not await _try_dm(
                member,
                f"📨 Your application to **{squad.name}** was received — "
                "you'll get the Leader/Officers' decision here.",
            ):
                raise BotUserError(_DM_CLOSED_HELP)

            request = await squad_membership.submit_join_request(conn, squad_id=squad.id, applicant=member)
            recipients = await memberships_repo.list_active_members(conn, squad.id)
        notify_targets = [m for m in recipients if m.squad_role in (SquadRole.LEADER, SquadRole.OFFICER)]
        await self._notify_join_request(squad, request.id, member, notify_targets)
        await interaction.followup.send(
            f"Your application to **{squad.name}** was submitted — check your DMs for the decision.",
            ephemeral=True,
        )

    async def _notify_join_request(
        self,
        squad: Squad,
        request_id: UUID,
        applicant: discord.Member,
        targets: list[SquadMembership],
    ) -> None:
        guild = applicant.guild
        view = build_join_decision_view(request_id)
        content = f"{applicant.mention} applied to join **{squad.name}**."
        for membership in targets:
            recipient = guild.get_member(membership.discord_user_id)
            if recipient is None:
                continue
            try:
                await recipient.send(content, view=view)
            except discord.Forbidden:
                logger.warning("Could not DM join-request notice to %s (DMs closed)", recipient.id)

    @squad_group.command(name="invite", description="Invite a user to your squad (Leader/Officer only)")
    @app_commands.describe(user="The user to invite")
    async def invite(self, interaction: discord.Interaction, user: discord.Member) -> None:
        member = self._member(interaction)
        state = self.bot.require_guild_state()
        await interaction.response.defer(ephemeral=True, thinking=True)
        async with self.bot.db_pool.acquire() as conn:
            inviter_membership = await memberships_repo.get_active_membership(conn, member.id)
            if inviter_membership is None:
                raise BotUserError("You're not in a squad.")
            await squad_membership.invite_member(
                conn, state=state, squad_id=inviter_membership.squad_id, inviter=member, invitee=user
            )
        await interaction.followup.send(f"{user.mention} has been added to your squad.", ephemeral=True)

    @squad_group.command(name="leave", description="Leave your current squad")
    async def leave(self, interaction: discord.Interaction) -> None:
        member = self._member(interaction)
        state = self.bot.require_guild_state()
        await interaction.response.defer(ephemeral=True, thinking=True)
        async with self.bot.db_pool.acquire() as conn:
            squad = await squad_membership.leave_squad(conn, state=state, member=member)
        await interaction.followup.send(f"You left **{squad.name}**.", ephemeral=True)

    @squad_group.command(name="remove", description="Remove a member from your squad (Leader/Officer only)")
    @app_commands.describe(user="The member to remove", reason="Optional reason")
    async def remove(self, interaction: discord.Interaction, user: discord.Member, reason: str | None = None) -> None:
        member = self._member(interaction)
        state = self.bot.require_guild_state()

        async def do_remove(confirm_interaction: discord.Interaction) -> None:
            async with self.bot.db_pool.acquire() as conn:
                actor_membership = await memberships_repo.get_active_membership(conn, member.id)
                if actor_membership is None:
                    raise BotUserError("You're not in a squad.")
                await squad_membership.remove_member(
                    conn, state=state, squad_id=actor_membership.squad_id, actor=member, target=user, reason=reason
                )
            await confirm_interaction.followup.send(f"{user.mention} was removed from the squad.", ephemeral=True)

        await self._confirm(interaction, f"Remove {user.mention} from the squad?", do_remove)

    @squad_group.command(name="promote", description="Promote a member to Officer (Leader only)")
    @app_commands.describe(user="The member to promote")
    async def promote(self, interaction: discord.Interaction, user: discord.Member) -> None:
        member = self._member(interaction)
        state = self.bot.require_guild_state()
        await interaction.response.defer(ephemeral=True, thinking=True)
        async with self.bot.db_pool.acquire() as conn:
            actor_membership = await memberships_repo.get_active_membership(conn, member.id)
            if actor_membership is None:
                raise BotUserError("You're not in a squad.")
            await squad_membership.promote_to_officer(
                conn, state=state, squad_id=actor_membership.squad_id, actor=member, target=user
            )
        await interaction.followup.send(f"{user.mention} was promoted to Officer.", ephemeral=True)

    @squad_group.command(name="demote", description="Demote an Officer to Member (Leader only)")
    @app_commands.describe(user="The officer to demote")
    async def demote(self, interaction: discord.Interaction, user: discord.Member) -> None:
        member = self._member(interaction)
        state = self.bot.require_guild_state()

        async def do_demote(confirm_interaction: discord.Interaction) -> None:
            async with self.bot.db_pool.acquire() as conn:
                actor_membership = await memberships_repo.get_active_membership(conn, member.id)
                if actor_membership is None:
                    raise BotUserError("You're not in a squad.")
                await squad_membership.demote_to_member(
                    conn, state=state, squad_id=actor_membership.squad_id, actor=member, target=user
                )
            await confirm_interaction.followup.send(f"{user.mention} was demoted to Member.", ephemeral=True)

        await self._confirm(interaction, f"Demote {user.mention} from Officer to Member?", do_demote)

    @squad_group.command(
        name="transfer-leadership", description="Transfer squad leadership to another member (Leader only)"
    )
    @app_commands.describe(user="The member to become the new Leader")
    async def transfer_leadership(self, interaction: discord.Interaction, user: discord.Member) -> None:
        member = self._member(interaction)
        state = self.bot.require_guild_state()

        async def do_transfer(confirm_interaction: discord.Interaction) -> None:
            async with self.bot.db_pool.acquire() as conn:
                actor_membership = await memberships_repo.get_active_membership(conn, member.id)
                if actor_membership is None:
                    raise BotUserError("You're not in a squad.")
                await squad_membership.transfer_leadership(
                    conn, state=state, squad_id=actor_membership.squad_id, current_leader=member, new_leader=user
                )
            await confirm_interaction.followup.send(f"Leadership transferred to {user.mention}.", ephemeral=True)

        await self._confirm(
            interaction, f"Transfer squad leadership to {user.mention}? You cannot undo this yourself.", do_transfer
        )

    @squad_group.command(name="disband", description="Disband your squad (Leader only)")
    @app_commands.describe(reason="Optional reason")
    async def disband(self, interaction: discord.Interaction, reason: str | None = None) -> None:
        member = self._member(interaction)
        state = self.bot.require_guild_state()

        async def do_disband(confirm_interaction: discord.Interaction) -> None:
            async with self.bot.db_pool.acquire() as conn:
                actor_membership = await memberships_repo.get_active_membership(conn, member.id)
                if actor_membership is None or actor_membership.squad_role is not SquadRole.LEADER:
                    raise BotUserError("Only the Squad Leader can disband the squad.")
                squad = await squads_repo.get_squad_by_id(conn, actor_membership.squad_id)
                await squad_lifecycle.disband_squad(
                    conn,
                    state=state,
                    squad=squad,
                    actor_id=member.id,
                    reason=reason,
                    archive_days=self.bot.config.squad_archive_days,
                )
            await confirm_interaction.followup.send("Your squad has been disbanded.", ephemeral=True)

        await self._confirm(
            interaction,
            "Disband your squad? This immediately removes everyone's access. This cannot be undone.",
            do_disband,
        )

    @squad_group.command(name="info", description="Show info about your current squad")
    async def info(self, interaction: discord.Interaction) -> None:
        member = self._member(interaction)
        await interaction.response.defer(ephemeral=True, thinking=True)
        async with self.bot.db_pool.acquire() as conn:
            membership = await memberships_repo.get_active_membership(conn, member.id)
            if membership is None:
                await interaction.followup.send("You're not in a squad.", ephemeral=True)
                return
            squad = await squads_repo.get_squad_by_id(conn, membership.squad_id)
            members = await memberships_repo.list_active_members(conn, squad.id)
        leader = next((m for m in members if m.squad_role is SquadRole.LEADER), None)
        officers = [m for m in members if m.squad_role is SquadRole.OFFICER]
        lines = [
            f"**{squad.name}**",
            f"Leader: <@{leader.discord_user_id}>" if leader else "Leader: (none — contact staff)",
            f"Officers: {', '.join(f'<@{o.discord_user_id}>' for o in officers) or 'none'}",
            f"Members: {len(members)}",
        ]
        await interaction.followup.send("\n".join(lines), ephemeral=True)

    async def _confirm(
        self,
        interaction: discord.Interaction,
        prompt: str,
        on_confirm: Callable[[discord.Interaction], Awaitable[None]],
    ) -> None:
        view = ConfirmView(invoker_id=interaction.user.id, on_confirm=on_confirm)
        await interaction.response.send_message(prompt, view=view, ephemeral=True)


async def setup(bot: "ManavaBot") -> None:
    await bot.add_cog(SquadsCog(bot))
