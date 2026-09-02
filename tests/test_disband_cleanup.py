"""On disband, the shared Squad Leader/Officer/Member rank roles must be
stripped from every squad member (the squad-specific role is deleted, which
Discord auto-removes, but the shared roles are not)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.discord_state.provisioning import revoke_all_member_access


@pytest.mark.asyncio
async def test_disband_strips_shared_rank_roles_from_every_member() -> None:
    squad_leader_role = MagicMock(name="Squad Leader")
    squad_officer_role = MagicMock(name="Squad Officer")
    squad_member_role = MagicMock(name="Squad Member")
    squad_specific_role = MagicMock(name="Squad Alpha")

    # Two members: one leader (Squad Leader + Squad Member), one plain member.
    leader = SimpleNamespace(id=1, roles=[squad_specific_role, squad_leader_role, squad_member_role], remove_roles=AsyncMock())
    plain = SimpleNamespace(id=2, roles=[squad_specific_role, squad_member_role], remove_roles=AsyncMock())
    squad_specific_role.members = [leader, plain]
    squad_specific_role.delete = AsyncMock()

    guild = MagicMock()
    guild.get_role.return_value = squad_specific_role
    guild.get_channel.return_value = None  # no officer channels to touch in this test

    state = SimpleNamespace(
        guild=guild,
        roles=SimpleNamespace(
            squad_leader=squad_leader_role,
            squad_officer=squad_officer_role,
            squad_member=squad_member_role,
        ),
    )
    squad = SimpleNamespace(role_id=999, id="s1", officer_text_channel_id=10, officer_voice_channel_id=11)

    await revoke_all_member_access(state, squad)  # type: ignore[arg-type]

    leader.remove_roles.assert_awaited_once()
    stripped_from_leader = set(leader.remove_roles.await_args.args)
    assert stripped_from_leader == {squad_leader_role, squad_member_role}

    plain.remove_roles.assert_awaited_once()
    assert set(plain.remove_roles.await_args.args) == {squad_member_role}

    squad_specific_role.delete.assert_awaited_once()
