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


# --- Phase 3: applications ---


class DuplicateApplicationError(BotUserError):
    def __init__(self, type_label: str) -> None:
        super().__init__(
            f"You already have an open {type_label} application. Wait for it to be reviewed before submitting another."
        )


class ApplicationCooldownError(BotUserError):
    def __init__(self, type_label: str, days_left: int) -> None:
        super().__init__(
            f"Your last {type_label} application was declined. You can reapply in {days_left} day(s)."
        )


class ApplicationNotFoundError(BotUserError):
    def __init__(self) -> None:
        super().__init__("That application no longer exists.")


class ApplicationAlreadyDecidedError(BotUserError):
    def __init__(self) -> None:
        super().__init__("This application has already been decided — nothing more to do here.")


# --- Phase 3: seasons ---


class SeasonStateError(BotUserError):
    """Start/End Season called in a state that doesn't allow it (e.g. no active season to end)."""

    def __init__(self, message: str) -> None:
        super().__init__(message)


# --- Phase 3: MANAVA Gateway ---


class GatewayError(Exception):
    """A call to the MANAVA Gateway failed (network, non-2xx, bad body). Internal —
    callers decide whether to fall back to cached/manual data or surface it."""


class GatewayDisabledError(GatewayError):
    """Gateway mode is off (MANAVA_GATEWAY_BASE_URL / DISCORD_BACKEND_API_KEY unset)."""
