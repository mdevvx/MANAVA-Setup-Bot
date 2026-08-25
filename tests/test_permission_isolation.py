"""Explicit proof of cross-squad permission isolation (Phase 1 requirement).

Officer Text/Voice access is keyed off individual member-ID overwrites for a
squad's own Leader + Officers, not the shared global "Squad Officer" role.
These tests assert that building overwrites for one squad never includes
another squad's leader/officers, and vice versa.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from src.discord_state.provisioning import build_member_channel_overwrites, build_officer_channel_overwrites


def _fake_state() -> SimpleNamespace:
    guild = MagicMock(name="guild")
    guild.default_role = MagicMock(name="@everyone")
    staff_roles = (MagicMock(name="Admin"), MagicMock(name="MANAVA Team"))
    roles = SimpleNamespace(staff_roles=staff_roles)
    return SimpleNamespace(guild=guild, roles=roles)


def test_officer_overwrites_for_one_squad_never_include_another_squads_leader() -> None:
    state = _fake_state()
    squad_a_leader = MagicMock(name="SquadALeader")
    squad_b_leader = MagicMock(name="SquadBLeader")

    overwrites_a = build_officer_channel_overwrites(state, [squad_a_leader])  # type: ignore[arg-type]
    overwrites_b = build_officer_channel_overwrites(state, [squad_b_leader])  # type: ignore[arg-type]

    assert squad_a_leader in overwrites_a
    assert squad_b_leader not in overwrites_a
    assert squad_b_leader in overwrites_b
    assert squad_a_leader not in overwrites_b


def test_officer_overwrites_never_leak_between_squads_officer_sets() -> None:
    state = _fake_state()
    squad_a_leader, squad_a_officer = MagicMock(name="A-Leader"), MagicMock(name="A-Officer")
    squad_b_leader, squad_b_officer = MagicMock(name="B-Leader"), MagicMock(name="B-Officer")

    overwrites_a = build_officer_channel_overwrites(state, [squad_a_leader, squad_a_officer])  # type: ignore[arg-type]
    overwrites_b = build_officer_channel_overwrites(state, [squad_b_leader, squad_b_officer])  # type: ignore[arg-type]

    a_authorized = {squad_a_leader, squad_a_officer}
    b_authorized = {squad_b_leader, squad_b_officer}

    assert a_authorized.issubset(overwrites_a.keys())
    assert b_authorized.isdisjoint(overwrites_a.keys())
    assert b_authorized.issubset(overwrites_b.keys())
    assert a_authorized.isdisjoint(overwrites_b.keys())


def test_member_overwrites_key_off_squad_specific_role_only() -> None:
    state = _fake_state()
    squad_a_role = MagicMock(name="SquadARole")
    squad_b_role = MagicMock(name="SquadBRole")

    overwrites_a = build_member_channel_overwrites(state, squad_a_role)  # type: ignore[arg-type]
    overwrites_b = build_member_channel_overwrites(state, squad_b_role)  # type: ignore[arg-type]

    assert squad_a_role in overwrites_a
    assert squad_b_role not in overwrites_a
    assert squad_b_role in overwrites_b
    assert squad_a_role not in overwrites_b
