"""Converting amounts into euros (ADR-0007, "FX rates").

An amount is converted at the rate for its day: the latest rate published on or before that
day, if it is at most MAX_RATE_AGE_DAYS old. Without one the result is NULL (None), never the
amount unconverted, so callers can leave it out and say so.
"""

from bisect import bisect_right
from collections.abc import Iterable
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy import (
    ColumnElement,
    Date,
    ScalarSelect,
    SQLColumnExpression,
    case,
    literal,
    select,
)
from sqlalchemy.ext.asyncio import AsyncSession

from hubnisio.finance.models import FxRate

BASE_CURRENCY = "EUR"
# Banks and the ECB skip weekends and holidays; currency-api history is sampled weekly.
MAX_RATE_AGE_DAYS = 10
_MONEY_STEP = Decimal("0.0001")


def rate_on(
    currency: SQLColumnExpression[str], on: SQLColumnExpression[date]
) -> ScalarSelect[Decimal]:
    """A correlated subquery: the currency's latest rate on or before `on`, within the
    allowed age; NULL if there is none."""
    return (
        select(FxRate.rate)
        .where(
            FxRate.quote_currency == currency,
            FxRate.on <= on,
            FxRate.on >= on - MAX_RATE_AGE_DAYS,
        )
        .order_by(FxRate.on.desc())
        .limit(1)
        .scalar_subquery()
    )


def eur_amount(
    amount: SQLColumnExpression[Any],
    currency: SQLColumnExpression[str],
    on: SQLColumnExpression[date],
) -> ColumnElement[Decimal]:
    """The amount in euros, as a SQL expression: euros pass through; any other currency is the
    amount divided by its rate on `on`, NULL when there is none. Not rounded, so sums stay
    exact."""
    return case(
        (currency == BASE_CURRENCY, amount),
        else_=amount / rate_on(currency, on),
    )


async def to_eur(session: AsyncSession, amount: Decimal, currency: str, on: date) -> Decimal | None:
    """The same conversion for one value, rounded to the money scale; None without a rate."""
    if currency == BASE_CURRENCY:
        return amount
    rate = await session.scalar(select(rate_on(literal(currency), literal(on, Date))))
    if rate is None:
        return None
    return (amount / rate).quantize(_MONEY_STEP, rounding=ROUND_HALF_UP)


class RateTable:
    """Rates loaded once for many conversions, e.g. a balance on every day of a chart."""

    def __init__(self, rates: dict[str, list[tuple[date, Decimal]]]) -> None:
        self._rates = rates  # per currency, oldest first

    @classmethod
    async def load(
        cls, session: AsyncSession, currencies: Iterable[str], first: date, last: date
    ) -> RateTable:
        wanted = {currency for currency in currencies if currency != BASE_CURRENCY}
        rates: dict[str, list[tuple[date, Decimal]]] = {currency: [] for currency in wanted}
        if wanted:
            rows = await session.execute(
                select(FxRate.quote_currency, FxRate.on, FxRate.rate)
                .where(
                    FxRate.quote_currency.in_(wanted),
                    FxRate.on >= first - timedelta(days=MAX_RATE_AGE_DAYS),
                    FxRate.on <= last,
                )
                .order_by(FxRate.on)
            )
            for currency, on, rate in rows:
                rates[currency].append((on, rate))
        return cls(rates)

    def rate(self, currency: str, on: date) -> Decimal | None:
        if currency == BASE_CURRENCY:
            return Decimal(1)
        rates = self._rates.get(currency, [])
        index = bisect_right(rates, on, key=lambda item: item[0]) - 1
        if index < 0 or (on - rates[index][0]).days > MAX_RATE_AGE_DAYS:
            return None
        return rates[index][1]

    def to_eur(self, amount: Decimal, currency: str, on: date) -> Decimal | None:
        """Not rounded, so sums stay exact; None without a rate."""
        rate = self.rate(currency, on)
        return None if rate is None else amount / rate
