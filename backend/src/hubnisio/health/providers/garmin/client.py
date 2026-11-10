"""Garmin Connect Personal API client (ADR-0009), read-only.

The member's personal key lives in a file (`read_key_file`), never in the database, a stored
payload or a log. It is exchanged for a token: `POST` the key as `Authorization: ApiKey <key>`
and the reply's body is the token itself, as plain text (a JWT valid about 24 hours). Data calls
send it as `Authorization: Bearer <token>`. There is no refresh token: the client exchanges the
key again when the token's `exp` is near, or once when a call is answered 401.

Garmin publishes no rate limits, so the client is polite: one call at a time, a short pause
between calls, and on 429 it waits (`Retry-After`, else 5 s doubling) and gives up after a few
tries.

Each endpoint is described once in `ENDPOINTS`: its path, and the most days one call may cover
(`window`; 1 for an endpoint that takes one day, None for one that isn't about days). The sync
splits a period into windows; the client makes one call per window.
"""

import asyncio
import base64
import binascii
import json
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from types import TracebackType
from typing import Any, Self

import httpx

from hubnisio.health.providers.garmin.errors import (
    GarminError,
    KeyFileError,
    KeyRejected,
    RateLimited,
    error_for,
)

API_URL = "https://personal.connectapi.garmin.com"
TOKEN_PATH = "/personalapitoken-service/personal-api/personal-api-key/token"  # noqa: S105
USER_AGENT = "Hubnisio/0.1 (self-hosted personal hub)"

PAUSE = 0.5  # seconds between two calls
FILE_PAUSE = 2.0  # seconds before an activity file's download, the heavy call
ACTIVITY_PAGE = 100  # activities per search page (Garmin's default is 99; 100 works)
MAX_FILE_BYTES = 32 * 1024 * 1024  # an activity's zip is a few hundred KB
SEARCH_PATH = "/activitylist-service/activities/search/activities"
DETAIL_PATH = "/activity-service/activity/{activity_id}"
DOWNLOAD_PATH = "/download-service/files/activity/{activity_id}"
MAX_ATTEMPTS = 5  # per call, while answered 429
MIN_BACKOFF = 5.0  # seconds after the first 429, doubling, when Retry-After doesn't say
MAX_WAIT = 300.0  # never wait longer than this at once
TOKEN_MARGIN = 300.0  # exchange the key again this many seconds before the token's exp
TOKEN_FALLBACK_LIFETIME = 23 * 3600.0  # when the token's exp can't be read

# How many days one weight call covers: a 365-day range was answered 400, 364 days work.
WEIGHT_WINDOW = 180


@dataclass(frozen=True, slots=True)
class Endpoint:
    kind: str  # the payload kind it's stored as
    path: str  # may hold {start}, {end} and {day}
    params: tuple[tuple[str, str], ...] = ()  # query parameters, with the same placeholders
    window: int | None = None  # the most days per call; 1: one day; None: not about days

    def request(self, start: date, end: date) -> tuple[str, dict[str, str]]:
        values = {"start": start.isoformat(), "end": end.isoformat(), "day": start.isoformat()}
        path = self.path.format(**values)
        return path, {name: value.format(**values) for name, value in self.params}


_RANGE = (("startDate", "{start}"), ("endDate", "{end}"))

ENDPOINTS: dict[str, Endpoint] = {
    endpoint.kind: endpoint
    for endpoint in (
        Endpoint("profile", "/userprofile-service/userprofile/settings"),
        Endpoint("hr_zones", "/biometric-service/heartRateZones/v2"),
        Endpoint("daily_summaries", "/usersummary-service/v2/dailysummaries", _RANGE, 364),
        Endpoint("hrv", "/hrv-service/hrv/daily/{start}/{end}", window=28),
        Endpoint("sleep", "/sleep-service/sleep/dailySleepSummariesByDate", _RANGE, 31),
        Endpoint(
            "body_battery", "/wellness-service/wellness/bodyBattery/reports/daily", _RANGE, 31
        ),
        Endpoint("stress", "/usersummary-service/stats/stress/daily/{start}/{end}", window=28),
        Endpoint("steps", "/usersummary-service/stats/steps/daily/{start}/{end}", window=28),
        Endpoint("weight", "/weight-service/weight/range/{start}/{end}", window=WEIGHT_WINDOW),
        Endpoint("hrv_readings", "/hrv-service/hrv/{day}", window=1),
        Endpoint(
            "heart_rate", "/wellness-service/wellness/dailyHeartRate", (("date", "{day}"),), 1
        ),
        Endpoint("spo2", "/wellness-service/wellness/daily/spo2acclimation/{day}", window=1),
        # Read for one day, today: what it says now.
        Endpoint("fitness_age", "/fitnessage-service/fitnessage/v2/{day}", window=1),
        Endpoint(
            "weight_goal", "/goal-service/goal/user/effective/weightgoal/{start}/{end}", window=364
        ),
    )
}


