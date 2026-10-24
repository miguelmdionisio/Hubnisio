"""Instruments' prices loaded once for many days, e.g. a portfolio's value on every day of a chart
(ADR-0008, "Value over time").

A day uses the latest price on or before it, if at most MAX_PRICE_AGE_DAYS old. Without one
the holding can't be valued that day: callers leave it out and count it, as with exchange
rates. There's never a fallback to cost.
"""

import uuid
from bisect import bisect_right
from collections.abc import Collection
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from hubnisio.finance.fx.convert import RateTable
from hubnisio.finance.models import Instrument, InstrumentPrice

MAX_PRICE_AGE_DAYS = 10


@dataclass(frozen=True, slots=True)
class InstrumentInfo:
    ticker: str
    name: str | None
    currency: str | None  # its prices'; GBX is pence. None: unknown, so it can't be valued

    @property
    def label(self) -> str:
        return self.name or self.ticker


class PriceTable:
    def __init__(
        self,
        instruments: dict[uuid.UUID, InstrumentInfo],
        prices: dict[uuid.UUID, list[tuple[date, Decimal]]],
    ) -> None:
        self.instruments = instruments
        self._prices = prices  # per instrument, oldest first

    @classmethod
    async def load(
        cls, session: AsyncSession, instrument_ids: Collection[uuid.UUID], first: date, last: date
    ) -> PriceTable:
        if not instrument_ids:
            return cls({}, {})
        ids = list(instrument_ids)
        instruments = {
            instrument.id: InstrumentInfo(instrument.ticker, instrument.name, instrument.currency)
            for instrument in await session.scalars(
                select(Instrument).where(Instrument.id.in_(ids))
            )
        }
        prices: dict[uuid.UUID, list[tuple[date, Decimal]]] = {id_: [] for id_ in instruments}
        rows = await session.execute(
            select(InstrumentPrice.instrument_id, InstrumentPrice.on, InstrumentPrice.price)
            .where(
                InstrumentPrice.instrument_id.in_(ids),
                InstrumentPrice.on >= first - timedelta(days=MAX_PRICE_AGE_DAYS),
                InstrumentPrice.on <= last,
            )
            .order_by(InstrumentPrice.on)
        )
        for instrument_id, on, price in rows:
            prices[instrument_id].append((on, price))
        return cls(instruments, prices)

    @property
    def currencies(self) -> set[str]:
        return {info.currency for info in self.instruments.values() if info.currency}

    def price(self, instrument_id: uuid.UUID, on: date) -> Decimal | None:
        prices = self._prices.get(instrument_id, [])
        index = bisect_right(prices, on, key=lambda item: item[0]) - 1
        if index < 0 or (on - prices[index][0]).days > MAX_PRICE_AGE_DAYS:
            return None
        return prices[index][1]

    def value_eur(
        self, instrument_id: uuid.UUID, quantity: Decimal, on: date, rates: RateTable
    ) -> Decimal | None:
        """The holding's value in euros on the day, not rounded; None without a price or an
        exchange rate."""
        info = self.instruments.get(instrument_id)
        price = self.price(instrument_id, on)
        if info is None or info.currency is None or price is None:
            return None
        return rates.to_eur(quantity * price, info.currency, on)
