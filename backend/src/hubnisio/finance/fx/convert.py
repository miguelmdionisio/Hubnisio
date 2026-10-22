"""Converting amounts into euros (ADR-0007, "FX rates").

An amount is converted at the rate for its day: the latest rate published on or before that
day, if it is at most MAX_RATE_AGE_DAYS old. Without one the result is NULL (None), never the
amount unconverted, so callers can leave it out and say so.
"""

from datetime import date
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
