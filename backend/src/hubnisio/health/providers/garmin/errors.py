"""Garmin errors. Each carries the code a failed sync records in `health.sync_runs.error_code`."""


class GarminError(Exception):
    CODE = "UNEXPECTED"

    def __init__(self, message: str = "", *, code: str | None = None) -> None:
        self.code = code or self.CODE
        # Only the code goes into str(): a message could echo request details.
        super().__init__(f"Garmin error {self.code}")
        self.message = message


class KeyRejected(GarminError):
    """The token exchange refused the key (wrong, deleted or lapsed), or a fresh token was
    refused too. Link a new key."""

    CODE = "KEY_REJECTED"


class RateLimited(GarminError):
    """429, still, after backing off a few times."""

    CODE = "RATE_LIMITED"


class KeyFileError(GarminError):
    """The key's file is missing, unreadable, or not in the documented format."""

    CODE = "KEY_FILE"


def error_for(status: int) -> GarminError:
    match status:
        case 401:
            return KeyRejected()
        case 429:
            return RateLimited()
        case _:
            return GarminError(code=f"HTTP_{status}")