@dataclass(frozen=True, slots=True)
class ApiKey:
    key: str = field(repr=False)


@dataclass(frozen=True, slots=True)
class Fetched:
    """One reply: what was asked, the days it covers, and the raw JSON (None: no body)."""

    kind: str
    request: dict[str, Any]
    raw: Any
    day_from: date | None = None
    day_to: date | None = None


def read_key_file(path: Path) -> ApiKey:
    """A key file holds one line, `key=<personal API key>` or the bare key. Blank lines and
    lines starting with # are ignored. Errors name the file and the line, never a value."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        reason = exc.strerror or type(exc).__name__
        raise KeyFileError(f"Can't read the key file {path}: {reason}.") from None
    key: str | None = None
    for number, line in enumerate(text.splitlines(), start=1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        name, sep, value = line.partition("=")
        if sep and name.strip().lower() == "key":
            found = value.strip()
        elif not any(ch.isspace() for ch in line) and not (sep and name.isalpha()):
            found = line  # the bare key on a line of its own, as Garmin shows it
        else:
            raise KeyFileError(f"Line {number} of {path} isn't `key=…`.")
        if key is not None:
            raise KeyFileError(f"{path} has more than one `key=` line.")
        key = found
    if not key:
        raise KeyFileError(f"{path} has no `key=` line.")
    return ApiKey(key)


def token_expiry(token: str) -> float | None:
    """The `exp` claim (a Unix time) of a JWT, read without checking its signature: only to know
    when to exchange the key again. None when it can't be read."""
    parts = token.split(".")
    if len(parts) != 3:
        return None
    body = parts[1] + "=" * (-len(parts[1]) % 4)
    try:
        claims = json.loads(base64.urlsafe_b64decode(body))
    except binascii.Error, ValueError:
        return None
    exp = claims.get("exp") if isinstance(claims, dict) else None
    return float(exp) if isinstance(exp, int | float) and not isinstance(exp, bool) else None


