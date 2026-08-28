from __future__ import annotations

from typing import TYPE_CHECKING

import discord

from src.errors import BotUserError

if TYPE_CHECKING:
    from src.bot import ManavaBot


def is_elevated_staff(bot: "ManavaBot", member: discord.Member) -> bool:
    if bot.guild_state is not None:
        elevated = {bot.guild_state.roles.admin.id, bot.guild_state.roles.manava_team.id}
        if any(role.id in elevated for role in member.roles):
            return True
    # Fallback so a real server Administrator can still bootstrap the bot
    # even before the named Admin/MANAVA Team roles are resolvable.
    return member.guild_permissions.administrator


async def require_elevated_staff(bot: "ManavaBot", interaction: discord.Interaction) -> None:
    if not isinstance(interaction.user, discord.Member) or not is_elevated_staff(bot, interaction.user):
        raise BotUserError("This command is restricted to Admin / MANAVA Team.")
