import json
from collections.abc import Callable
from datetime import date
from decimal import Decimal

import httpx
import pytest

from hubnisio.finance.fx.sources import (
    FxClient,
    FxSourceError,
    parse_currency_api,
    parse_ecb_csv,
)

pytestmark = pytest.mark.anyio

# The shape of the ECB Data Portal's `csvdata` format, with the columns the hub ignores cut.
ECB_HEADER = "KEY,FREQ,CURRENCY,CURRENCY_DENOM,EXR_TYPE,EXR_SUFFIX,TIME_PERIOD,OBS_VALUE,OBS_STATUS"
ECB_CSV = f"""{ECB_HEADER}
EXR.D.USD.EUR.SP00.A,D,USD,EUR,SP00,A,2026-10-15,1.1208,A
EXR.D.USD.EUR.SP00.A,D,USD,EUR,SP00,A,2026-10-16,1.1253,A
EXR.D.USD.EUR.SP00.A,D,USD,EUR,SP00,A,2026-10-17,,M
EXR.D.USD.EUR.SP00.A,D,USD,EUR,SP00,A,2026-10-19,1.1225,A
"""


ECB_ROW = "EXR.D.MAD.EUR.SP00.A,D,MAD,EUR,SP00,A,2020-10-30,10.7485,A\n"


def currency_api_file(day: date, **rates: object) -> dict[str, object]:
    return {"date": day.isoformat(), "eur": {"aed": 4.126445, "usd": 1.1205, **rates}}


class Web:
    """Answers each request with `handler`'s response and keeps the requests."""

    def __init__(self, handler: Callable[[httpx.Request], httpx.Response]) -> None:
        self.handler = handler
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return self.handler(request)

    def client(self) -> FxClient:
        return FxClient(transport=httpx.MockTransport(self))


def test_parse_ecb_csv_reads_each_day_and_skips_days_without_a_rate() -> None:
    assert parse_ecb_csv(ECB_CSV) == {
        date(2026, 10, 15): Decimal("1.1208"),
        date(2026, 10, 16): Decimal("1.1253"),
        date(2026, 10, 19): Decimal("1.1225"),
    }
    assert parse_ecb_csv("") == {}
    assert parse_ecb_csv(ECB_HEADER + "\n") == {}


@pytest.mark.parametrize(
    "body",
    [
        "<html><body>Bad Request</body></html>",
        f"{ECB_HEADER}\nEXR.D.USD.EUR.SP00.A,D,USD,EUR,SP00,A,2026-10-15,0,A\n",
        f"{ECB_HEADER}\nEXR.D.USD.EUR.SP00.A,D,USD,EUR,SP00,A,2026-10-15,NaN,A\n",
        f"{ECB_HEADER}\nEXR.D.USD.EUR.SP00.A,D,USD,EUR,SP00,A,15 Oct,1.12,A\n",
    ],
)
def test_parse_ecb_csv_refuses_what_it_cannot_trust(body: str) -> None:
    with pytest.raises(FxSourceError):
        parse_ecb_csv(body)


def test_parse_currency_api_reads_the_rate_exactly() -> None:
    day = date(2026, 10, 20)
    body = '{"date": "2026-10-20", "eur": {"mad": 11.01207566, "usd": 1}}'

    assert parse_currency_api(body, "MAD", day) == Decimal("11.01207566")
    assert parse_currency_api(body, "USD", day) == Decimal("1")
    assert parse_currency_api(body, "SEK", day) is None


@pytest.mark.parametrize(
    "body",
    [
        "not json",
        "[]",
        '{"date": "2026-10-19", "eur": {"mad": 11.0}}',  # another day's file
        '{"date": "2026-10-20"}',
        '{"date": "2026-10-20", "eur": {"mad": 0}}',
        '{"date": "2026-10-20", "eur": {"mad": "lots"}}',
    ],
)
def test_parse_currency_api_refuses_what_it_cannot_trust(body: str) -> None:
    with pytest.raises(FxSourceError):
        parse_currency_api(body, "MAD", date(2026, 10, 20))


