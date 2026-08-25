from __future__ import annotations

from collections.abc import Awaitable, Callable

import discord


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
        await self._on_confirm(interaction)
        self.stop()

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        self._disable_all()
        await interaction.response.edit_message(content="Cancelled.", view=self)
        self.stop()
