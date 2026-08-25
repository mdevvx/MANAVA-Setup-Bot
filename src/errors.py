from __future__ import annotations


class BotUserError(Exception):
    """Base for errors whose message is safe to show directly to a Discord user.

    Anything NOT wrapped in a BotUserError subclass is treated as an internal
    error by the command error handler: logged with a full traceback, and shown
    to the user only as a generic friendly message.
    """

    def __init__(self, user_message: str) -> None:
        super().__init__(user_message)
        self.user_message = user_message


class DuplicateSquadNameError(BotUserError):
    def __init__(self, name: str) -> None:
        super().__init__(f"A squad named **{name}** already exists (or existed). Choose a different name.")


class AlreadyInSquadError(BotUserError):
    def __init__(self) -> None:
        super().__init__("You're already in a squad. Leave your current squad first.")


class AlreadyAppliedError(BotUserError):
    def __init__(self) -> None:
        super().__init__("You already have a pending application to this squad.")


class SquadNotFoundError(BotUserError):
    def __init__(self) -> None:
        super().__init__("That squad doesn't exist or is no longer active.")


class NotSquadMemberError(BotUserError):
    def __init__(self) -> None:
        super().__init__("You're not a member of that squad.")


class InsufficientSquadPermissionError(BotUserError):
    def __init__(self) -> None:
        super().__init__("You don't have permission to do that in this squad.")


class OfficerLimitReachedError(BotUserError):
    def __init__(self, limit: int) -> None:
        super().__init__(f"This squad already has the maximum of {limit} officers.")


class CapacityExceededError(BotUserError):
    def __init__(self) -> None:
        super().__init__("The server is at maximum squad capacity right now. Please contact staff.")


class InvalidSquadStateError(BotUserError):
    def __init__(self, message: str) -> None:
        super().__init__(message)


class DiscordSetupError(BotUserError):
    """Raised when required Discord roles/categories can't be resolved on the guild."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