async def test_ecb_rates_asks_for_the_series_from_the_day() -> None:
    web = Web(lambda _request: httpx.Response(200, text=ECB_CSV))

    async with web.client() as client:
        rates = await client.ecb_rates("USD", date(2026, 10, 15))

    assert list(rates) == [date(2026, 10, 15), date(2026, 10, 16), date(2026, 10, 19)]
    (request,) = web.requests
    assert request.url.host == "data-api.ecb.europa.eu"
    assert request.url.path == "/service/data/EXR/D.USD.EUR.SP00.A"
    assert dict(request.url.params) == {"startPeriod": "2026-10-15", "format": "csvdata"}


async def test_ecb_has_nothing_when_the_series_is_missing_or_the_period_empty() -> None:
    problem = httpx.Response(404, json={"title": "Not Found"})
    async with Web(lambda _request: problem).client() as client:
        assert await client.ecb_rates("ZZZ", date(2026, 10, 15)) == {}
        assert await client.ecb_latest("ZZZ") is None
    async with Web(lambda _request: httpx.Response(200, text="")).client() as client:
        assert await client.ecb_rates("USD", date(2026, 10, 31)) == {}


async def test_ecb_latest_asks_for_the_last_observation() -> None:
    web = Web(lambda _request: httpx.Response(200, text=ECB_CSV.splitlines()[0] + "\n" + ECB_ROW))

    async with web.client() as client:
        assert await client.ecb_latest("MAD") == date(2020, 10, 30)

    assert dict(web.requests[0].url.params) == {"lastNObservations": "1", "format": "csvdata"}


async def test_ecb_failures_are_reported_not_mistaken_for_no_data() -> None:
    async with Web(lambda _request: httpx.Response(503)).client() as client:
        with pytest.raises(FxSourceError, match="HTTP 503"):
            await client.ecb_rates("USD", date(2026, 10, 15))

    def unreachable(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route", request=request)

    async with Web(unreachable).client() as client:
        with pytest.raises(FxSourceError, match="ConnectError"):
            await client.ecb_latest("USD")


async def test_currency_api_reads_the_days_file_from_the_cdn() -> None:
    day = date(2026, 10, 20)
    web = Web(lambda _request: httpx.Response(200, json=currency_api_file(day, mad=11.01207566)))

    async with web.client() as client:
        assert await client.currency_api_rate("MAD", day) == Decimal("11.01207566")

    (request,) = web.requests
    assert str(request.url) == (
        "https://cdn.jsdelivr.net/npm/@fawazahmed0/currency-api@2026-10-20/v1/currencies/eur.json"
    )


@pytest.mark.parametrize(
    "cdn", [httpx.Response(404), httpx.Response(503), httpx.Response(200, text="<")]
)
async def test_currency_api_falls_back_to_pages_dev(cdn: httpx.Response) -> None:
    day = date(2026, 10, 20)

    def answer(request: httpx.Request) -> httpx.Response:
        if request.url.host == "cdn.jsdelivr.net":
            return cdn
        return httpx.Response(200, json=currency_api_file(day, mad=11.5))

    web = Web(answer)
    async with web.client() as client:
        assert await client.currency_api_rate("MAD", day) == Decimal("11.5")

    assert [request.url.host for request in web.requests] == [
        "cdn.jsdelivr.net",
        "2026-10-20.currency-api.pages.dev",
    ]


async def test_currency_api_has_no_rate_when_there_is_no_file_or_no_currency() -> None:
    day = date(2026, 10, 20)
    async with Web(lambda _request: httpx.Response(404)).client() as client:
        assert await client.currency_api_rate("MAD", day) is None

    async with Web(lambda _request: httpx.Response(200, json=currency_api_file(day))).client() as c:
        assert await c.currency_api_rate("MAD", day) is None


async def test_currency_api_reports_failure_unless_both_hosts_say_there_is_no_file() -> None:
    day = date(2026, 10, 20)

    def half_down(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404 if request.url.host == "cdn.jsdelivr.net" else 503)

    for answer in (lambda _request: httpx.Response(503), half_down):
        async with Web(answer).client() as client:
            with pytest.raises(FxSourceError):
                await client.currency_api_rate("MAD", day)


async def test_currency_codes_are_checked_before_they_reach_a_url() -> None:
    web = Web(lambda _request: httpx.Response(200, text=json.dumps({})))

    async with web.client() as client:
        with pytest.raises(ValueError, match="currency code"):
            await client.ecb_rates("../x", date(2026, 10, 15))
        with pytest.raises(ValueError, match="currency code"):
            await client.currency_api_rate("mad", date(2026, 10, 15))

    assert web.requests == []
