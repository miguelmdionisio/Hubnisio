"""Yahoo Finance as the price source sees it (ADR-0008): ISIN searches and daily charts, from
synthetic data, recording every request."""

from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time
from decimal import Decimal
from typing import Any
from urllib.parse import unquote

import httpx

from hubnisio.finance.prices.sources import PriceClient


@dataclass
class Listed:
    currency: str  # as Yahoo writes it: GBp for pence
    kind: str  # Yahoo's: EQUITY, ETF
    closes: dict[date, Decimal]  # adjusted for later splits, as Yahoo sends them
    splits: list[tuple[date, int, int]] = field(default_factory=list[tuple[date, int, int]])


@dataclass
class FakeYahoo:
    charts: dict[str, Listed] = field(default_factory=dict[str, Listed])
    searches: dict[str, list[str]] = field(default_factory=dict[str, list[str]])  # ISIN → symbols
    down: bool = False
    requests: list[httpx.Request] = field(default_factory=list[httpx.Request])

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.down:
            return httpx.Response(503)
        if request.url.path == "/v1/finance/search":
            symbols = self.searches.get(request.url.params["q"], [])
            quotes = [{"symbol": s, "exchange": "TST", "quoteType": "EQUITY"} for s in symbols]
            return httpx.Response(200, json={"quotes": quotes, "news": []})
        symbol = unquote(request.url.path.rsplit("/", 1)[1])
        listed = self.charts.get(symbol)
        if listed is None:
            error = {"code": "Not Found", "description": "No data found, symbol may be delisted"}
            return httpx.Response(404, json={"chart": {"result": None, "error": error}})
        since = int(request.url.params["period1"])
        days = [day for day in sorted(listed.closes) if _stamp(day) >= since]
        result: dict[str, Any] = {
            "meta": {
                "currency": listed.currency,
                "symbol": symbol,
                "instrumentType": listed.kind,
                "gmtoffset": -14400,
                "priceHint": 2,
            },
            "timestamp": [_stamp(day) for day in days],
            "indicators": {"quote": [{"close": [float(listed.closes[day]) for day in days]}]},
        }
        if listed.splits:
            result["events"] = {
                "splits": {
                    str(_stamp(day)): {
                        "date": _stamp(day),
                        "numerator": float(numerator),
                        "denominator": float(denominator),
                    }
                    for day, numerator, denominator in listed.splits
                }
            }
        return httpx.Response(200, json={"chart": {"result": [result], "error": None}})

    def client(self) -> PriceClient:
        return PriceClient(transport=httpx.MockTransport(self))

    def charted(self) -> list[tuple[str, date]]:
        """The symbols asked for, with the first day asked."""
        return [
            (
                unquote(request.url.path.rsplit("/", 1)[1]),
                datetime.fromtimestamp(int(request.url.params["period1"]), UTC).date(),
            )
            for request in self.requests
            if "/chart/" in request.url.path
        ]


def _stamp(day: date) -> int:
    """A bar's timestamp: the market's opening, 9:30 in New York."""
    return int(datetime.combine(day, time(14, 30), UTC).timestamp())
