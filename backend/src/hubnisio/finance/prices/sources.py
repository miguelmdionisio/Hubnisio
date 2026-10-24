"""Where daily instrument prices come from (ADR-0008, "As built in T3"): Yahoo Finance's chart
endpoint, keyless but unofficial. No official or free-with-a-key source covered every
instrument held, with the history needed.

- `search` lists the symbols Yahoo has for an ISIN.
- `chart` gives a symbol's daily closes from a day on, with its currency and type.

A close is as traded on its day, like a fill's price: Yahoo divides the days before a split by
its ratio, so they're multiplied back.
"""

import json
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time
from decimal import Decimal, InvalidOperation
from types import TracebackType
from typing import Any, Self
from urllib.parse import quote

import httpx

SEARCH_URL = "https://query2.finance.yahoo.com/v1/finance/search"
CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
# Yahoo answers an HTTP library's default User-Agent with 429.
USER_AGENT = "Hubnisio/1.0 (personal finance hub)"
# Yahoo writes pence as GBp; the hub, like Trading 212, as GBX.
_CURRENCIES = {"GBp": "GBX"}


class PriceSourceError(Exception):
    """The source couldn't be reached or answered with something unusable."""


@dataclass(frozen=True, slots=True)
class Listing:
    symbol: str
    exchange: str | None = None
    type: str | None = None  # Yahoo's: EQUITY, ETF, …


@dataclass(frozen=True, slots=True)
class Chart:
    symbol: str
    currency: str | None  # GBX for pence
    type: str | None  # Yahoo's: EQUITY, ETF, …
    closes: dict[date, Decimal] = field(default_factory=dict[date, Decimal])  # as traded


def _json(body: str, where: str) -> Any:
    try:
        return json.loads(body, parse_float=Decimal)
    except ValueError as exc:
        raise PriceSourceError(f"{where}: the response isn't JSON") from exc


def parse_search(body: str) -> list[Listing]:
    payload = _json(body, "Yahoo search")
    quotes = payload.get("quotes") if isinstance(payload, dict) else None
    if not isinstance(quotes, list):
        raise PriceSourceError("Yahoo search: no quotes in the response")
    return [
        Listing(item["symbol"], item.get("exchange"), item.get("quoteType"))
        for item in quotes
        if isinstance(item, dict) and isinstance(item.get("symbol"), str)
    ]


def _decimal(value: object) -> Decimal | None:
    if isinstance(value, bool) or not isinstance(value, int | Decimal):
        return None
    try:
        number = Decimal(value)
    except InvalidOperation:
        return None
    return number if number.is_finite() and number > 0 else None


def parse_chart(body: str, symbol: str) -> Chart | None:
    """The chart's daily closes, as traded. None when Yahoo has no such symbol."""
    payload = _json(body, f"Yahoo chart {symbol}")
    chart = payload.get("chart") if isinstance(payload, dict) else None
    if not isinstance(chart, dict):
        raise PriceSourceError(f"Yahoo chart {symbol}: not a chart")
    results = chart.get("result")
    if not results:
        error = chart.get("error")
        if isinstance(error, dict) and error.get("code") == "Not Found":
            return None
        raise PriceSourceError(f"Yahoo chart {symbol}: {error!r}")
    result = results[0]
    meta = result.get("meta") or {}
    # Bars are stamped at the market's opening, so its UTC offset gives the trading day.
    offset = int(meta.get("gmtoffset") or 0)
    hint = meta.get("priceHint")
    step = Decimal(1).scaleb(-min(max(hint, 2), 6) if isinstance(hint, int) else -4)

    def day(timestamp: int) -> date:
        return datetime.fromtimestamp(timestamp + offset, UTC).date()

    splits: list[tuple[date, Decimal]] = []
    for split in ((result.get("events") or {}).get("splits") or {}).values():
        numerator, denominator = (
            _decimal(split.get("numerator")),
            _decimal(split.get("denominator")),
        )
        if isinstance(split.get("date"), int) and numerator and denominator:
            splits.append((day(split["date"]), numerator / denominator))
    quotes = ((result.get("indicators") or {}).get("quote") or [{}])[0]
    closes: dict[date, Decimal] = {}
    for timestamp, value in zip(
        result.get("timestamp") or [], quotes.get("close") or [], strict=False
    ):
        close = _decimal(value)
        if close is None or not isinstance(timestamp, int):
            continue  # a day without trades
        on = day(timestamp)
        for split_day, ratio in splits:
            if split_day > on:
                close *= ratio
        closes[on] = close.quantize(step)
    currency = meta.get("currency")
    return Chart(
        symbol=symbol,
        currency=_CURRENCIES.get(currency, currency) if isinstance(currency, str) else None,
        type=meta.get("instrumentType"),
        closes=closes,
    )


class PriceClient:
    def __init__(
        self,
        *,
        http: httpx.AsyncClient | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._owns_http = http is None
        self._http = http or httpx.AsyncClient(
            timeout=30, transport=transport, headers={"User-Agent": USER_AGENT}
        )

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

    async def _get(self, url: str, params: dict[str, str]) -> httpx.Response:
        """The response, unless the request failed or the server answered with an error. A 404
        is returned for the caller to read: a chart says "no such symbol" with it."""
        try:
            response = await self._http.get(url, params=params)
        except httpx.HTTPError as exc:
            raise PriceSourceError(f"Yahoo: {type(exc).__name__}") from exc
        if response.is_error and response.status_code != 404:
            raise PriceSourceError(f"Yahoo: HTTP {response.status_code}")
        return response

    async def search(self, isin: str) -> list[Listing]:
        """The symbols Yahoo lists for an ISIN, its best match first."""
        response = await self._get(SEARCH_URL, {"q": isin, "quotesCount": "10", "newsCount": "0"})
        return [] if response.status_code == 404 else parse_search(response.text)

    async def chart(self, symbol: str, since: date) -> Chart | None:
        """Daily closes from `since` to today, and the splits since, to undo Yahoo's adjustment
        for them. None when Yahoo has no such symbol."""
        start = int(datetime.combine(since, time(), UTC).timestamp())
        response = await self._get(
            CHART_URL.format(symbol=quote(symbol, safe="")),
            {
                "period1": str(start),
                "period2": str(int(datetime.now(UTC).timestamp())),
                "interval": "1d",
                "events": "split",
            },
        )
        return parse_chart(response.text, symbol)
