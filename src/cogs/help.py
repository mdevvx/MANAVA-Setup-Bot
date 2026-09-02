from __future__ import annotations

from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands

from src.discord_state.staff_check import is_elevated_staff

if TYPE_CHECKING:
    from src.bot import ManavaBot


class HelpCog(commands.Cog):
    def __init__(self, bot: "ManavaBot") -> None:
        self.bot = bot

    @app_commands.command(name="help", description="Show available MANAVA bot commands")
    async def help_command(self, interaction: discord.Interaction) -> None:
        # The reply is ephemeral, so it's safe to tailor it to the caller:
        # everyone sees the member commands; Admin / MANAVA Team additionally
        # see the staff sections. Normal members never see the admin commands.
        show_admin = isinstance(interaction.user, discord.Member) and is_elevated_staff(
            self.bot, interaction.user
        )

        embed = discord.Embed(
            title="MANAVA Multiverse Bot — Commands",
            color=discord.Color.blurple(),
        )

        embed.add_field(
            name="Squad — everyone",
            value=(
                "`/squad create name:<...>` — create a squad (needs the Member role, "
                "1500+ lifetime XP, verified player, not already in a squad)\n"
                "`/squad apply squad_name:<...>` — request to join a squad\n"
                "`/squad info` — view your current squad's roster\n"
                "`/squad leave` — leave your squad (Leaders must transfer or disband first)"
            ),
            inline=False,
        )
        embed.add_field(
            name="Squad — Leader / Officer",
            value=(
                "`/squad invite user:<@user>` — add someone directly, no approval needed\n"
                "`/squad remove user:<@user>` — remove a member (asks to confirm)"
            ),
            inline=False,
        )
        embed.add_field(
            name="Squad — Leader only",
            value=(
                "`/squad promote user:<@user>` — promote a member to Officer (max 2 per squad)\n"
                "`/squad demote user:<@user>` — demote an Officer to Member (asks to confirm)\n"
                "`/squad transfer-leadership user:<@user>` — hand off leadership (asks to confirm)\n"
                "`/squad disband` — disband the squad (asks to confirm)"
            ),
            inline=False,
        )
        embed.add_field(
            name="Leaderboards — everyone",
            value=(
                "`/leaderboard squads` — global squad leaderboard, ranked by season XP\n"
                "`/leaderboard squad squad_name:<optional>` — a squad's member leaderboard "
                "(defaults to your own squad)"
            ),
            inline=False,
        )
        embed.add_field(
            name="Applications — everyone",
            value=(
                "`/apply developer` — submit a Developer application\n"
                "`/apply creator-streamer` — submit a Creator / Streamer application\n"
                "One open application per type at a time; after a rejection you can reapply in 30 days."
            ),
            inline=False,
        )

        if show_admin:
            embed.add_field(
                name="​",
                value="**— Admin / MANAVA Team only (below) —**",
                inline=False,
            )
            embed.add_field(
                name="Seasons",
                value=(
                    "`/season status` — show the current season\n"
                    "`/season start` — open a new season\n"
                    "`/season end` — end the active season\n"
                    "`/season new` — end the current season and reset all Season XP "
                    "(Lifetime XP is kept; asks to confirm)"
                ),
                inline=False,
            )
            embed.add_field(
                name="Admin",
                value=(
                    "`/admin set-verified user:<@user> verified:<bool>` — mark a user as a verified MANAVA player\n"
                    "`/admin add-xp user:<@user> amount:<n> [reason]` — manually grant Personal XP\n"
                    "`/admin link-manava-account user:<@user> manava_user_id:<...>` — link a Discord user to MANAVA\n"
                    "`/admin restore-squad squad_name:<...>` — recover a squad disbanded in the last 30 days\n"
                    "`!sync` — message command (not slash): re-sync slash commands + re-check "
                    "roles/categories/permissions without a restart"
                ),
                inline=False,
            )
            embed.add_field(
                name="Admin — MANAVA Gateway (only when Gateway mode is on)",
                value=(
                    "`/admin gateway refresh-identity user:<@user>` — re-fetch a user's MANAVA "
                    "identity (linked / verified) and re-cache it"
                ),
                inline=False,
            )
            embed.add_field(
                name="XP configuration",
                value=(
                    "`/xpconfig view` — current XP amounts, level thresholds, settings\n"
                    "`/xpconfig set-xp key:<...> value:<n>` — update an XP amount\n"
                    "`/xpconfig set-threshold level:<2-7> value:<n>` — update a squad level's XP threshold\n"
                    "`/xpconfig exclude-channel channel:<#channel> excluded:<bool>` — toggle text XP for a channel\n"
                    "`/xpconfig simulate-manava-event ...` — test the MANAVA event pipeline directly"
                ),
                inline=False,
            )
            embed.set_footer(text="You're seeing the Admin / MANAVA Team commands.")
        else:
            embed.set_footer(text="Staff see extra commands when they run /help.")

        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: "ManavaBot") -> None:
    await bot.add_cog(HelpCog(bot))
