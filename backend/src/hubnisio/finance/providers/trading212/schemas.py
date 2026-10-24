"""Trading 212 response models, for the fields the hub reads (Public API v0; the OpenAPI spec is
at https://docs.trading212.com/_bundle/api.json).

Unknown fields are kept (`extra="allow"`), and the raw JSON is stored separately anyway. History
items stay raw dicts in a page: the normalizer parses them one by one, so one odd item can't
fail a whole page.
"""

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel


class _Model(BaseModel):
    # References are documented as strings; take a number too.
    model_config = ConfigDict(
        extra="allow",
        alias_generator=to_camel,
        populate_by_name=True,
        coerce_numbers_to_str=True,
    )


class Cash(_Model):
    available_to_trade: Decimal
    in_pies: Decimal = Decimal(0)
    reserved_for_orders: Decimal = Decimal(0)


class Investments(_Model):
    current_value: Decimal | None = None
    total_cost: Decimal | None = None
    realized_profit_loss: Decimal | None = None
    unrealized_profit_loss: Decimal | None = None


class AccountSummary(_Model):
    """`GET /equity/account/summary`. Amounts are in the account's currency."""

    id: int  # the account number
    currency: str
    total_value: Decimal  # cash plus investments at market value
    cash: Cash
    investments: Investments | None = None


class HistoryPage(_Model):
    """One page of a history endpoint, newest first, at most 50 items."""

    items: list[dict[str, Any]] = []
    next_page_path: str | None = None  # e.g. /api/v0/equity/history/dividends?limit=50&cursor=…


class CashMovement(_Model):
    """An item of `GET /equity/history/transactions`."""

    # WITHDRAW, DEPOSIT, FEE, TRANSFER (between Trading 212 accounts), INTEREST_ON_FREE_CASH,
    # LENDING_INTEREST
    type: str
    amount: Decimal
    currency: str
    date_time: datetime
    reference: str | None = None


class Instrument(_Model):
    ticker: str | None = None  # e.g. AAPL_US_EQ
    name: str | None = None
    isin: str | None = None
    currency: str | None = None


class Dividend(_Model):
    """An item of `GET /equity/history/dividends`."""

    amount: Decimal  # paid, in the account's currency
    currency: str  # the account's currency
    paid_on: datetime
    reference: str | None = None
    type: str | None = None  # ORDINARY, RETURN_OF_CAPITAL_NON_US, … (58 kinds)
    ticker: str | None = None
    ticker_currency: str | None = None
    instrument: Instrument | None = None
    quantity: Decimal | None = None
    gross_amount_per_share: Decimal | None = None  # in the instrument's currency
    amount_in_euro: Decimal | None = None


def day_of(moment: datetime) -> date:
    """The UTC day of a Trading 212 timestamp; one without an offset is taken as UTC."""
    if moment.tzinfo is None:
        return moment.date()
    return moment.astimezone(UTC).date()
