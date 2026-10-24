"""What every data source gives the sync (ADR-0003).

Linking differs too much between sources to share an interface (a bank redirect and consent
for Enable Banking, an API key for Trading 212), so each provider exposes its own. Fetching is
shared: a provider yields raw responses, the sync stores each one in
`finance.provider_payloads`, and the provider's `Normalizer` turns them into records.

A broker (ADR-0008) gives more than a bank: its cash and totals, holdings, order fills and the
instruments they name. Those records are here too; a bank's normalizer has none of them.
"""

from collections.abc import AsyncIterator, Callable, Mapping
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from types import TracebackType
from typing import Any, Protocol, Self

from hubnisio.finance.models import TransactionStatus


@dataclass(frozen=True, slots=True)
class Fetched[T]:
    """One provider response: what was asked, the raw JSON, and its parsed form."""

    kind: str  # e.g. "balances", "transactions"; "summary", "dividends" for Trading 212
    request: dict[str, Any]
    raw: dict[str, Any]
    data: T


class Provider(Protocol):
    """A provider's client, used as `async with`."""

    async def __aenter__(self) -> Self: ...

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None: ...

    def fetch(
        self,
        account_uid: str,
        since: date | None,
        psu_headers: Mapping[str, str] | None = None,
        *,
        trades_since: date | None = None,
    ) -> AsyncIterator[Fetched[Any]]:
        """Yield every response needed to bring one account up to date.

        `since=None` asks for the longest history the source offers (the first sync).
        `trades_since` is the same for a broker's trades; a bank has none.
        `psu_headers` are given only when the user is present and triggered the fetch.
        """
        ...


@dataclass(frozen=True, slots=True)
class TransactionRecord:
    """A transaction as the provider reports it: the bank facts, before identity is assigned."""

    status: TransactionStatus
    amount: Decimal  # negative = money out
    currency: str
    occurred_on: date  # booking date, else transaction date, else value date
    entry_reference: str | None = None
    original_amount: Decimal | None = None
    original_currency: str | None = None
    booking_date: date | None = None
    value_date: date | None = None
    transaction_date: date | None = None
    counterparty_name: str | None = None
    counterparty_iban: str | None = None
    description: str | None = None
    reference: str | None = None
    mcc: str | None = None
    bank_transaction_code: dict[str, Any] | None = None
    balance_after: Decimal | None = None


@dataclass(frozen=True, slots=True)
class BalanceRecord:
    balance_type: str
    amount: Decimal
    currency: str
    reference_date: date | None = None
    last_change_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class NormalizedPage:
    records: list[TransactionRecord] = field(default_factory=list)
    skipped: int = 0  # items that couldn't be parsed
    ignored: int = 0  # items in a state the hub doesn't store, e.g. cancelled or rejected


# A broker's records (ADR-0008). Amounts are in the account's currency unless they say otherwise.


@dataclass(frozen=True, slots=True)
class InstrumentRecord:
    """A tradable instrument, as the broker names it. What a response doesn't say is None."""

    ticker: str  # the broker's own, e.g. AAPL_US_EQ
    isin: str | None = None
    name: str | None = None
    currency: str | None = None  # the instrument's, e.g. USD, or GBX for pence
    type: str | None = None  # STOCK, ETF, …


@dataclass(frozen=True, slots=True)
class PortfolioRecord:
    """The account's cash and totals at one fetch."""

    currency: str
    total_value: Decimal  # cash plus holdings at market value
    cash: Decimal  # available to trade
    cash_in_pies: Decimal
    cash_reserved: Decimal  # for orders not yet filled
    investments_value: Decimal | None = None
    investments_cost: Decimal | None = None
    realised_result: Decimal | None = None
    unrealised_result: Decimal | None = None


@dataclass(frozen=True, slots=True)
class HoldingRecord:
    """One position at one fetch."""

    instrument: InstrumentRecord
    quantity: Decimal
    quantity_in_pies: Decimal | None = None
    average_price: Decimal | None = None  # per share, in the instrument's currency
    current_price: Decimal | None = None  # likewise
    currency: str | None = None  # of the amounts below
    value: Decimal | None = None
    cost: Decimal | None = None
    unrealised_result: Decimal | None = None
    fx_impact: Decimal | None = None  # the part of the result due to exchange rates
    opened_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class TaxRecord:
    """A tax or fee charged on a fill: commission, currency conversion fee, stamp duty, …"""

    name: str
    amount: Decimal
    currency: str | None = None
    charged_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class FillRecord:
    """One execution of an order: a trade, or a corporate action such as a split. Never a
    transaction: a buy moves cash into a holding within the account."""

    fill_id: int  # the broker's: the fill's identity
    instrument: InstrumentRecord
    side: str  # BUY or SELL
    fill_type: str  # TRADE, STOCK_SPLIT, …
    filled_at: datetime
    quantity: Decimal  # as sent
    price: Decimal  # per share, in the instrument's currency
    order_id: int | None = None
    order_type: str | None = None  # MARKET, LIMIT, …
    initiated_from: str | None = None  # WEB, AUTOINVEST, …
    currency: str | None = None  # of the amounts below
    fx_rate: Decimal | None = None
    net_value: Decimal | None = None
    realised_result: Decimal | None = None
    taxes: tuple[TaxRecord, ...] = ()


@dataclass(frozen=True, slots=True)
class HoldingsPage:
    records: list[HoldingRecord] = field(default_factory=list)
    skipped: int = 0


@dataclass(frozen=True, slots=True)
class FillPage:
    records: list[FillRecord] = field(default_factory=list)
    skipped: int = 0  # items that couldn't be parsed
    ignored: int = 0  # orders without a fill: cancelled, rejected, or still working


@dataclass(frozen=True, slots=True)
class Normalizer:
    """Turns one provider's raw payloads into records, by the payload's kind. Pure: no I/O, no
    clock. Kinds it has no function for are stored but not applied."""

    transactions: Mapping[str, Callable[[dict[str, Any]], NormalizedPage]]
    balances: Mapping[str, Callable[[dict[str, Any]], list[BalanceRecord]]]
    # A broker's (ADR-0008); a bank's normalizer leaves them empty.
    portfolios: Mapping[str, Callable[[dict[str, Any]], PortfolioRecord]] = field(
        default_factory=dict[str, Callable[[dict[str, Any]], PortfolioRecord]]
    )
    holdings: Mapping[str, Callable[[dict[str, Any]], HoldingsPage]] = field(
        default_factory=dict[str, Callable[[dict[str, Any]], HoldingsPage]]
    )
    fills: Mapping[str, Callable[[dict[str, Any]], FillPage]] = field(
        default_factory=dict[str, Callable[[dict[str, Any]], FillPage]]
    )
    instruments: Mapping[str, Callable[[dict[str, Any]], list[InstrumentRecord]]] = field(
        default_factory=dict[str, Callable[[dict[str, Any]], list[InstrumentRecord]]]
    )
