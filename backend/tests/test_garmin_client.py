"""The Garmin client against a fake API: the key file, the token exchange (plain text), the
Bearer token and its reuse, a 401 retried once, 429 back-off, and windows."""

from datetime import date
from pathlib import Path

import httpx
import pytest
from garmin_data import KEY, TOKEN_PATH, FakeGarmin, jwt

from hubnisio.health.providers.garmin.client import (
    ENDPOINTS,
    MAX_ATTEMPTS,
    MIN_BACKOFF,
    PAUSE,
    TOKEN_MARGIN,
    USER_AGENT,
    ApiKey,
    GarminClient,
    read_key_file,
    token_expiry,
    windows,
)
from hubnisio.health.providers.garmin.errors import (
    GarminError,
    KeyFileError,
    KeyRejected,
    RateLimited,
)

pytestmark = pytest.mark.anyio

DAY = date(2026, 3, 4)


class Clock:
    """A clock that only moves when the client sleeps, or when a test moves it."""

    def __init__(self, now: float = 1_800_000_000.0) -> None:
        self.now = now
        self.slept: list[float] = []

    def __call__(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds


TEST_KEY = ApiKey(KEY)


def client_for(api: FakeGarmin, clock: Clock, key: ApiKey | Path = TEST_KEY) -> GarminClient:
    return GarminClient(key, transport=httpx.MockTransport(api), clock=clock, sleep=clock.sleep)


async def test_exchanges_the_key_for_a_plain_text_token_and_sends_it_as_bearer() -> None:
    clock = Clock()
    api = FakeGarmin(now=clock)
    async with client_for(api, clock) as client:
        fetched = await client.fetch("steps", DAY, DAY)

    exchange, call = api.requests
    assert exchange.method == "POST"
    assert exchange.url.path == TOKEN_PATH
    assert exchange.headers["authorization"] == f"ApiKey {KEY}"
    assert exchange.headers["user-agent"] == USER_AGENT
    assert call.method == "GET"
    assert call.headers["authorization"] == f"Bearer {api.tokens[0]}"
    assert call.url.path == "/usersummary-service/stats/steps/daily/2026-03-04/2026-03-04"
    assert fetched.kind == "steps"
    assert (fetched.day_from, fetched.day_to) == (DAY, DAY)
    assert fetched.request == {"method": "GET", "path": call.url.path}
    assert fetched.raw[0]["calendarDate"] == "2026-03-04"


async def test_query_parameters_are_recorded_with_the_request() -> None:
    clock = Clock()
    api = FakeGarmin(now=clock)
    async with client_for(api, clock) as client:
        fetched = await client.fetch("sleep", DAY, date(2026, 3, 5))

    assert fetched.request["params"] == {"startDate": "2026-03-04", "endDate": "2026-03-05"}
    assert [item["calendarDate"] for item in fetched.raw] == ["2026-03-04", "2026-03-05"]


async def test_the_token_is_reused_until_near_its_expiry() -> None:
    clock = Clock()
    api = FakeGarmin(now=clock)
    async with client_for(api, clock) as client:
        await client.fetch("steps", DAY)
        await client.fetch("stress", DAY)
        assert len(api.tokens) == 1
        clock.now += 86_400 - TOKEN_MARGIN + 1  # within the margin of the token's exp
        await client.fetch("steps", DAY)

    assert len(api.tokens) == 2
    assert api.requests[-1].headers["authorization"] == f"Bearer {api.tokens[1]}"


async def test_a_401_exchanges_the_key_again_and_retries_once() -> None:
    clock = Clock()
    api = FakeGarmin(now=clock)
    async with client_for(api, clock) as client:
        await client.fetch("steps", DAY)
        api.queued = [httpx.Response(401)]  # the token was revoked early
        fetched = await client.fetch("steps", DAY)

    assert fetched.raw[0]["totalSteps"] == 9999
    assert [r.url.path for r in api.requests].count(TOKEN_PATH) == 2


async def test_a_second_401_rejects_the_key() -> None:
    clock = Clock()
    api = FakeGarmin(now=clock)
    async with client_for(api, clock) as client:
        await client.fetch("steps", DAY)
        api.queued = [httpx.Response(401), httpx.Response(200, text=jwt(clock() + 86_400))]
        api.queued.append(httpx.Response(401))
        with pytest.raises(KeyRejected):
            await client.fetch("steps", DAY)


@pytest.mark.parametrize("status", [401, 403])
async def test_a_refused_exchange_rejects_the_key(status: int) -> None:
    clock = Clock()
    api = FakeGarmin(now=clock, queued=[httpx.Response(status)])
    async with client_for(api, clock) as client:
        with pytest.raises(KeyRejected):
            await client.fetch("steps", DAY)


async def test_an_exchange_reply_that_is_not_a_token_fails() -> None:
    clock = Clock()
    api = FakeGarmin(now=clock, queued=[httpx.Response(200, json={"token": "x"})])
    async with client_for(api, clock) as client:
        with pytest.raises(GarminError) as error:
            await client.fetch("steps", DAY)
    assert error.value.code == "UNEXPECTED_TOKEN"


async def test_a_token_without_a_readable_exp_is_kept_for_a_while() -> None:
    clock = Clock()
    api = FakeGarmin(
        now=clock,
        queued=[httpx.Response(200, text="opaque-token"), httpx.Response(200, json=[])],
    )
    async with client_for(api, clock) as client:
        assert (await client.fetch("steps", DAY)).raw == []
        api.queued = [httpx.Response(200, json=[])]
        await client.fetch("steps", DAY)

    assert [r.url.path for r in api.requests].count(TOKEN_PATH) == 1
    assert api.requests[-1].headers["authorization"] == "Bearer opaque-token"


async def test_429_backs_off_with_retry_after_then_doubling() -> None:
    clock = Clock()
    api = FakeGarmin(now=clock)
    async with client_for(api, clock) as client:
        await client.fetch("steps", DAY)
        clock.slept.clear()
        api.queued = [
            httpx.Response(429, headers={"retry-after": "7"}),
            httpx.Response(429),
        ]
        fetched = await client.fetch("steps", DAY)

    assert fetched.raw[0]["totalSteps"] == 9999
    backoffs = [seconds for seconds in clock.slept if seconds > PAUSE]
    assert backoffs == [7.0, MIN_BACKOFF * 2]


async def test_429_gives_up_after_a_few_tries() -> None:
    clock = Clock()
    api = FakeGarmin(now=clock)
    async with client_for(api, clock) as client:
        await client.fetch("steps", DAY)
        api.queued = [httpx.Response(429) for _ in range(MAX_ATTEMPTS)]
        with pytest.raises(RateLimited):
            await client.fetch("steps", DAY)


async def test_calls_are_spaced_by_a_pause() -> None:
    clock = Clock()
    api = FakeGarmin(now=clock)
    async with client_for(api, clock) as client:
        await client.fetch("steps", DAY)
        await client.fetch("stress", DAY)

    assert clock.slept == [PAUSE, PAUSE]  # before the first GET, and before the second


async def test_errors_carry_their_status_and_an_empty_body_is_none() -> None:
    clock = Clock()
    api = FakeGarmin(now=clock, fail={"weight": 400})
    async with client_for(api, clock) as client:
        with pytest.raises(GarminError) as error:
            await client.fetch("weight", DAY, DAY)
        assert error.value.code == "HTTP_400"
        assert "invented" not in str(error.value)
        api.queued = [httpx.Response(204)]
        assert (await client.fetch("spo2", DAY)).raw is None


async def test_a_window_longer_than_the_endpoint_allows_is_refused() -> None:
    clock = Clock()
    async with client_for(FakeGarmin(now=clock), clock) as client:
        with pytest.raises(ValueError, match="at most 28"):
            await client.fetch("stress", DAY, date(2026, 4, 30))


def test_windows_split_a_period() -> None:
    assert windows(date(2026, 1, 1), date(2026, 1, 5), 2) == [
        (date(2026, 1, 1), date(2026, 1, 2)),
        (date(2026, 1, 3), date(2026, 1, 4)),
        (date(2026, 1, 5), date(2026, 1, 5)),
    ]
    assert windows(date(2026, 1, 2), date(2026, 1, 1), 5) == []


def test_every_ranged_endpoint_stays_under_a_year() -> None:
    assert all(e.window is None or e.window <= 364 for e in ENDPOINTS.values())
    assert ENDPOINTS["weight"].window is not None and ENDPOINTS["weight"].window <= 364


def test_token_expiry_reads_the_exp_claim() -> None:
    assert token_expiry(jwt(1_900_000_000)) == 1_900_000_000
    assert token_expiry("not-a-jwt") is None
    assert token_expiry("a.!!!.c") is None


def test_read_key_file(tmp_path: Path) -> None:
    path = tmp_path / "garmin"
    path.write_text("# my key\n\nkey = abc-123 \n", encoding="utf-8")
    assert read_key_file(path).key == "abc-123"
    assert "abc" not in repr(read_key_file(path))

    for text, message in [
        ("secret=x\n", "isn't `key=…`"),
        ("key=a\nkey=b\n", "more than one"),
        ("# nothing\n", "no `key=` line"),
    ]:
        path.write_text(text, encoding="utf-8")
        with pytest.raises(KeyFileError) as error:
            read_key_file(path)
        assert message in error.value.message
    with pytest.raises(KeyFileError):
        read_key_file(tmp_path / "missing")
