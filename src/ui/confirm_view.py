from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable

import discord

from src.errors import BotUserError

logger = logging.getLogger(__name__)


class ConfirmView(discord.ui.View):
    """Generic confirm/cancel view for destructive actions (Remove, Demote, Disband,
    Transfer Leadership). Only the original invoker can respond, and the action only
    runs after the explicit Confirm click — never on the first click of a command."""

    def __init__(
        self,
        *,
        invoker_id: int,
        on_confirm: Callable[[discord.Interaction], Awaitable[None]],
        timeout: float = 60.0,
    ) -> None:
        super().__init__(timeout=timeout)
        self._invoker_id = invoker_id
        self._on_confirm = on_confirm
        self._prompt: discord.Interaction | None = None

    def bind(self, interaction: discord.Interaction) -> None:
        """Optional: the interaction whose response holds this prompt, so an
        unanswered prompt can be disabled on timeout instead of leaving dead
        buttons that just fail when clicked."""
        self._prompt = interaction

    async def on_timeout(self) -> None:
        if self._prompt is None:
            return
        self._disable_all()
        try:
            await self._prompt.edit_original_response(content="Timed out — nothing was changed.", view=self)
        except discord.DiscordException:
            logger.debug("Couldn't disable a timed-out confirm prompt", exc_info=True)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self._invoker_id:
            await interaction.response.send_message(
                "Only the person who started this action can confirm it.", ephemeral=True
            )
            return False
        return True

    def _disable_all(self) -> None:
        for child in self.children:
            if isinstance(child, discord.ui.Button):
                child.disabled = True

    @discord.ui.button(label="Confirm", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        self._disable_all()
        await interaction.response.edit_message(view=self)
        try:
            await self._on_confirm(interaction)
        except BotUserError as exc:
            # The response was already consumed by edit_message above, so the
            # confirmed action's own error has to be delivered as a follow-up.
            await interaction.followup.send(exc.user_message, ephemeral=True)
        except Exception:
            logger.exception("Confirmed action failed")
            await interaction.followup.send(
                "Something went wrong completing that. Please try again, or contact staff.", ephemeral=True
            )
        finally:
            self.stop()

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        self._disable_all()
        await interaction.response.edit_message(content="Cancelled.", view=self)
        self.stop()
