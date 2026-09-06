"""Per-application-type review channel overrides (/admin set-application-channel)
and how finalize_submission picks the target channel."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from src.db.repositories import bot_config as bot_config_repo
from src.models.application import Application, AppStatus, AppType
from src.services import application_actions


@pytest.mark.asyncio
async def test_set_and_get_review_channel_roundtrip(monkeypatch: pytest.MonkeyPatch) -> None:
    store: dict[str, object] = {}

    async def fake_get(conn: object, key: str, default: object) -> object:
        return store.get(key, default)

    async def fake_set(conn: object, key: str, value: object) -> None:
        store[key] = value

    monkeypatch.setattr(bot_config_repo, "get_value", fake_get)
    monkeypatch.setattr(bot_config_repo, "set_value", fake_set)

    await bot_config_repo.set_application_review_channel(object(), "developer", 111)  # type: ignore[arg-type]
    await bot_config_repo.set_application_review_channel(object(), "creator_streamer", 222)  # type: ignore[arg-type]
    assert await bot_config_repo.get_application_review_channels(object()) == {  # type: ignore[arg-type]
        "developer": 111,
        "creator_streamer": 222,
    }

    # Passing None clears just that type.
    await bot_config_repo.set_application_review_channel(object(), "developer", None)  # type: ignore[arg-type]
    assert await bot_config_repo.get_application_review_channels(object()) == {"creator_streamer": 222}  # type: ignore[arg-type]


def _app(app_type: AppType) -> Application:
    return Application(
        id=uuid4(),
        applicant_id=1,
        applicant_username="u#1",
        app_type=app_type,
        status=AppStatus.PENDING,
        fields={},
        review_channel_id=None,
        review_message_id=None,
        submitted_at=None,  # type: ignore[arg-type]
        decided_at=None,
        decided_by=None,
    )


class _Channel:
    def __init__(self, name: str) -> None:
        self.name = name
        self.id = 999
        self.send = AsyncMock(return_value=SimpleNamespace(id=5, channel=SimpleNamespace(id=999)))


@pytest.mark.asyncio
async def test_finalize_uses_configured_channel_then_falls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    import discord

    default_channel = _Channel("applications-review")
    custom_channel = _Channel("dev-apps")
    monkeypatch.setattr(discord, "TextChannel", _Channel)  # make isinstance(candidate, TextChannel) pass

    async def fake_set_review_message(conn: object, app_id: object, *, channel_id: int, message_id: int) -> None:
        return None

    monkeypatch.setattr(application_actions.applications_repo, "set_review_message", fake_set_review_message)
    monkeypatch.setattr(application_actions, "_dm", AsyncMock(return_value=True))
    monkeypatch.setattr(application_actions.role_safety, "assign_role", AsyncMock())

    class _Pool:
        def acquire(self) -> object:
            class _Ctx:
                async def __aenter__(self) -> object:
                    return object()

                async def __aexit__(self, *a: object) -> None:
                    return None

            return _Ctx()

    bot = SimpleNamespace(
        require_guild_state=lambda: SimpleNamespace(),
        require_application_state=lambda: SimpleNamespace(
            review_channel=default_channel, role_by_name=lambda n: SimpleNamespace()
        ),
        application_review_channel_ids={"developer": 42},
        get_channel=lambda cid: custom_channel if cid == 42 else None,
        db_pool=_Pool(),
        config=SimpleNamespace(guild_id=1),
    )

    applicant = SimpleNamespace(id=1)

    # Configured -> posts to the custom channel.
    await application_actions.finalize_submission(bot, applicant=applicant, app=_app(AppType.DEVELOPER))  # type: ignore[arg-type]
    custom_channel.send.assert_awaited_once()
    default_channel.send.assert_not_awaited()

    # Creator/Streamer has no override -> default channel.
    await application_actions.finalize_submission(
        bot, applicant=applicant, app=_app(AppType.CREATOR_STREAMER)  # type: ignore[arg-type]
    )
    default_channel.send.assert_awaited_once()
