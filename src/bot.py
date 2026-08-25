from __future__ import annotations

import logging

import asyncpg
import discord
from discord import app_commands
from discord.ext import commands, tasks

from src.config import BotConfig
from src.db.repositories import squads as squads_repo
from src.discord_state import provisioning
from src.discord_state.role_resolver import ResolvedGuildState, resolve_guild_state
from src.errors import BotUserError, DiscordSetupError
from src.services import xp_stub_service

logger = logging.getLogger(__name__)


class ManavaBot(commands.Bot):
    def __init__(self, config: BotConfig, db_pool: asyncpg.Pool) -> None:
        intents = discord.Intents.default()
        intents.members = True
        # message_content is a privileged intent — needed to parse the "!sync"
        # message command, and Phase 2's real +15/10-char XP rule will need it
        # too. Must also be turned on in the Discord Developer Portal under
        # Bot -> Privileged Gateway Intents -> Message Content Intent, or the
        # gateway connection will be rejected even with this set.
        intents.message_content = True
        super().__init__(command_prefix="!", intents=intents)
        self.config = config
        self.db_pool = db_pool
        self.guild_state: ResolvedGuildState | None = None
        # discord.py's documented pattern for a custom tree-wide error handler;
        # the type stubs don't reflect that this attribute is assignable.
        self.tree.on_error = self.on_app_command_error  # type: ignore[method-assign]

    async def setup_hook(self) -> None:
        await self.load_extension("src.cogs.squads")
        await self.load_extension("src.cogs.admin")
        await self.load_extension("src.cogs.help")
        guild_obj = discord.Object(id=self.config.guild_id)
        self.tree.copy_global_to(guild=guild_obj)
        await self.tree.sync(guild=guild_obj)
        self.purge_archived_squads.start()

    async def on_ready(self) -> None:
        guild = self.get_guild(self.config.guild_id)
        if guild is None:
            logger.error(
                "Configured guild id %s not found — is the bot a member of that server?", self.config.guild_id
            )
            return
        try:
            self.guild_state = resolve_guild_state(guild)
            logger.info("Resolved required Discord roles/categories successfully.")
        except DiscordSetupError as exc:
            self.guild_state = None
            logger.error("Squad features disabled until this is fixed: %s", exc.user_message)
        logger.info("Logged in as %s (%s)", self.user, self.user.id if self.user else "?")

    def require_guild_state(self) -> ResolvedGuildState:
        if self.guild_state is None:
            raise DiscordSetupError(
                "The bot isn't fully configured on this server yet (missing required roles/categories). Contact staff."
            )
        return self.guild_state

    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot or message.guild is None:
            return
        try:
            async with self.db_pool.acquire() as conn:
                await xp_stub_service.record_message_activity(conn, message.author.id)
        except Exception:
            logger.exception("Failed to record STUB message XP for %s", message.author.id)
        # Required for prefix/message commands (e.g. "!sync") to dispatch at
        # all — overriding on_message fully replaces discord.py's default
        # dispatch, which normally calls this for you.
        await self.process_commands(message)

    async def on_app_command_error(
        self, interaction: discord.Interaction, error: app_commands.AppCommandError
    ) -> None:
        original = error.original if isinstance(error, app_commands.CommandInvokeError) else error
        if isinstance(original, BotUserError):
            message = original.user_message
        else:
            logger.exception(
                "Unhandled error in app command %s", getattr(interaction.command, "name", "?"), exc_info=original
            )
            message = "Something went wrong. Please try again, or contact staff if this keeps happening."
        try:
            if interaction.response.is_done():
                await interaction.followup.send(message, ephemeral=True)
            else:
                await interaction.response.send_message(message, ephemeral=True)
        except discord.DiscordException:
            logger.exception("Failed to deliver error message to user")

    @tasks.loop(hours=24)
    async def purge_archived_squads(self) -> None:
        if self.guild_state is None:
            return
        try:
            async with self.db_pool.acquire() as conn:
                ready = await squads_repo.list_squads_ready_for_purge(conn)
                for squad in ready:
                    await provisioning.teardown_squad_discord_objects(self.guild_state, squad)
                    await squads_repo.mark_discord_objects_purged(conn, squad.id)
                    logger.info("Purged Discord objects for archived squad %s (%s)", squad.name, squad.id)
        except Exception:
            logger.exception("Archived-squad purge task failed")

    @purge_archived_squads.before_loop
    async def _before_purge(self) -> None:
        await self.wait_until_ready()
