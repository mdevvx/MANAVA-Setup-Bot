from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands

from src.db.repositories import personal_xp as xp_repo
from src.discord_state import provisioning
from src.discord_state.role_resolver import resolve_guild_state
from src.discord_state.staff_check import is_elevated_staff, require_elevated_staff
from src.errors import BotUserError, DiscordSetupError

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
            await xp_repo.set_verified_player(conn, user.id, verified)
        await interaction.followup.send(
            f"Set verified-player for {user.mention} to **{verified}**.", ephemeral=True
        )

    @admin_group.command(
        name="add-xp",
        description="Manually add Personal Lifetime XP to a user",
    )
    @app_commands.describe(user="The user to grant XP to", amount="XP amount to add")
    async def add_xp(self, interaction: discord.Interaction, user: discord.Member, amount: int) -> None:
        await require_elevated_staff(self.bot, interaction)
        if amount <= 0:
            raise BotUserError("Amount must be a positive number.")
        await interaction.response.defer(ephemeral=True, thinking=True)
        async with self.bot.db_pool.acquire() as conn:
            personal = await xp_repo.add_xp(conn, user.id, amount)
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
            await xp_repo.set_manava_user_id(conn, user.id, manava_user_id)
        await interaction.followup.send(
            f"Linked {user.mention} to MANAVA account `{manava_user_id}`.", ephemeral=True
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
            f"XP exclusion list / MANAVA mode cache: refreshed"
        )


async def setup(bot: "ManavaBot") -> None:
    await bot.add_cog(AdminCog(bot))
