from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands

from src.db.repositories import audit_logs as audit_repo
from src.db.repositories import personal_xp as xp_repo
from src.db.repositories import squads as squads_repo
from src.discord_state import provisioning
from src.discord_state.role_resolver import resolve_guild_state
from src.discord_state.staff_check import is_elevated_staff, require_elevated_staff
from src.errors import BotUserError, DiscordSetupError
from src.services import account_linking, squad_lifecycle

if TYPE_CHECKING:
    from src.bot import ManavaBot

logger = logging.getLogger(__name__)


class AdminCog(commands.Cog):
    def __init__(self, bot: "ManavaBot") -> None:
        self.bot = bot

    admin_group = app_commands.Group(name="admin", description="Admin utility commands")

    @admin_group.command(
        name="set-verified",
        description="STUB: manually set a user's verified-player status (replaced by MANAVA account-linking in Phase 3)",
    )
    @app_commands.describe(user="The user to update", verified="New verified-player status")
    async def set_verified(self, interaction: discord.Interaction, user: discord.Member, verified: bool) -> None:
        await require_elevated_staff(self.bot, interaction)
        await interaction.response.defer(ephemeral=True, thinking=True)
        async with self.bot.db_pool.acquire() as conn:
            old = await xp_repo.get_verified_player(conn, user.id)
            await xp_repo.set_verified_player(conn, user.id, verified)
            await audit_repo.record(
                conn,
                actor_id=interaction.user.id,
                action="admin.set_verified",
                target_type="user",
                target_id=str(user.id),
                old_value={"verified_player": old},
                new_value={"verified_player": verified},
            )
        await interaction.followup.send(
            f"Set verified-player for {user.mention} to **{verified}**.", ephemeral=True
        )

    @admin_group.command(
        name="add-xp",
        description="Manually add Personal Lifetime XP to a user",
    )
    @app_commands.describe(
        user="The user to grant XP to", amount="XP amount to add", reason="Why (recorded in the audit log)"
    )
    async def add_xp(
        self, interaction: discord.Interaction, user: discord.Member, amount: int, reason: str | None = None
    ) -> None:
        await require_elevated_staff(self.bot, interaction)
        if amount <= 0:
            raise BotUserError("Amount must be a positive number.")
        await interaction.response.defer(ephemeral=True, thinking=True)
        async with self.bot.db_pool.acquire() as conn:
            before = await xp_repo.get_lifetime_xp(conn, user.id)
            personal = await xp_repo.add_xp(conn, user.id, amount)
            await audit_repo.record(
                conn,
                actor_id=interaction.user.id,
                action="admin.add_xp",
                target_type="user",
                target_id=str(user.id),
                old_value={"lifetime_xp": before},
                new_value={"lifetime_xp": personal.lifetime_xp, "amount": amount},
                reason=reason,
            )
        await interaction.followup.send(
            f"Added {amount} XP to {user.mention}. New lifetime XP: **{personal.lifetime_xp}**.", ephemeral=True
        )

    @admin_group.command(
        name="link-manava-account",
        description="STUB: manually link a user's MANAVA account ID (replaced by MANAVA account-linking in Phase 3)",
    )
    @app_commands.describe(user="The Discord user", manava_user_id="Their MANAVA account ID")
    async def link_manava_account(
        self, interaction: discord.Interaction, user: discord.Member, manava_user_id: str
    ) -> None:
        await require_elevated_staff(self.bot, interaction)
        await interaction.response.defer(ephemeral=True, thinking=True)
        async with self.bot.db_pool.acquire() as conn:
            existing = await xp_repo.get_discord_user_id_by_manava_id(conn, manava_user_id)
            if existing is not None and existing != user.id:
                raise BotUserError(f"MANAVA account `{manava_user_id}` is already linked to another user.")
            old = await xp_repo.get(conn, user.id)
            await xp_repo.set_manava_user_id(conn, user.id, manava_user_id)
            await audit_repo.record(
                conn,
                actor_id=interaction.user.id,
                action="admin.link_manava_account",
                target_type="user",
                target_id=str(user.id),
                old_value={"manava_user_id": old.manava_user_id},
                new_value={"manava_user_id": manava_user_id},
            )
        await interaction.followup.send(
            f"Linked {user.mention} to MANAVA account `{manava_user_id}`.", ephemeral=True
        )

    async def _disbanded_squad_autocomplete(
        self, interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        if not isinstance(interaction.user, discord.Member) or not is_elevated_staff(self.bot, interaction.user):
            return []
        try:
            async with self.bot.db_pool.acquire() as conn:
                names = await squads_repo.search_squad_names(conn, active=False, name_contains=current)
        except Exception:  # noqa: BLE001 — autocomplete must never raise
            logger.exception("restore-squad autocomplete failed")
            return []
        return [app_commands.Choice(name=n, value=n) for n in names]

    @admin_group.command(
        name="restore-squad",
        description="Recover a squad disbanded within the last 30 days (before its channels are purged)",
    )
    @app_commands.describe(squad_name="The disbanded squad to restore")
    @app_commands.autocomplete(squad_name=_disbanded_squad_autocomplete)
    async def restore_squad(self, interaction: discord.Interaction, squad_name: str) -> None:
        await require_elevated_staff(self.bot, interaction)
        state = self.bot.require_guild_state()
        await interaction.response.defer(ephemeral=True, thinking=True)
        async with self.bot.db_pool.acquire() as conn:
            squad = await squads_repo.get_squad_by_name_any_status(conn, squad_name)
            if squad is None:
                raise BotUserError(f"No squad named **{squad_name}** has ever existed.")
            restored, reopened = await squad_lifecycle.restore_squad(
                conn, state=state, squad=squad, actor_id=interaction.user.id
            )
        members = ", ".join(f"<@{uid}>" for uid, _ in reopened) or "none"
        await interaction.followup.send(
            f"Restored **{restored.name}**. Re-added {len(reopened)} member(s): {members}.\n"
            "Any former members who have since joined another squad were skipped.",
            ephemeral=True,
        )

    # --- MANAVA Gateway ---------------------------------------------------
    #
    # The bot backend holds only DISCORD_BACKEND_API_KEY, which the Gateway
    # scopes to the identity endpoint. Registering this deployment's
    # /webhooks/manava URL is a MANAVA-side ops action (guarded by their
    # INTERNAL_SERVICE_KEY), so there's no bot command for it.

    gateway_group = app_commands.Group(
        name="gateway", description="MANAVA Gateway integration (Admin / MANAVA Team only)", parent=admin_group
    )

    @gateway_group.command(name="refresh-identity", description="Re-fetch a user's MANAVA identity from the Gateway")
    @app_commands.describe(user="The user to refresh")
    async def gateway_refresh_identity(self, interaction: discord.Interaction, user: discord.Member) -> None:
        await require_elevated_staff(self.bot, interaction)
        if not self.bot.gateway.enabled:
            raise BotUserError(
                "Gateway mode is off — set MANAVA_GATEWAY_BASE_URL and DISCORD_BACKEND_API_KEY."
            )
        await interaction.response.defer(ephemeral=True, thinking=True)
        async with self.bot.db_pool.acquire() as conn:
            identity = await account_linking.refresh_from_gateway(conn, self.bot.gateway, user.id)
        if identity is None:
            raise BotUserError("The Gateway lookup failed — see logs. Cached values are unchanged.")
        await interaction.followup.send(
            f"{user.mention}: linked=**{identity.linked}** "
            f"manava_user_id=`{identity.manava_user_id or '—'}` verified=**{identity.verified_player}**",
            ephemeral=True,
        )

    @commands.command(name="sync")
    async def sync(self, ctx: commands.Context["ManavaBot"]) -> None:
        """Message command (not slash): !sync re-syncs slash commands and
        re-checks required roles/categories, without restarting the bot.
        Deliberately a message command, not a slash command — slash commands
        only work once they've been synced, so a slash-based sync command is
        useless the moment syncing itself is what's broken."""
        if not isinstance(ctx.author, discord.Member) or not is_elevated_staff(self.bot, ctx.author):
            await ctx.send("This command is restricted to Admin / MANAVA Team.")
            return

        try:
            await ctx.message.add_reaction("⏳")
        except discord.DiscordException:
            logger.exception("Failed to add waiting reaction to !sync message")

        success = True
        async with ctx.typing():
            guild_obj = discord.Object(id=self.bot.config.guild_id)
            synced = await self.bot.tree.sync(guild=guild_obj)

            guild = self.bot.get_guild(self.bot.config.guild_id)
            if guild is None:
                state_status = "not checked — bot isn't in the configured guild"
                perms_status = "skipped"
                success = False
            else:
                try:
                    self.bot.guild_state = resolve_guild_state(guild)
                    state_status = "OK — all required roles/categories resolved"
                    try:
                        await provisioning.apply_category_baseline_permissions(self.bot.guild_state)
                        perms_status = "OK — category baseline permissions (re)applied"
                    except discord.DiscordException:
                        logger.exception("Failed to apply SQUADS category baseline permissions")
                        perms_status = "FAILED — check bot permissions on those categories"
                        success = False
                except DiscordSetupError as exc:
                    self.bot.guild_state = None
                    state_status = f"FAILED — {exc.user_message}"
                    perms_status = "skipped — roles/categories not fully resolved"
                    success = False

            if self.bot.guild_state is None:
                apps_status = "skipped — core roles/categories not resolved"
            else:
                await self.bot.refresh_application_state()
                if self.bot.application_state is not None:
                    apps_status = "OK — roles + #applications-review resolved"
                else:
                    apps_status = "FAILED — see logs (applications feature disabled)"
                    success = False

            await self.bot.refresh_bot_config_cache()

        try:
            await ctx.message.remove_reaction("⏳", ctx.me)
        except discord.DiscordException:
            logger.exception("Failed to remove waiting reaction from !sync message")
        try:
            await ctx.message.add_reaction("✅" if success else "❌")
        except discord.DiscordException:
            logger.exception("Failed to add completion reaction to !sync message")

        await ctx.send(
            f"Synced {len(synced)} slash command(s).\n"
            f"Role/category check: {state_status}\n"
            f"Category permissions: {perms_status}\n"
            f"Applications setup: {apps_status}\n"
            f"XP exclusion list / MANAVA mode cache: refreshed"
        )


async def setup(bot: "ManavaBot") -> None:
    await bot.add_cog(AdminCog(bot))
