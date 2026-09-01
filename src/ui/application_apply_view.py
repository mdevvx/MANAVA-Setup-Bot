"""The applicant-facing submission flow (all ephemeral, all transient — none of
this needs to survive a restart, unlike the review side):

    /apply <type>  ->  pre-form: select menus + Continue     (ApplyPreFormView)
                   ->  modal: the 5 required free-text fields  (ApplyModal)
                   ->  optional: "Add comments" / "Submit now" (CommentsFollowupView)
                   ->  cog.finalize(...)

The split exists only because Discord caps a modal at 5 inputs and a message at
5 action rows — see src/models/application.py for the field arrangement.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import discord

from src.errors import BotUserError
from src.models.application import (
    AppType,
    FieldSpec,
    followup_spec,
    modal_specs,
    select_specs,
    validate_fields,
)

if TYPE_CHECKING:
    from src.cogs.applications import ApplicationsCog

logger = logging.getLogger(__name__)

_PARAGRAPH_MAX = 1024
_SHORT_MAX = 300


async def _report_error(interaction: discord.Interaction, error: Exception) -> None:
    message = (
        error.user_message
        if isinstance(error, BotUserError)
        else "Something went wrong submitting that. Please try again, or contact staff."
    )
    if not isinstance(error, BotUserError):
        logger.exception("Error in application submission flow", exc_info=error)
    try:
        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)
    except discord.DiscordException:
        # Interaction token already dead (e.g. the 3s ACK window was missed) —
        # nothing more we can surface to the user here.
        logger.warning("Could not deliver application error message to the user", exc_info=True)


class _CommentsModal(discord.ui.Modal, title="Additional comments"):
    def __init__(
        self, cog: "ApplicationsCog", app_type: AppType, fields: dict[str, str], spec: FieldSpec
    ) -> None:
        super().__init__()
        self._cog = cog
        self._app_type = app_type
        self._fields = fields
        self._spec = spec
        self._input: discord.ui.TextInput["_CommentsModal"] = discord.ui.TextInput(
            label=spec.label[:45], style=discord.TextStyle.paragraph, required=False, max_length=_PARAGRAPH_MAX
        )
        self.add_item(self._input)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        # ACK within Discord's 3s window before any DB / Discord-API work.
        await interaction.response.defer(ephemeral=True, thinking=True)
        value = str(self._input.value).strip()
        if value:
            self._fields[self._spec.key] = value
        try:
            await self._cog.finalize(interaction, self._app_type, self._fields)
        except Exception as exc:  # noqa: BLE001 — surfaced to the applicant
            await _report_error(interaction, exc)

    # discord.py's Modal.on_error is (interaction, error); mypy resolves to the
    # View base's 3-arg signature. Runtime is correct.
    async def on_error(self, interaction: discord.Interaction, error: Exception) -> None:  # type: ignore[override]
        await _report_error(interaction, error)


class CommentsFollowupView(discord.ui.View):
    def __init__(
        self, cog: "ApplicationsCog", app_type: AppType, applicant_id: int, fields: dict[str, str], spec: FieldSpec
    ) -> None:
        super().__init__(timeout=300)
        self._cog = cog
        self._app_type = app_type
        self._applicant_id = applicant_id
        self._fields = fields
        self._spec = spec

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self._applicant_id:
            await interaction.response.send_message("This form isn't yours.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Add comments", style=discord.ButtonStyle.secondary)
    async def add_comments(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.send_modal(
            _CommentsModal(self._cog, self._app_type, self._fields, self._spec)
        )
        self.stop()

    @discord.ui.button(label="Submit now", style=discord.ButtonStyle.success)
    async def submit_now(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        # ACK within Discord's 3s window first — finalize() does DB writes and
        # several Discord API calls that can easily exceed it.
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            await self._cog.finalize(interaction, self._app_type, self._fields)
        except Exception as exc:  # noqa: BLE001
            await _report_error(interaction, exc)
        finally:
            self.stop()


class FixResubmitView(discord.ui.View):
    """Shown when the submitted modal has an invalid URL/email. Reopens the
    modal with every field pre-filled so the applicant only fixes the flagged
    one — Discord modals can't validate inline or disable their Submit button,
    so this is the least-annoying recovery."""

    def __init__(
        self,
        cog: "ApplicationsCog",
        app_type: AppType,
        applicant_id: int,
        selections: dict[str, str],
        prefill: dict[str, str],
    ) -> None:
        super().__init__(timeout=600)
        self._cog = cog
        self._app_type = app_type
        self._applicant_id = applicant_id
        self._selections = selections
        self._prefill = prefill

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self._applicant_id:
            await interaction.response.send_message("This form isn't yours.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Fix & resubmit", style=discord.ButtonStyle.primary)
    async def fix(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.send_modal(
            ApplyModal(self._cog, self._app_type, self._applicant_id, self._selections, prefill=self._prefill)
        )
        self.stop()


class ApplyModal(discord.ui.Modal):
    def __init__(
        self,
        cog: "ApplicationsCog",
        app_type: AppType,
        applicant_id: int,
        selections: dict[str, str],
        *,
        prefill: dict[str, str] | None = None,
    ) -> None:
        super().__init__(title=f"{app_type.label} Application"[:45])
        self._cog = cog
        self._app_type = app_type
        self._applicant_id = applicant_id
        self._selections = selections
        self._inputs: dict[str, discord.ui.TextInput["ApplyModal"]] = {}
        prefill = prefill or {}
        for spec in modal_specs(app_type):
            is_para = spec.kind == "paragraph"
            text_input: discord.ui.TextInput["ApplyModal"] = discord.ui.TextInput(
                label=spec.label[:45],
                style=discord.TextStyle.paragraph if is_para else discord.TextStyle.short,
                required=spec.required,
                max_length=_PARAGRAPH_MAX if is_para else _SHORT_MAX,
                default=(prefill.get(spec.key) or None),
            )
            self._inputs[spec.key] = text_input
            self.add_item(text_input)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        fields: dict[str, str] = dict(self._selections)
        for key, text_input in self._inputs.items():
            fields[key] = str(text_input.value).strip()

        # A Discord modal can't validate inline — this is the earliest we can
        # catch a bad URL / email. Nothing is created; the applicant gets a
        # "Fix & resubmit" button that reopens the modal pre-filled.
        problems = validate_fields(self._app_type, fields)
        if problems:
            fix_view = FixResubmitView(
                self._cog, self._app_type, self._applicant_id, self._selections, fields
            )
            await interaction.response.send_message(
                "❌ Not submitted — fix the following, then click **Fix & resubmit** "
                "(your other answers are kept):\n• " + "\n• ".join(problems),
                view=fix_view,
                ephemeral=True,
            )
            return

        follow = followup_spec(self._app_type)
        if follow is not None:
            comments_view = CommentsFollowupView(
                self._cog, self._app_type, self._applicant_id, fields, follow
            )
            await interaction.response.send_message(
                "Optional: add any additional comments, or submit as-is.", view=comments_view, ephemeral=True
            )
        else:
            await interaction.response.defer(ephemeral=True, thinking=True)
            try:
                await self._cog.finalize(interaction, self._app_type, fields)
            except Exception as exc:  # noqa: BLE001
                await _report_error(interaction, exc)

    async def on_error(self, interaction: discord.Interaction, error: Exception) -> None:  # type: ignore[override]
        await _report_error(interaction, error)


class _FieldSelect(discord.ui.Select["ApplyPreFormView"]):
    def __init__(self, spec: FieldSpec) -> None:
        self.spec = spec
        super().__init__(
            placeholder=spec.label,
            min_values=1,
            max_values=1,
            options=[discord.SelectOption(label=option) for option in spec.options],
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        assert self.view is not None
        self.view.selections[self.spec.key] = self.values[0]
        self.placeholder = f"{self.spec.label}: {self.values[0]}"
        await interaction.response.edit_message(view=self.view)


class _ContinueButton(discord.ui.Button["ApplyPreFormView"]):
    def __init__(self) -> None:
        super().__init__(label="Continue", style=discord.ButtonStyle.primary, row=4)

    async def callback(self, interaction: discord.Interaction) -> None:
        view = self.view
        assert view is not None
        missing = [
            child.spec.label
            for child in view.children
            if isinstance(child, _FieldSelect) and child.spec.key not in view.selections
        ]
        if missing:
            await interaction.response.send_message(
                f"Please choose an option for: {', '.join(missing)}", ephemeral=True
            )
            return
        await interaction.response.send_modal(
            ApplyModal(view.cog, view.app_type, view.applicant_id, dict(view.selections))
        )
        view.stop()


class ApplyPreFormView(discord.ui.View):
    def __init__(self, cog: "ApplicationsCog", app_type: AppType, applicant_id: int) -> None:
        super().__init__(timeout=300)
        self.cog = cog
        self.app_type = app_type
        self.applicant_id = applicant_id
        self.selections: dict[str, str] = {}
        for spec in select_specs(app_type):
            self.add_item(_FieldSelect(spec))
        self.add_item(_ContinueButton())

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.applicant_id:
            await interaction.response.send_message("This form isn't yours.", ephemeral=True)
            return False
        return True
