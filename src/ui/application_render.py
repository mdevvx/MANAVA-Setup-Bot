"""Rendering for the applications-review embed.

This embed is ONLY ever sent into the private #applications-review channel
(Admin + MANAVA Team only), so it may include the applicant's contact details —
that's inside the private flow. It must never be reproduced in a public
channel or a generic log.
"""

from __future__ import annotations

import discord

from src.models.application import Application, AppStatus, field_specs

_STATUS_COLOR = {
    AppStatus.PENDING: discord.Color.blurple(),
    AppStatus.MORE_INFO_REQUESTED: discord.Color.orange(),
    AppStatus.APPROVED: discord.Color.green(),
    AppStatus.REJECTED: discord.Color.red(),
}

_STATUS_LABEL = {
    AppStatus.PENDING: "Pending review",
    AppStatus.MORE_INFO_REQUESTED: "Awaiting applicant response",
    AppStatus.APPROVED: "Approved",
    AppStatus.REJECTED: "Rejected",
}


def render_application_embed(app: Application, *, extra_note: str | None = None) -> discord.Embed:
    embed = discord.Embed(
        title=f"{app.app_type.label} Application",
        color=_STATUS_COLOR.get(app.status, discord.Color.greyple()),
        timestamp=app.submitted_at,
    )
    embed.add_field(name="Applicant", value=f"<@{app.applicant_id}> (`{app.applicant_username}`)", inline=False)
    embed.add_field(name="Status", value=_STATUS_LABEL.get(app.status, app.status.value), inline=False)

    for spec in field_specs(app.app_type):
        value = (app.fields.get(spec.key) or "").strip()
        if not value:
            continue
        # Discord field values cap at 1024 chars.
        embed.add_field(name=spec.label, value=value[:1024], inline=False)

    if extra_note:
        embed.add_field(name="Note", value=extra_note[:1024], inline=False)

    embed.set_footer(text=f"Application {app.id}")
    return embed
