from __future__ import annotations

import logging
import time

import asyncpg
import discord
from discord import app_commands
from discord.ext import commands, tasks

from src import constants
from src.config import BotConfig
from src.db.repositories import bot_config as bot_config_repo
from src.db.repositories import squads as squads_repo
from src.discord_state import provisioning
from src.discord_state.applications_setup import ResolvedApplicationState, ensure_application_state
from src.discord_state.role_resolver import ResolvedGuildState, resolve_guild_state
from src.discord_state.xp_channel_filter import is_message_xp_eligible, is_within_cooldown
from src.errors import BotUserError, DiscordSetupError
from src.services import xp_service
from src.services.gateway_client import GatewayClient
from src.web.polling import ManavaPollingTask
from src.web.webhook_server import ManavaWebhookServer

logger = logging.getLogger(__name__)


class ManavaBot(commands.Bot):
    def __init__(self, config: BotConfig, db_pool: asyncpg.Pool) -> None:
        intents = discord.Intents.default()
        intents.members = True
        # message_content is a privileged intent — needed to parse the "!sync"
        # message command and the real Discord text-XP rule (10-char minimum).
        # Must also be turned on in the Discord Developer Portal under
        # Bot -> Privileged Gateway Intents -> Message Content Intent, or the
        # gateway connection will be rejected even with this set.
        intents.message_content = True
        super().__init__(command_prefix="!", intents=intents)
        self.config = config
        self.db_pool = db_pool
        self.guild_state: ResolvedGuildState | None = None
        self.application_state: ResolvedApplicationState | None = None
        self.xp_excluded_channel_ids: set[int] = set()
        self.application_review_channel_ids: dict[str, int] = {}
        self.started_at = discord.utils.utcnow()
        self._xp_cooldowns: dict[int, float] = {}
        self.webhook_server = ManavaWebhookServer(self)
        self.polling_task = ManavaPollingTask(self)
        self.gateway = GatewayClient(config)
        # discord.py's documented pattern for a custom tree-wide error handler;
        # the type stubs don't reflect that this attribute is assignable.
        self.tree.on_error = self.on_app_command_error  # type: ignore[method-assign]

    async def setup_hook(self) -> None:
        await self.load_extension("src.cogs.squads")
        await self.load_extension("src.cogs.admin")
        await self.load_extension("src.cogs.help")
        await self.load_extension("src.cogs.xp")
        await self.load_extension("src.cogs.seasons")
        await self.load_extension("src.cogs.applications")

        # Persistent views: keep every long-lived button working across a bot
        # restart — the application review buttons, the applicant's more-info
        # "Respond" button, and the squad join-request Approve/Reject buttons.
        from src.ui.application_moreinfo_view import MoreInfoRespondButton
        from src.ui.application_review_view import ApplicationReviewView
        from src.ui.squad_apply_view import SquadJoinDecisionButton

        self.add_view(ApplicationReviewView())
        self.add_dynamic_items(MoreInfoRespondButton, SquadJoinDecisionButton)

        guild_obj = discord.Object(id=self.config.guild_id)
        self.tree.copy_global_to(guild=guild_obj)
        await self.tree.sync(guild=guild_obj)
        self.purge_archived_squads.start()
        await self.webhook_server.start()

    async def close(self) -> None:
        await self.webhook_server.stop()
        self.polling_task.stop()
        await self.gateway.aclose()
        await super().close()

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

        await self.refresh_application_state()
        await self.refresh_bot_config_cache()
        logger.info("Logged in as %s (%s)", self.user, self.user.id if self.user else "?")

    async def refresh_bot_config_cache(self) -> None:
        """Reloads bot_config-backed in-memory state: the XP channel exclusion
        list, the per-type application review channel overrides, and starts/stops
        the MANAVA REST-polling fallback per the configured integration mode.
        Safe to call anytime (e.g. !sync)."""
        async with self.db_pool.acquire() as conn:
            self.xp_excluded_channel_ids = await bot_config_repo.get_excluded_channel_ids(conn)
            self.application_review_channel_ids = await bot_config_repo.get_application_review_channels(conn)
            mode = await bot_config_repo.get_value(
                conn, constants.BOT_CONFIG_KEY_MANAVA_INTEGRATION_MODE, constants.MANAVA_INTEGRATION_MODE_WEBHOOK
            )
        if mode == constants.MANAVA_INTEGRATION_MODE_POLLING:
            self.polling_task.start()
        else:
            self.polling_task.stop()

    async def refresh_application_state(self) -> None:
        """Resolve/create the application roles + #applications-review channel and
        re-apply that channel's permission baseline. A failure disables only the
        applications feature — squads/XP are unaffected. Safe to call anytime
        (on_ready, !sync); no-op if the guild's core roles aren't resolved yet."""
        if self.guild_state is None:
            self.application_state = None
            return
        try:
            self.application_state = await ensure_application_state(self.guild_state)
            logger.info("Applications feature ready (roles + #applications-review resolved).")
        except DiscordSetupError as exc:
            self.application_state = None
            logger.error("Applications feature disabled until this is fixed: %s", exc.user_message)

    def require_application_state(self) -> ResolvedApplicationState:
        if self.application_state is None:
            raise DiscordSetupError(
                "The application system isn't set up on this server yet (missing roles or review channel). Contact staff."
            )
        return self.application_state

    def require_guild_state(self) -> ResolvedGuildState:
        if self.guild_state is None:
            raise DiscordSetupError(
                "The bot isn't fully configured on this server yet (missing required roles/categories). Contact staff."
            )
        return self.guild_state

    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot or message.guild is None:
            await self.process_commands(message)
            return
        await self._maybe_grant_text_xp(message)
        # Required for prefix/message commands (e.g. "!sync") to dispatch at
        # all — overriding on_message fully replaces discord.py's default
        # dispatch, which normally calls this for you.
        await self.process_commands(message)

    async def _maybe_grant_text_xp(self, message: discord.Message) -> None:
        if len(message.content.strip()) < constants.DISCORD_TEXT_XP_MIN_CHARS:
            return
        if not is_message_xp_eligible(message, self.xp_excluded_channel_ids):
            return

        now = time.monotonic()
        last_grant = self._xp_cooldowns.get(message.author.id)
        if is_within_cooldown(last_grant, now, constants.DISCORD_TEXT_XP_COOLDOWN_SECONDS):
            return
        # Set the cooldown BEFORE awaiting the DB call, so two messages sent
        # back-to-back can't both slip through while the first write is still
        # in flight (a single Discord message can never grant XP more than
        # once — this is the guard for that within one process).
        self._xp_cooldowns[message.author.id] = now

        try:
            async with self.db_pool.acquire() as conn:
                await xp_service.grant_personal_xp(conn, message.author.id, constants.DISCORD_TEXT_XP_AMOUNT)
        except Exception:
            logger.exception("Failed to grant Discord text XP to %s", message.author.id)

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
