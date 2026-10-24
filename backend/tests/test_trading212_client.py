"""The Trading 212 client against a fake API: auth, paging, rate limits, errors, key files."""

import base64
from datetime import date
from pathlib import Path
from typing import Any

import httpx
import pytest

from hubnisio.finance.providers.base import Provider
from hubnisio.finance.providers.trading212.client import (
    MAX_ATTEMPTS,
    ApiKey,
    Trading212Client,
    read_key_file,
)
from hubnisio.finance.providers.trading212.errors import (
    KeyFileError,
    KeyRejected,
    MissingPermission,
    PaginationError,
    RateLimited,
    Trading212Error,
    WrongAccount,
)

pytestmark = pytest.mark.anyio

KEY = ApiKey("key-123", "secret-456")
SUMMARY = {
    "id": 4242,
    "currency": "EUR",
    "totalValue": 1234.56,
    "cash": {"availableToTrade": 34.56, "inPies": 0, "reservedForOrders": 0},
    "investments": {"currentValue": 1200, "totalCost": 1100},
}


class FakeApi:
    """Answers requests from a queue of responses and records what was asked."""

    def __init__(self, *responses: httpx.Response) -> None:
        self.responses = list(responses)
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return self.responses.pop(0)


class Clock:
    """A clock that only moves when the client sleeps."""

    def __init__(self, now: float = 1_000_000.0) -> None:
        self.now = now
        self.slept: list[float] = []

    def __call__(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds


def ok(body: dict[str, Any], **headers: str) -> httpx.Response:
    return httpx.Response(200, json=body, headers=headers)


def page(items: list[dict[str, Any]], following: str | None) -> httpx.Response:
    return ok({"items": items, "nextPagePath": following})


def client(api: FakeApi, clock: Clock | None = None, key: ApiKey | Path = KEY) -> Trading212Client:
    clock = clock or Clock()
    return Trading212Client(key, transport=httpx.MockTransport(api), clock=clock, sleep=clock.sleep)


async def test_requests_carry_the_key_as_basic_auth() -> None:
    api = FakeApi(ok(SUMMARY))
    async with client(api) as t212:
        fetched = await t212.get_summary()

    (request,) = api.requests
    assert str(request.url) == "https://live.trading212.com/api/v0/equity/account/summary"
    expected = base64.b64encode(b"key-123:secret-456").decode()
    assert request.headers["authorization"] == f"Basic {expected}"
    assert fetched.kind == "summary"
    assert fetched.request == {"method": "GET", "path": "/api/v0/equity/account/summary"}
    assert "key-123" not in repr(KEY) and "secret-456" not in repr(KEY)
    assert fetched.data.total_value == fetched.data.cash.available_to_trade + 1200


async def test_history_follows_next_page_paths_until_null() -> None:
    path = "/api/v0/equity/history/dividends"
    api = FakeApi(
        page([{"paidOn": "2026-10-20T10:00:00Z"}], f"{path}?limit=50&cursor=1760346100000"),
        page([{"paidOn": "2026-09-20T10:00:00Z"}], None),
    )
    async with client(api) as t212:
        pages = [item async for item in t212.iter_history("dividends")]

    assert [len(fetched.data.items) for fetched in pages] == [1, 1]
    first, second = api.requests
    assert first.url.path == path
    assert dict(first.url.params) == {"limit": "50"}
    assert dict(second.url.params) == {"limit": "50", "cursor": "1760346100000"}
    assert pages[1].request["params"] == {"limit": "50", "cursor": "1760346100000"}


async def test_a_later_sync_stops_at_the_page_that_reaches_back_past_since() -> None:
    path = "/api/v0/equity/history/transactions"
    api = FakeApi(
        page([{"dateTime": "2026-10-20T10:00:00Z"}], f"{path}?cursor=a"),
        page([{"dateTime": "2026-10-05T10:00:00Z"}, {"dateTime": "2026-09-30T23:00:00Z"}], "x"),
    )
    async with client(api) as t212:
        pages = [item async for item in t212.iter_history("transactions", since=date(2026, 10, 1))]

    assert len(pages) == 2  # the second page holds 30 September, so no third is asked for
    assert len(api.requests) == 2


async def test_a_repeated_page_path_is_an_error() -> None:
    api = FakeApi(page([], "/api/v0/equity/history/transactions?cursor=a"))
    api.responses.append(page([], "/api/v0/equity/history/transactions?cursor=a"))
    with pytest.raises(PaginationError):
        async with client(api) as t212:
            async for _ in t212.iter_history("transactions"):
                pass


def position(ticker: str) -> dict[str, Any]:
    return {"instrument": {"ticker": ticker}, "quantity": 1}


def order(
    ticker: str, filled_at: str | None, created_at: str = "2026-01-01T10:00:00Z"
) -> dict[str, Any]:
    fill = {"id": 1, "filledAt": filled_at, "quantity": 1, "price": 1} if filled_at else None
    return {"order": {"createdAt": created_at, "instrument": {"ticker": ticker}}, "fill": fill}


async def test_fetch_gives_the_summary_and_positions_then_the_histories_then_instruments() -> None:
    listed = [
        {"ticker": ticker, "type": "ETF"} for ticker in ("VWRL_EQ", "AAPL_US_EQ", "TSLA_US_EQ")
    ]
    api = FakeApi(
        ok(SUMMARY),
        httpx.Response(200, json=[position("VWRL_EQ")]),
        page([], None),
        page([], None),
        page([order("AAPL_US_EQ", "2026-10-01T10:00:00Z")], None),
        httpx.Response(200, json=listed),
    )
    async with client(api) as t212:
        provider: Provider = t212
        fetched = [item async for item in provider.fetch("4242", None)]

    kinds = [item.kind for item in fetched]
    assert kinds == ["summary", "positions", "transactions", "dividends", "orders", "instruments"]
    paths = [request.url.path.removeprefix("/api/v0/equity/") for request in api.requests]
    assert paths == [
        "account/summary",
        "positions",
        "history/transactions",
        "history/dividends",
        "history/orders",
        "metadata/instruments",
    ]
    positions, instruments = fetched[1], fetched[-1]
    assert positions.raw == {"items": [position("VWRL_EQ")]}  # a bare array, wrapped
    # Only the instruments the positions and orders name are kept.
    assert instruments.raw == {"items": listed[:2]}


async def test_without_positions_or_orders_the_instrument_list_isnt_asked_for() -> None:
    api = FakeApi(ok(SUMMARY), httpx.Response(200, json=[]), *(page([], None) for _ in range(3)))
    async with client(api) as t212:
        kinds = [item.kind async for item in t212.fetch("4242", None)]

    assert kinds == ["summary", "positions", "transactions", "dividends", "orders"]
    assert api.responses == []


async def test_a_key_without_the_metadata_permission_still_syncs() -> None:
    api = FakeApi(
        ok(SUMMARY),
        httpx.Response(200, json=[position("VWRL_EQ")]),
        *(page([], None) for _ in range(3)),
        httpx.Response(403),
    )
    async with client(api) as t212:
        kinds = [item.kind async for item in t212.fetch("4242", None)]

    assert kinds[-1] == "orders"  # no instruments: their types stay unknown


async def test_orders_page_back_to_their_own_cutoff_dated_by_their_fill() -> None:
    path = "/api/v0/equity/history/orders"
    api = FakeApi(
        ok(SUMMARY),
        httpx.Response(200, json=[]),
        page([{"dateTime": "2026-10-20T10:00:00Z"}], None),
        page([], None),
        # Created long ago but filled after the cutoff, then a cancelled order created after it.
        page(
            [
                order("A_EQ", "2026-10-10T10:00:00Z", created_at="2026-08-01T10:00:00Z"),
                order("A_EQ", None, created_at="2026-10-02T10:00:00Z"),
            ],
            f"{path}?cursor=1",
        ),
        page([order("A_EQ", "2026-09-30T10:00:00Z")], f"{path}?cursor=2"),
        httpx.Response(200, json=[]),
    )
    async with client(api) as t212:
        fetched = [
            item
            async for item in t212.fetch("4242", date(2026, 10, 15), trades_since=date(2026, 10, 1))
        ]

    assert [item.kind for item in fetched].count("orders") == 2  # not a third page
    assert api.responses == []


async def test_positions_that_arent_a_list_are_unexpected() -> None:
    api = FakeApi(ok(SUMMARY), ok({"items": []}))
    with pytest.raises(Trading212Error) as caught:
        async with client(api) as t212:
            async for _ in t212.fetch("4242", None):
                pass
    assert caught.value.code == "UNEXPECTED_RESPONSE"


async def test_fetch_refuses_a_key_for_another_account() -> None:
    api = FakeApi(ok(SUMMARY))
    with pytest.raises(WrongAccount):
        async with client(api) as t212:
            async for _ in t212.fetch("9999", None):
                pass


async def test_a_used_up_allowance_waits_for_its_reset() -> None:
    clock = Clock()
    reset = str(int(clock.now) + 5)
    api = FakeApi(
        ok(SUMMARY, **{"x-ratelimit-remaining": "0", "x-ratelimit-reset": reset}),
        ok(SUMMARY, **{"x-ratelimit-remaining": "0", "x-ratelimit-reset": str(int(reset) + 5)}),
    )
    async with client(api, clock) as t212:
        await t212.get_summary()
        assert clock.slept == []
        await t212.get_summary()

    assert clock.slept == [5.0]


async def test_a_429_waits_and_retries() -> None:
    clock = Clock()
    api = FakeApi(
        httpx.Response(429, headers={"x-ratelimit-reset": str(int(clock.now) + 30)}),
        httpx.Response(429),  # no reset given: back off
        ok(SUMMARY),
    )
    async with client(api, clock) as t212:
        await t212.get_summary()

    assert clock.slept == [30.0, 2.0]
    assert len(api.requests) == 3


async def test_a_429_that_never_ends_gives_up() -> None:
    api = FakeApi(*(httpx.Response(429) for _ in range(MAX_ATTEMPTS)))
    with pytest.raises(RateLimited) as raised:
        async with client(api) as t212:
            await t212.get_summary()
    assert raised.value.code == "RATE_LIMITED"
    assert len(api.requests) == MAX_ATTEMPTS


@pytest.mark.parametrize(
    ("status", "error", "code"),
    [
        (401, KeyRejected, "KEY_REJECTED"),
        (403, MissingPermission, "MISSING_PERMISSION"),
        (408, Trading212Error, "HTTP_408"),
    ],
)
async def test_errors_by_status(status: int, error: type[Trading212Error], code: str) -> None:
    api = FakeApi(httpx.Response(status, json={"message": "Nope"}))
    with pytest.raises(error) as raised:
        async with client(api) as t212:
            await t212.get_summary()
    assert raised.value.code == code
    assert str(raised.value) == f"Trading 212 error {code}"


async def test_a_key_file_is_read_at_the_first_request(tmp_path: Path) -> None:
    path = tmp_path / "invest"
    path.write_text("# Invest\nkey = key-123\n\nsecret=secret-456\n", encoding="utf-8")
    api = FakeApi(ok(SUMMARY))
    async with client(api, key=path) as t212:
        await t212.get_summary()
    expected = base64.b64encode(b"key-123:secret-456").decode()
    assert api.requests[0].headers["authorization"] == f"Basic {expected}"


async def test_a_missing_key_file_fails_the_request(tmp_path: Path) -> None:
    with pytest.raises(KeyFileError) as raised:
        async with client(FakeApi(), key=tmp_path / "missing") as t212:
            await t212.get_summary()
    assert raised.value.code == "KEY_FILE"


@pytest.mark.parametrize(
    ("text", "complaint"),
    [
        ("key=KEYVALUE\n", "no `secret=` line"),
        ("secret=SECRETVALUE\n", "no `key=` line"),
        ("KEYVALUE\nSECRETVALUE\n", "Line 1"),
        ("key=KEYVALUE\nkey=OTHERVALUE\nsecret=SECRETVALUE\n", "more than one `key=`"),
        ("key=\nsecret=SECRETVALUE\n", "no `key=` line"),
    ],
)
def test_malformed_key_files_say_why_without_values(
    tmp_path: Path, text: str, complaint: str
) -> None:
    path = tmp_path / "invest"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(KeyFileError) as raised:
        read_key_file(path)
    assert complaint in raised.value.message
    for value in ("KEYVALUE", "OTHERVALUE", "SECRETVALUE"):
        assert value not in raised.value.message
