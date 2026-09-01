"""Least-privilege hard guard: the bot must never be able to grant Admin,
MANAVA Team, Senior Moderator or Moderator — even if calling code has a bug."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.discord_state import role_safety
from src.discord_state.role_resolver import ResolvedGuildState, ResolvedRoles
from src.errors import DiscordSetupError


def _role(role_id: int, name: str) -> SimpleNamespace:
    return SimpleNamespace(id=role_id, name=name)


def _state() -> ResolvedGuildState:
    roles = ResolvedRoles(
        admin=_role(1, "Admin"),  # type: ignore[arg-type]
        manava_team=_role(2, "MANAVA Team"),  # type: ignore[arg-type]
        senior_moderator=_role(3, "Senior Moderator"),  # type: ignore[arg-type]
        moderator=_role(4, "Moderator"),  # type: ignore[arg-type]
        squad_leader=_role(5, "Squad Leader"),  # type: ignore[arg-type]
        squad_officer=_role(6, "Squad Officer"),  # type: ignore[arg-type]
        squad_member=_role(7, "Squad Member"),  # type: ignore[arg-type]
        member=_role(8, "Member"),  # type: ignore[arg-type]
    )
    return ResolvedGuildState(guild=SimpleNamespace(), roles=roles, squad_categories=())  # type: ignore[arg-type]


@pytest.mark.parametrize("protected_id,protected_name", [(1, "Admin"), (2, "MANAVA Team"), (3, "Senior Moderator"), (4, "Moderator")])
def test_ensure_assignable_blocks_every_protected_role(protected_id: int, protected_name: str) -> None:
    with pytest.raises(DiscordSetupError):
        _state().ensure_assignable(_role(protected_id, protected_name))  # type: ignore[arg-type]


def test_ensure_assignable_allows_non_protected_roles() -> None:
    _state().ensure_assignable(_role(999, "Developer"))  # type: ignore[arg-type]  # no raise


@pytest.mark.asyncio
async def test_assign_role_refuses_protected_before_touching_discord() -> None:
    member = SimpleNamespace(roles=[], add_roles=AsyncMock())
    with pytest.raises(DiscordSetupError):
        await role_safety.assign_role(
            _state(), member, _role(1, "Admin"), reason="buggy caller"  # type: ignore[arg-type]
        )
    member.add_roles.assert_not_awaited()