class GarminClient:
    def __init__(
        self,
        key: ApiKey | Path,
        *,
        http: httpx.AsyncClient | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        clock: Callable[[], float] = time.time,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        pause: float = PAUSE,
    ) -> None:
        """`key` is the key itself, or its file, read at the first exchange."""
        self._key = key
        self._owns_http = http is None
        self._http = http or httpx.AsyncClient(
            base_url=API_URL,
            timeout=60,
            transport=transport,
            headers={"User-Agent": USER_AGENT},  # no Accept: Garmin answers 406 to application/json
        )
        self._clock = clock
        self._sleep = sleep
        self._pause = pause
        self._token: str | None = None
        self._token_until = 0.0
        self._last_call: float | None = None

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

    async def fetch(self, kind: str, start: date, end: date | None = None) -> Fetched:
        """One call to the endpoint of `kind`, for the days from `start` to `end` (or `start`
        alone). An endpoint not about days ignores them."""
        endpoint = ENDPOINTS[kind]
        end = end or start
        if endpoint.window is not None and (end - start).days + 1 > endpoint.window:
            raise ValueError(f"{kind} takes at most {endpoint.window} days per call.")
        path, params = endpoint.request(start, end)
        raw = await self.get_json(path, params)
        request: dict[str, Any] = {"method": "GET", "path": path}
        if params:
            request["params"] = params
        if endpoint.window is None:
            return Fetched(kind, request, raw)
        return Fetched(kind, request, raw, start, end)

    async def get_profile(self) -> Fetched:
        return await self.fetch("profile", date.today())

    # Activities

    async def search_activities(self, first: date, last: date, start: int = 0) -> Fetched:
        """One page of the activities that started from `first` to `last`, oldest first.
        Multisport legs are listed too (`excludeChildren=false`)."""
        params = {
            "startDate": first.isoformat(),
            "endDate": last.isoformat(),
            "start": str(start),
            "limit": str(ACTIVITY_PAGE),
            "sortOrder": "asc",
            "excludeChildren": "false",
        }
        raw = await self.get_json(SEARCH_PATH, params)
        request: dict[str, Any] = {"method": "GET", "path": SEARCH_PATH, "params": params}
        return Fetched("activities", request, raw, first, last)

    async def activity_detail(self, activity_id: int) -> Fetched:
        path = DETAIL_PATH.format(activity_id=activity_id)
        raw = await self.get_json(path)
        return Fetched("activity_detail", {"method": "GET", "path": path}, raw)

    async def download_activity(self, activity_id: int) -> tuple[bytes, str | None]:
        """The activity's original file as Garmin sends it (a zip holding one .FIT) and its
        content type. Paced more slowly than the other calls; no Accept header either."""
        path = DOWNLOAD_PATH.format(activity_id=activity_id)
        response = await self._get(path, pause=FILE_PAUSE)
        if response.is_error:
            raise error_for(response.status_code)
        if not response.content:
            raise GarminError(code="EMPTY_FILE")
        if len(response.content) > MAX_FILE_BYTES:
            raise GarminError(code="FILE_TOO_LARGE")
        return response.content, response.headers.get("content-type")

    async def get_json(self, path: str, params: Mapping[str, str] | None = None) -> Any:
        """GET a path: the parsed JSON, or None when the reply has no body."""
        response = await self._get(path, params)
        if response.is_error:
            raise error_for(response.status_code)
        if not response.content.strip():
            return None
        try:
            return response.json()
        except ValueError:
            raise GarminError(code="UNEXPECTED_RESPONSE") from None

    async def _get(
        self, path: str, params: Mapping[str, str] | None = None, *, pause: float | None = None
    ) -> httpx.Response:
        """GET with the token: exchanges the key again once on 401, backs off on 429."""
        refreshed = False
        attempts = 0
        while True:
            token = await self._valid_token()
            response = await self._call(
                "GET", path, params=params, auth=f"Bearer {token}", pause=pause
            )
            if response.status_code == httpx.codes.UNAUTHORIZED and not refreshed:
                # The token lapsed early or was revoked: exchange the key once more.
                refreshed = True
                self._token = None
                continue
            if response.status_code == httpx.codes.TOO_MANY_REQUESTS:
                attempts += 1
                if attempts == MAX_ATTEMPTS:
                    raise RateLimited()
                await self._back_off(response, attempts)
                continue
            return response

    # Plumbing

    async def _valid_token(self) -> str:
        if self._token is not None and self._clock() < self._token_until - TOKEN_MARGIN:
            return self._token
        return await self._exchange()

    async def _exchange(self) -> str:
        if isinstance(self._key, Path):
            self._key = read_key_file(self._key)
        attempts = 0
        while True:
            response = await self._call("POST", TOKEN_PATH, auth=f"ApiKey {self._key.key}")
            if response.status_code != httpx.codes.TOO_MANY_REQUESTS:
                break
            attempts += 1
            if attempts == MAX_ATTEMPTS:
                raise RateLimited()
            await self._back_off(response, attempts)
        if response.status_code in (httpx.codes.UNAUTHORIZED, httpx.codes.FORBIDDEN):
            raise KeyRejected()
        if response.is_error:
            raise error_for(response.status_code)
        token = response.text.strip()
        if not token or token.startswith(("{", "[", "<")) or any(c.isspace() for c in token):
            raise GarminError(code="UNEXPECTED_TOKEN")
        expiry = token_expiry(token)
        self._token = token
        self._token_until = (
            expiry if expiry is not None else self._clock() + TOKEN_FALLBACK_LIFETIME
        )
        return token

    async def _call(
        self,
        method: str,
        path: str,
        *,
        auth: str,
        params: Mapping[str, str] | None = None,
        pause: float | None = None,
    ) -> httpx.Response:
        if self._last_call is not None:
            wait = self._pause if pause is None else max(pause, self._pause)
            delay = self._last_call + wait - self._clock()
            if delay > 0:
                await self._sleep(delay)
        try:
            return await self._http.request(
                method, path, params=params, headers={"Authorization": auth}
            )
        finally:
            self._last_call = self._clock()

    async def _back_off(self, response: httpx.Response, attempts: int) -> None:
        delay = _seconds(response.headers.get("retry-after"))
        if delay is None:
            delay = MIN_BACKOFF * 2 ** (attempts - 1)
        await self._sleep(min(delay, MAX_WAIT))


def _seconds(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        return max(float(value), 0.0)
    except ValueError:
        return None


def windows(start: date, end: date, size: int) -> list[tuple[date, date]]:
    """The days from `start` to `end`, both included, in runs of at most `size` days."""
    result: list[tuple[date, date]] = []
    while start <= end:
        last = min(start + timedelta(days=size - 1), end)
        result.append((start, last))
        start = last + timedelta(days=1)
    return result
