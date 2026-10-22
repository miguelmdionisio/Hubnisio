"""Where daily euro exchange rates come from (ADR-0007, "FX rates").

- **ECB reference rates** (ECB Data Portal API, no key): the default for every currency it
  publishes.
- **fawazahmed0's currency-api** (keyless, CC0, one dated file per day since 2024-03-02): only
  for currencies the ECB doesn't publish any more. The ECB has a Moroccan dirham series, but it
  stopped on 2020-10-30, so a series being present doesn't mean the ECB covers the currency.

A rate is how many units of the currency one euro buys.
"""

import csv
import io
import json
import re
from datetime import date
from decimal import Decimal, InvalidOperation
from types import TracebackType
from typing import Any, Self
from urllib.parse import urlsplit

import httpx

ECB_URL = "https://data-api.ecb.europa.eu/service/data/EXR/D.{currency}.EUR.SP00.A"
# The CDN first; pages.dev is the project's own fallback host.
CURRENCY_API_URLS = (
    "https://cdn.jsdelivr.net/npm/@fawazahmed0/currency-api@{date}/v1/currencies/eur.json",
    "https://{date}.currency-api.pages.dev/v1/currencies/eur.json",
)
# The first day currency-api has a file for.
CURRENCY_API_FIRST_DATE = date(2024, 3, 2)

_CURRENCY_CODE = re.compile(r"[A-Z]{3}")


class FxSourceError(Exception):
    """A source couldn't be reached or answered with something unusable."""


def is_currency_code(value: str) -> bool:
    return _CURRENCY_CODE.fullmatch(value) is not None


def _rate(value: object, where: str) -> Decimal:
    try:
        rate = value if isinstance(value, Decimal) else Decimal(str(value))
    except InvalidOperation as exc:
        raise FxSourceError(f"{where}: {value!r} is not a number") from exc
    if not rate.is_finite() or rate <= 0:
        raise FxSourceError(f"{where}: {rate} is not a usable rate")
    return rate


def parse_ecb_csv(body: str) -> dict[date, Decimal]:
    """The ECB's `csvdata` format: one row per day, the rate in `OBS_VALUE`. Days without a
    value are left out."""
    if not body.strip():
        return {}
    reader = csv.DictReader(io.StringIO(body))
    if not {"TIME_PERIOD", "OBS_VALUE"} <= set(reader.fieldnames or ()):
        raise FxSourceError("ECB: the response isn't the expected CSV")
    rates: dict[date, Decimal] = {}
    for row in reader:
        period, value = row["TIME_PERIOD"], row["OBS_VALUE"]
        if not period or not value:
            continue
        try:
            day = date.fromisoformat(period)
        except ValueError as exc:
            raise FxSourceError(f"ECB: {period!r} is not a date") from exc
        rates[day] = _rate(value, f"ECB {period}")
    return rates


def parse_currency_api(body: str, currency: str, on: date) -> Decimal | None:
    """A day's file maps every currency to its rate against the euro. None when the file
    doesn't list the currency. A file dated differently from the one asked for is unusable."""
    try:
        payload: Any = json.loads(body, parse_float=Decimal)
    except ValueError as exc:
        raise FxSourceError("currency-api: the response isn't JSON") from exc
    if not isinstance(payload, dict) or payload.get("date") != on.isoformat():
        raise FxSourceError(f"currency-api: the file isn't for {on}")
    rates = payload.get("eur")
    if not isinstance(rates, dict):
        raise FxSourceError("currency-api: the file has no euro rates")
    value = rates.get(currency.lower())
    if value is None:
        return None
    return _rate(value, f"currency-api {on}")


def _code(currency: str) -> str:
    if not is_currency_code(currency):
        raise ValueError(f"Not a currency code: {currency!r}")
    return currency


class FxClient:
    def __init__(
        self,
        *,
        http: httpx.AsyncClient | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._owns_http = http is None
        self._http = http or httpx.AsyncClient(timeout=30, transport=transport)

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

    async def _get(self, url: str, params: dict[str, str] | None = None) -> httpx.Response:
        """The response, unless the request failed or the server answered with an error. A 404
        is returned for the caller to read: both sources use it for "nothing there"."""
        host = urlsplit(url).hostname
        try:
            response = await self._http.get(url, params=params)
        except httpx.HTTPError as exc:
            raise FxSourceError(f"{host}: {type(exc).__name__}") from exc
        if response.is_error and response.status_code != 404:
            raise FxSourceError(f"{host}: HTTP {response.status_code}")
        return response

    async def _ecb(self, currency: str, params: dict[str, str]) -> dict[date, Decimal]:
        url = ECB_URL.format(currency=_code(currency))
        response = await self._get(url, {**params, "format": "csvdata"})
        # 404: the ECB has no series for this currency. 200 with no body: no rate in the period.
        return {} if response.status_code == 404 else parse_ecb_csv(response.text)

    async def ecb_rates(self, currency: str, since: date) -> dict[date, Decimal]:
        """Every rate the ECB published from `since` on, by day. Empty if there are none."""
        return await self._ecb(currency, {"startPeriod": since.isoformat()})

    async def ecb_latest(self, currency: str) -> date | None:
        """The day of the ECB's newest rate for the currency; None if it has no series."""
        rates = await self._ecb(currency, {"lastNObservations": "1"})
        return max(rates, default=None)

    async def currency_api_rate(self, currency: str, on: date) -> Decimal | None:
        """The rate in currency-api's file for the day, trying the CDN and then pages.dev.
        None if neither has a file for the day or the file lacks the currency."""
        _code(currency)
        failure: FxSourceError | None = None
        for template in CURRENCY_API_URLS:
            try:
                response = await self._get(template.format(date=on.isoformat()))
                if response.status_code == 404:
                    continue
                return parse_currency_api(response.text, currency, on)
            except FxSourceError as exc:
                failure = exc
        if failure is not None:
            raise failure
        return None
