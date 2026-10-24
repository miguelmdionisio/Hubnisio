"""Trading 212 errors, told apart by HTTP status. Each carries the code a failed sync records
in `finance.sync_runs.error_code`."""


class Trading212Error(Exception):
    CODE = "UNEXPECTED"

    def __init__(self, message: str = "", *, code: str | None = None) -> None:
        self.code = code or self.CODE
        # Only the code goes into str(): a message could echo request details.
        super().__init__(f"Trading 212 error {self.code}")
        self.message = message


class KeyRejected(Trading212Error):
    """401: the key is wrong or deleted, or limited to other IP addresses. Link again."""

    CODE = "KEY_REJECTED"


class MissingPermission(Trading212Error):
    """403: the key lacks a permission the endpoint needs (account data, history, portfolio)."""

    CODE = "MISSING_PERMISSION"


class RateLimited(Trading212Error):
    """429, still, after waiting for the limit to reset a few times."""

    CODE = "RATE_LIMITED"


class KeyFileError(Trading212Error):
    """The key's file is missing, unreadable, or not in the documented format."""

    CODE = "KEY_FILE"


class WrongAccount(Trading212Error):
    """The key reads another Trading 212 account than the one the connection links."""

    CODE = "WRONG_ACCOUNT"


class PaginationError(Trading212Error):
    """History pages never ended: a page path repeated, or too many pages."""

    CODE = "PAGINATION"


def error_for(status: int) -> Trading212Error:
    match status:
        case 401:
            return KeyRejected()
        case 403:
            return MissingPermission()
        case 429:
            return RateLimited()
        case _:
            return Trading212Error(code=f"HTTP_{status}")
