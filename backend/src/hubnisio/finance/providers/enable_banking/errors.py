"""Enable Banking errors, told apart by the text code in the body, not the HTTP status.

Error bodies look like `{"message": ..., "code": <http status>, "error": "<CODE>", "detail": ...}`.
"""


class EnableBankingError(Exception):
    def __init__(self, status: int, code: str | None, message: str) -> None:
        # Only the status and code go into str(): messages could echo request details.
        super().__init__(f"Enable Banking error {status} {code or '(no code)'}")
        self.status = status
        self.code = code
        self.message = message


class SessionEnded(EnableBankingError):
    """The consent session is expired, closed or revoked: the user has to link again."""

    CODES = frozenset({"EXPIRED_SESSION", "CLOSED_SESSION", "REVOKED_SESSION"})


class RateLimited(EnableBankingError):
    """The bank's limit on unattended fetches (often 4 a day) is used up; retry hours later."""


class WrongPeriod(EnableBankingError):
    """The bank can't return transactions for the requested dates."""


class AlreadyAuthorized(EnableBankingError):
    """The authorization code was already turned into a session, e.g. a refreshed callback."""


class PaginationError(Exception):
    """Transaction pages never ended: a continuation key repeated, or too many pages."""


def error_for(status: int, code: str | None, message: str) -> EnableBankingError:
    if code in SessionEnded.CODES:
        return SessionEnded(status, code, message)
    if code == "ASPSP_RATE_LIMIT_EXCEEDED" or status == 429:
        return RateLimited(status, code, message)
    if code == "WRONG_TRANSACTIONS_PERIOD":
        return WrongPeriod(status, code, message)
    if code == "ALREADY_AUTHORIZED":
        return AlreadyAuthorized(status, code, message)
    return EnableBankingError(status, code, message)
