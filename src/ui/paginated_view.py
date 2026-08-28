from __future__ import annotations

import discord


class PaginatedEmbedView(discord.ui.View):
    """Generic Prev/Next pager for a pre-built list of embed pages. Used by
    the leaderboards, which can run to 70 squads or up to 1000 squad members."""

    def __init__(self, pages: list[discord.Embed], *, invoker_id: int, timeout: float = 120.0) -> None:
        super().__init__(timeout=timeout)
        self._pages = pages
        self._invoker_id = invoker_id
        self._index = 0
        self._update_buttons()

    def _update_buttons(self) -> None:
        self.previous_button.disabled = self._index == 0
        self.next_button.disabled = self._index >= len(self._pages) - 1

    @property
    def current_page(self) -> discord.Embed:
        return self._pages[self._index]

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self._invoker_id:
            await interaction.response.send_message(
                "Only the person who ran this command can page through it.", ephemeral=True
            )
            return False
        return True

    @discord.ui.button(label="Previous", style=discord.ButtonStyle.secondary)
    async def previous_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        self._index -= 1
        self._update_buttons()
        await interaction.response.edit_message(embed=self._pages[self._index], view=self)

    @discord.ui.button(label="Next", style=discord.ButtonStyle.secondary)
    async def next_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        self._index += 1
        self._update_buttons()
        await interaction.response.edit_message(embed=self._pages[self._index], view=self)
