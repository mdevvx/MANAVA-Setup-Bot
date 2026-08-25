from __future__ import annotations

from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands

if TYPE_CHECKING:
    from src.bot import ManavaBot


class HelpCog(commands.Cog):
    def __init__(self, bot: "ManavaBot") -> None:
        self.bot = bot

    @app_commands.command(name="help", description="Show available MANAVA bot commands")
    async def help_command(self, interaction: discord.Interaction) -> None:
        embed = discord.Embed(
            title="MANAVA Multiverse Bot — Commands",
            color=discord.Color.blurple(),
        )
        embed.add_field(
            name="Squad commands — everyone",
            value=(
                "`/squad create name:<...>` — create a squad (requires the Member role, "
                "1500+ lifetime XP, verified player, and not already being in a squad)\n"
                "`/squad apply squad_name:<...>` — request to join a squad\n"
                "`/squad info` — view your current squad's roster\n"
                "`/squad leave` — leave your squad (Leaders must transfer or disband first)"
            ),
            inline=False,
        )
        embed.add_field(
            name="Squad commands — Leader/Officer only",
            value=(
                "`/squad invite user:<@user>` — add someone directly, no approval needed\n"
                "`/squad remove user:<@user>` — remove a member (asks to confirm)"
            ),
            inline=False,
        )
        embed.add_field(
            name="Squad commands — Leader only",
            value=(
                "`/squad promote user:<@user>` — promote a member to Officer (max 2 per squad)\n"
                "`/squad demote user:<@user>` — demote an Officer to Member (asks to confirm)\n"
                "`/squad transfer-leadership user:<@user>` — hand off leadership (asks to confirm)\n"
                "`/squad disband` — disband the squad (asks to confirm)"
            ),
            inline=False,
        )
        embed.add_field(
            name="Admin commands — Admin / MANAVA Team only",
            value=(
                "`/admin set-verified user:<@user> verified:<true|false>` — mark a user as a "
                "verified MANAVA player\n"
                "`/admin add-xp user:<@user> amount:<n>` — manually grant Personal Lifetime XP to a user\n"
                "`!sync` — message command, not slash — re-syncs slash commands and re-checks "
                "required roles/categories/permissions without restarting the bot"
            ),
            inline=False,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: "ManavaBot") -> None:
    await bot.add_cog(HelpCog(bot))
