"""Trading 212 Public API client (https://docs.trading212.com/api), read-only.

Every call carries the API key and secret as HTTP Basic auth. The key lives in a file
(`read_key_file`), never in the database, and never in a stored payload or a log.

Rate limits are per account and per endpoint, and every response says where it stands in
`x-ratelimit-*` headers (`reset` is a Unix time). When an endpoint's allowance is used up, the
next call to it waits for the reset; a 429 waits too, and gives up after a few tries.
"""

import asyncio
import time
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from types import TracebackType
from typing import Any, Self

import httpx

from hubnisio.finance.providers.base import Fetched
from hubnisio.finance.providers.trading212.errors import (
    KeyFileError,
    PaginationError,
    RateLimited,
    Trading212Error,
    WrongAccount,
    error_for,
)
from hubnisio.finance.providers.trading212.schemas import AccountSummary, HistoryPage, day_of

API_URL = "https://live.trading212.com"
API_PREFIX = "/api/v0"
SUMMARY_PATH = f"{API_PREFIX}/equity/account/summary"
# The history endpoints read in a sync, and the field that dates their items.
HISTORY = {"transactions": "dateTime", "dividends": "paidOn"}
PAGE_SIZE = 50  # the most the API gives per page
MAX_PAGES = 1000
MAX_ATTEMPTS = 4  # per request, while answered 429
MIN_BACKOFF = 1.0  # seconds after a 429, doubling per try, when the reset time doesn't say
MAX_WAIT = 120.0  # never wait longer than this for one reset (the longest period is a minute)


@dataclass(frozen=True, slots=True)
class ApiKey:
    key: str = field(repr=False)
    secret: str = field(repr=False)


def read_key_file(path: Path) -> ApiKey:
    """A key file holds two lines, `key=<API key>` and `secret=<API secret>`. Blank lines and
    lines starting with # are ignored. Errors name the file and the line, never a value."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        reason = exc.strerror or type(exc).__name__
        raise KeyFileError(f"Can't read the key file {path}: {reason}.") from None
    values: dict[str, str] = {}
    for number, line in enumerate(text.splitlines(), start=1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        name, sep, value = line.partition("=")
        name = name.strip().lower()
        if not sep or name not in ("key", "secret"):
            raise KeyFileError(f"Line {number} of {path} isn't `key=…` or `secret=…`.")
        if name in values:
            raise KeyFileError(f"{path} has more than one `{name}=` line.")
        values[name] = value.strip()
    missing = [name for name in ("key", "secret") if not values.get(name)]
    if missing:
        raise KeyFileError(f"{path} has no {' or '.join(f'`{name}=`' for name in missing)} line.")
    return ApiKey(values["key"], values["secret"])


class Trading212Client:
    def __init__(
        self,
        key: ApiKey | Path,
        *,
        http: httpx.AsyncClient | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        clock: Callable[[], float] = time.time,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        """`key` is the key itself, or its file, read at the first request."""
        self._key = key
        self._owns_http = http is None
        self._http = http or httpx.AsyncClient(base_url=API_URL, timeout=30, transport=transport)
        self._clock = clock
        self._sleep = sleep
        self._ready_at: dict[str, float] = {}  # path -> when its allowance is back

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._owns_http:
            await self._http.aclose()

    # Data

    async def fetch(
        self,
        account_uid: str,
        since: date | None,
        psu_headers: Mapping[str, str] | None = None,
    ) -> AsyncIterator[Fetched[Any]]:
        """The summary, then cash movements and dividends: all of them when `since` is None,
        else newest first until a page reaches back past `since`. `psu_headers` are for banks."""
        summary = await self.get_summary()
        if str(summary.data.id) != account_uid:
            raise WrongAccount()
        yield summary
        for endpoint in HISTORY:
            async for page in self.iter_history(endpoint, since=since):
                yield page

    async def get_summary(self) -> Fetched[AccountSummary]:
        raw = await self._get(SUMMARY_PATH)
        return Fetched(
            "summary",
            {"method": "GET", "path": SUMMARY_PATH},
            raw,
            AccountSummary.model_validate(raw),
        )

    async def iter_history(
        self, endpoint: str, *, since: date | None = None
    ) -> AsyncIterator[Fetched[HistoryPage]]:
        """Pages of `GET /equity/history/<endpoint>`, following `nextPagePath` until it's null,
        or until a page holds an item dated before `since`."""
        date_field = HISTORY[endpoint]
        path = f"{API_PREFIX}/equity/history/{endpoint}"
        params = {"limit": str(PAGE_SIZE)}
        seen: set[str] = set()
        for _ in range(MAX_PAGES):
            raw = await self._get(path, params)
            page = HistoryPage.model_validate(raw)
            yield Fetched(endpoint, {"method": "GET", "path": path, "params": params}, raw, page)
            following = page.next_page_path
            if not following:
                return
            if since is not None and _reaches_back(page, date_field, since):
                return
            if following in seen:
                raise PaginationError("Trading 212 repeated a page path.")
            seen.add(following)
            url = httpx.URL(following)
            path = url.path if url.path.startswith(f"{API_PREFIX}/") else API_PREFIX + url.path
            params = dict(url.params)
        raise PaginationError(f"{endpoint} ran past {MAX_PAGES} pages.")

    # Plumbing

    def _auth(self) -> httpx.BasicAuth:
        if isinstance(self._key, Path):
            self._key = read_key_file(self._key)
        return httpx.BasicAuth(self._key.key, self._key.secret)

    async def _get(self, path: str, params: Mapping[str, str] | None = None) -> dict[str, Any]:
        auth = self._auth()
        attempts = 0
        while True:
            await self._wait_for(path)
            response = await self._http.get(path, params=params, auth=auth)
            reset = self._note_limit(path, response)
            if response.status_code != httpx.codes.TOO_MANY_REQUESTS:
                break
            attempts += 1
            if attempts == MAX_ATTEMPTS:
                raise RateLimited()
            # Wait for the reset; back off instead if it's past (clocks differ) or not given.
            backoff = MIN_BACKOFF * 2 ** (attempts - 1)
            self._ready_at[path] = max(reset or 0.0, self._clock() + backoff)
        if response.is_error:
            raise error_for(response.status_code)
        try:
            body = response.json()
        except ValueError:
            raise Trading212Error(code="UNEXPECTED_RESPONSE") from None
        if not isinstance(body, dict):
            raise Trading212Error(code="UNEXPECTED_RESPONSE")
        return body

    def _note_limit(self, path: str, response: httpx.Response) -> float | None:
        """Remember when the path's allowance is back if this response used it up. Returns the
        reset time the response gave."""
        remaining = _number(response.headers.get("x-ratelimit-remaining"))
        reset = _number(response.headers.get("x-ratelimit-reset"))
        if remaining is not None and remaining <= 0 and reset is not None:
            self._ready_at[path] = reset
        return reset

    async def _wait_for(self, path: str) -> None:
        ready_at = self._ready_at.pop(path, None)
        if ready_at is None:
            return
        delay = min(ready_at - self._clock(), MAX_WAIT)
        if delay > 0:
            await self._sleep(delay)


def _reaches_back(page: HistoryPage, date_field: str, since: date) -> bool:
    """Whether the page holds an item dated before `since`: older pages hold nothing new."""
    for item in page.items:
        value = item.get(date_field)
        if not isinstance(value, str):
            continue
        try:
            moment = datetime.fromisoformat(value)
        except ValueError:
            continue
        if day_of(moment) < since:
            return True
    return False


def _number(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except ValueError:
        return None
