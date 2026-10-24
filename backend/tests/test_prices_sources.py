"""The daily price source (ADR-0008): Yahoo's search and chart, parsed into closes as traded."""

from datetime import date
from decimal import Decimal

import httpx
import pytest
from yahoo import FakeYahoo, Listed

from hubnisio.finance.prices.sources import (
    USER_AGENT,
    PriceClient,
    PriceSourceError,
    parse_chart,
    parse_search,
)

pytestmark = pytest.mark.anyio


async def test_a_chart_gives_closes_as_traded_with_the_split_undone() -> None:
    yahoo = FakeYahoo(
        charts={
            "XACM": Listed(
                "USD",
                "EQUITY",
                # Yahoo divides the days before a 4-for-1 split by 4.
                {date(2026, 6, 1): Decimal("25.123"), date(2026, 6, 2): Decimal("101.5")},
                splits=[(date(2026, 6, 2), 4, 1)],
            )
        }
    )
    async with yahoo.client() as client:
        chart = await client.chart("XACM", date(2026, 6, 1))

    assert chart is not None
    assert (chart.symbol, chart.currency, chart.type) == ("XACM", "USD", "EQUITY")
    assert chart.closes == {
        date(2026, 6, 1): Decimal("100.49"),
        date(2026, 6, 2): Decimal("101.50"),
    }
    (request,) = yahoo.requests
    assert request.headers["User-Agent"] == USER_AGENT  # Yahoo turns away a library's own
    assert (request.url.params["interval"], request.url.params["events"]) == ("1d", "split")


async def test_pence_are_gbx_and_days_without_trades_are_skipped() -> None:
    body = (
        '{"chart": {"result": [{"meta": {"currency": "GBp", "instrumentType": "ETF",'
        ' "gmtoffset": 3600, "priceHint": 4},'
        ' "timestamp": [1790841600, 1790928000, 1791014400],'
        ' "indicators": {"quote": [{"close": [8312.000122070312, null, 0]}]}}], "error": null}}'
    )
    chart = parse_chart(body, "XPNC.L")

    assert chart is not None
    assert (chart.currency, chart.type) == ("GBX", "ETF")
    assert chart.closes == {date(2026, 10, 1): Decimal("8312.0001")}


async def test_a_symbol_yahoo_doesnt_have_is_none_and_other_errors_raise() -> None:
    async with FakeYahoo().client() as client:
        assert await client.chart("NOPE", date(2026, 1, 1)) is None
        assert await client.search("XS0000000000") == []
    async with FakeYahoo(down=True).client() as client:
        with pytest.raises(PriceSourceError, match="HTTP 503"):
            await client.chart("XACM", date(2026, 1, 1))
    with pytest.raises(PriceSourceError, match="isn't JSON"):
        parse_chart("<html>", "XACM")
    with pytest.raises(PriceSourceError):
        parse_chart('{"chart": {"result": [], "error": {"code": "Bad Request"}}}', "XACM")


async def test_a_search_lists_the_symbols_for_an_isin() -> None:
    body = '{"quotes": [{"symbol": "XACM", "exchange": "NMS", "quoteType": "EQUITY"}, {"x": 1}]}'
    (listing,) = parse_search(body)
    assert (listing.symbol, listing.exchange, listing.type) == ("XACM", "NMS", "EQUITY")
    with pytest.raises(PriceSourceError):
        parse_search('{"news": []}')

    yahoo = FakeYahoo(searches={"XS0000000002": ["XACM", "XACM.DE"]})
    async with PriceClient(transport=httpx.MockTransport(yahoo)) as client:
        found = await client.search("XS0000000002")
    assert [listing.symbol for listing in found] == ["XACM", "XACM.DE"]
    assert yahoo.requests[0].url.params["q"] == "XS0000000002"
