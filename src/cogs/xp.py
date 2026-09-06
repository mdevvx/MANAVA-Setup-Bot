from __future__ import annotations

import logging
from typing import TYPE_CHECKING
from uuid import uuid4

import discord
from discord import app_commands
from discord.ext import commands

from src import constants
from src.db.repositories import audit_logs as audit_repo
from src.db.repositories import bot_config as bot_config_repo
from src.db.repositories import level_thresholds as level_thresholds_repo
from src.db.repositories import memberships as memberships_repo
from src.db.repositories import squads as squads_repo
from src.db.repositories import xp_config as xp_config_repo
from src.discord_state.staff_check import require_elevated_staff
from src.errors import BotUserError
from src.models.xp import ManavaEvent
from src.services import leaderboard_service, manava_event_service
from src.ui.paginated_view import PaginatedEmbedView

if TYPE_CHECKING:
    from src.bot import ManavaBot

logger = logging.getLogger(__name__)

_PAGE_SIZE = 15


class XpCog(commands.Cog):
    def __init__(self, bot: "ManavaBot") -> None:
        self.bot = bot

    leaderboard_group = app_commands.Group(name="leaderboard", description="Squad and member leaderboards")
    # Hidden from anyone without the Discord Administrator permission; the
    # require_elevated_staff() checks remain the real gate.
    xpconfig_group = app_commands.Group(
        name="xpconfig",
        description="XP economy configuration (Admin / MANAVA Team only)",
        default_permissions=discord.Permissions(administrator=True),
        guild_only=True,
    )

    # --- Leaderboards -----------------------------------------------------

    @leaderboard_group.command(name="squads", description="Show the global squad leaderboard (ranked by Season XP)")
    async def leaderboard_squads(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        async with self.bot.db_pool.acquire() as conn:
            entries = await leaderboard_service.get_global_squad_leaderboard(conn)

        if not entries:
            await interaction.followup.send("No active squads yet.", ephemeral=True)
            return

        chunks = [entries[i : i + _PAGE_SIZE] for i in range(0, len(entries), _PAGE_SIZE)]
        pages = []
        for page_num, chunk in enumerate(chunks, start=1):
            lines = []
            for entry in chunk:
                badge = "🏆" if entry.rank <= constants.GLOBAL_LEADERBOARD_TOP_HIGHLIGHT else "  "
                lines.append(f"{badge} **#{entry.rank}** {entry.squad_name} — {entry.season_xp} season XP")
                if entry.rank == constants.GLOBAL_LEADERBOARD_TOP_HIGHLIGHT:
                    lines.append(f"— top {constants.GLOBAL_LEADERBOARD_TOP_HIGHLIGHT} above —")
            embed = discord.Embed(
                title="Global Squad Leaderboard",
                description="\n".join(lines),
                color=discord.Color.gold(),
            )
            embed.set_footer(text=f"Page {page_num}/{len(chunks)}")
            pages.append(embed)

        if len(pages) == 1:
            await interaction.followup.send(embed=pages[0], ephemeral=True)
        else:
            view = PaginatedEmbedView(pages, invoker_id=interaction.user.id)
            await interaction.followup.send(embed=pages[0], view=view, ephemeral=True)

    async def _active_squad_autocomplete(
        self, interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        try:
            async with self.bot.db_pool.acquire() as conn:
                names = await squads_repo.search_squad_names(conn, active=True, name_contains=current)
        except Exception:  # noqa: BLE001 — autocomplete must never raise
            logger.exception("leaderboard squad autocomplete failed")
            return []
        return [app_commands.Choice(name=n, value=n) for n in names]

    @leaderboard_group.command(name="squad", description="Show a squad's internal member leaderboard")
    @app_commands.describe(squad_name="Squad to show (defaults to your own current squad)")
    @app_commands.autocomplete(squad_name=_active_squad_autocomplete)
    async def leaderboard_squad(self, interaction: discord.Interaction, squad_name: str | None = None) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        async with self.bot.db_pool.acquire() as conn:
            if squad_name is not None:
                squad = await squads_repo.get_active_squad_by_name(conn, squad_name)
                if squad is None:
                    raise BotUserError(f"No active squad named **{squad_name}** was found.")
            else:
                membership = await memberships_repo.get_active_membership(conn, interaction.user.id)
                if membership is None:
                    raise BotUserError("You're not in a squad. Specify squad_name to view another squad's leaderboard.")
                squad = await squads_repo.get_squad_by_id(conn, membership.squad_id)

            entries = await leaderboard_service.get_squad_member_leaderboard(conn, squad.id)

        if not entries:
            await interaction.followup.send(f"**{squad.name}** has no active members.", ephemeral=True)
            return

        chunks = [entries[i : i + _PAGE_SIZE] for i in range(0, len(entries), _PAGE_SIZE)]
        pages = []
        for page_num, chunk in enumerate(chunks, start=1):
            lines = [
                f"**#{e.rank}** <@{e.discord_user_id}> ({e.squad_role}) — "
                f"{e.contributed_xp} contributed · {e.personal_lifetime_xp} lifetime · {e.personal_season_xp} season"
                for e in chunk
            ]
            embed = discord.Embed(
                title=f"{squad.name} — Member Leaderboard",
                description="\n".join(lines),
                color=discord.Color.blurple(),
            )
            embed.set_footer(text=f"Page {page_num}/{len(chunks)}")
            pages.append(embed)

        if len(pages) == 1:
            await interaction.followup.send(embed=pages[0], ephemeral=True)
        else:
            view = PaginatedEmbedView(pages, invoker_id=interaction.user.id)
            await interaction.followup.send(embed=pages[0], view=view, ephemeral=True)

    # --- XP economy configuration ------------------------------------------

    @xpconfig_group.command(name="view", description="Show current XP amounts and squad level thresholds")
    async def xpconfig_view(self, interaction: discord.Interaction) -> None:
        await require_elevated_staff(self.bot, interaction)
        await interaction.response.defer(ephemeral=True, thinking=True)
        async with self.bot.db_pool.acquire() as conn:
            xp_values = await xp_config_repo.get_all(conn)
            thresholds = await level_thresholds_repo.get_all(conn)
            excluded = await bot_config_repo.get_excluded_channel_ids(conn)
            mode = await bot_config_repo.get_value(
                conn, constants.BOT_CONFIG_KEY_MANAVA_INTEGRATION_MODE, constants.MANAVA_INTEGRATION_MODE_WEBHOOK
            )

        xp_lines = [f"`{key}` = {xp_values.get(key, 0)}" for key in constants.ALL_XP_CONFIG_KEYS]
        threshold_lines = [
            f"L{level} = {thresholds.get(level, '(not set)')} lifetime squad XP (cap: "
            f"{constants.SQUAD_LEVEL_MEMBER_CAPS[level]} members)"
            for level in range(2, constants.MAX_SQUAD_LEVEL + 1)
        ]
        excluded_text = ", ".join(f"<#{c}>" for c in excluded) or "none"

        embed = discord.Embed(title="XP Economy Configuration", color=discord.Color.blurple())
        embed.add_field(name="XP amounts", value="\n".join(xp_lines), inline=False)
        embed.add_field(name="Level thresholds", value="\n".join(threshold_lines), inline=False)
        embed.add_field(name="XP-excluded channels", value=excluded_text, inline=False)
        embed.add_field(name="MANAVA integration mode", value=mode, inline=False)
        await interaction.followup.send(embed=embed, ephemeral=True)

    @xpconfig_group.command(name="set-xp", description="Update an XP config amount")
    @app_commands.choices(
        key=[app_commands.Choice(name=k, value=k) for k in constants.ALL_XP_CONFIG_KEYS]
    )
    @app_commands.describe(value="New XP amount (must be >= 0)")
    async def xpconfig_set_xp(self, interaction: discord.Interaction, key: str, value: int) -> None:
        await require_elevated_staff(self.bot, interaction)
        if value < 0:
            raise BotUserError("XP amount can't be negative.")
        await interaction.response.defer(ephemeral=True, thinking=True)
        async with self.bot.db_pool.acquire() as conn:
            old = (await xp_config_repo.get_all(conn)).get(key)
            await xp_config_repo.set_value(conn, key, value, updated_by=interaction.user.id)
            await audit_repo.record(
                conn,
                actor_id=interaction.user.id,
                action="xpconfig.set_xp",
                target_type="xp_config",
                target_id=key,
                old_value={"value": old},
                new_value={"value": value},
            )
        await interaction.followup.send(f"Set `{key}` to **{value}**.", ephemeral=True)

    @xpconfig_group.command(name="set-threshold", description="Update the Lifetime Squad XP required for a level")
    @app_commands.describe(level="Squad level", value="Lifetime Squad XP required to reach this level")
    @app_commands.choices(
        level=[app_commands.Choice(name=f"Level {lvl}", value=lvl) for lvl in range(2, constants.MAX_SQUAD_LEVEL + 1)]
    )
    async def xpconfig_set_threshold(self, interaction: discord.Interaction, level: int, value: int) -> None:
        await require_elevated_staff(self.bot, interaction)
        await interaction.response.defer(ephemeral=True, thinking=True)
        async with self.bot.db_pool.acquire() as conn:
            old = (await level_thresholds_repo.get_all(conn)).get(level)
            await level_thresholds_repo.set_threshold(conn, level, value, updated_by=interaction.user.id)
            await audit_repo.record(
                conn,
                actor_id=interaction.user.id,
                action="xpconfig.set_threshold",
                target_type="level_threshold",
                target_id=str(level),
                old_value={"lifetime_squad_xp_required": old},
                new_value={"lifetime_squad_xp_required": value},
            )
        await interaction.followup.send(f"Set L{level} threshold to **{value}** lifetime squad XP.", ephemeral=True)

    @xpconfig_group.command(name="exclude-channel", description="Include/exclude a channel from granting Discord text XP")
    @app_commands.describe(channel="The channel or category to configure", excluded="True to exclude it from XP")
    async def xpconfig_exclude_channel(
        self, interaction: discord.Interaction, channel: discord.abc.GuildChannel, excluded: bool
    ) -> None:
        await require_elevated_staff(self.bot, interaction)
        await interaction.response.defer(ephemeral=True, thinking=True)
        async with self.bot.db_pool.acquire() as conn:
            current = await bot_config_repo.get_excluded_channel_ids(conn)
            was_excluded = channel.id in current
            if excluded:
                current.add(channel.id)
            else:
                current.discard(channel.id)
            await bot_config_repo.set_excluded_channel_ids(conn, current)
            await audit_repo.record(
                conn,
                actor_id=interaction.user.id,
                action="xpconfig.exclude_channel",
                target_type="channel",
                target_id=str(channel.id),
                old_value={"excluded": was_excluded},
                new_value={"excluded": excluded},
            )
        await self.bot.refresh_bot_config_cache()
        verb = "excluded from" if excluded else "included in"
        await interaction.followup.send(f"{channel.mention} is now {verb} Discord text XP.", ephemeral=True)

    @xpconfig_group.command(
        name="simulate-manava-event",
        description="Test harness: simulate an inbound MANAVA event through the real processing pipeline",
    )
    @app_commands.choices(
        event_type=[app_commands.Choice(name=t, value=t) for t in constants.ALL_MANAVA_EVENT_TYPES],
        game=[app_commands.Choice(name=g, value=g) for g in constants.MANAVA_GAMES],
    )
    @app_commands.describe(
        manava_user_id="The MANAVA user ID the event is for (must be linked/known to the bot)",
        event_type="Which kind of event to simulate",
        game="Game the event is for",
        place="Final placement (1/2/3/…), only meaningful for tournament_placement",
        won_prize_slot="tournament_placement only: player landed in a paid prize slot",
        event_id="Override the event_id to deliberately test duplicate-delivery handling (defaults to a fresh random one)",
    )
    async def simulate_manava_event(
        self,
        interaction: discord.Interaction,
        manava_user_id: str,
        event_type: str,
        game: str = "cs2",
        place: int | None = None,
        won_prize_slot: bool = False,
        event_id: str | None = None,
    ) -> None:
        await require_elevated_staff(self.bot, interaction)
        await interaction.response.defer(ephemeral=True, thinking=True)

        event = ManavaEvent(
            event_id=event_id or f"sim-{uuid4()}",
            manava_user_id=manava_user_id,
            event_type=event_type,
            game=game,
            timestamp=discord.utils.utcnow(),
            match_id=None,
            tournament_id=None,
            result=None,
            place=place,
            won_prize_slot=won_prize_slot if event_type == constants.MANAVA_EVENT_TOURNAMENT_PLACEMENT else None,
        )
        async with self.bot.db_pool.acquire() as conn:
            outcome = await manava_event_service.process_event(conn, event)

        await interaction.followup.send(
            f"event_id=`{outcome.event_id}` status=**{outcome.status}** xp_granted=**{outcome.xp_granted}** "
            f"discord_user={f'<@{outcome.discord_user_id}>' if outcome.discord_user_id else 'none'}",
            ephemeral=True,
        )


async def setup(bot: "ManavaBot") -> None:
    await bot.add_cog(XpCog(bot))
