"""Reviewer-permission boundary: only Admin / MANAVA Team pass the elevated-staff
gate the application review view uses. Moderator and Senior Moderator are staff
elsewhere but are explicitly excluded from application review (spec)."""

from __future__ import annotations

from types import SimpleNamespace

from src.discord_state.staff_check import is_elevated_staff


class _Role:
    def __init__(self, role_id: int) -> None:
        self.id = role_id


def _member(*role_ids: int, administrator: bool = False) -> SimpleNamespace:
    return SimpleNamespace(
        roles=[_Role(r) for r in role_ids],
        guild_permissions=SimpleNamespace(administrator=administrator),
    )


def _bot(admin_id: int = 10, manava_id: int = 11) -> SimpleNamespace:
    guild_state = SimpleNamespace(
        roles=SimpleNamespace(admin=_Role(admin_id), manava_team=_Role(manava_id))
    )
    return SimpleNamespace(guild_state=guild_state)


def test_moderator_and_senior_moderator_are_not_elevated() -> None:
    bot = _bot()
    moderator = _member(20)          # some Moderator role id
    senior_moderator = _member(21)   # some Senior Moderator role id
    assert is_elevated_staff(bot, moderator) is False
    assert is_elevated_staff(bot, senior_moderator) is False


def test_admin_and_manava_team_are_elevated() -> None:
    bot = _bot(admin_id=10, manava_id=11)
    assert is_elevated_staff(bot, _member(10)) is True
    assert is_elevated_staff(bot, _member(11)) is True


def test_server_administrator_permission_is_a_bootstrap_fallback() -> None:
    bot = _bot()
    assert is_elevated_staff(bot, _member(99, administrator=True)) is True
