"""An investment account's value over time, rebuilt from its trades (ADR-0008, "Value over
time").

The latest portfolio snapshot is the anchor, as a bank's balance is. A holding's quantity on a
day is the snapshot's, moved back by the fills since; the cash is the snapshot's (available, in
pies and reserved for orders), moved back by the cash movements and the fills' net values. A
fill's side gives the direction, on its absolute quantity and net value: Trading 212 sends a
sell's quantity negative and every net value positive (ADR-0008, "As built in T2"). Corporate
actions such as splits are fills with a side too.

A day's value is its cash plus each holding at its price that day (finance/prices/table.py),
converted at that day's exchange rate. A holding without a price is left out of the day and
counted; there's never a fallback to cost.

What the history doesn't explain is what the rebuild holds before the account's first
movement, which should be nothing. Those amounts, and the rebuilt value on the snapshot's day
against the broker's own total, are the check: reported, never hidden.

`load_portfolios` loads the inputs and the rest is pure, so the MCP server can load the same
inputs from the `analytics` views and give the same figures (ADR-0006).
"""

import uuid
from collections import defaultdict
from collections.abc import Collection, Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import distinct_on
from sqlalchemy.ext.asyncio import AsyncSession

from hubnisio.finance import schemas
from hubnisio.finance.fx.convert import RateTable
from hubnisio.finance.insights.spending import cents
from hubnisio.finance.models import (
    Fill,
    HoldingSnapshot,
    PortfolioSnapshot,
    Transaction,
    TransactionStatus,
)
from hubnisio.finance.prices.table import PriceTable

BUY = "BUY"


@dataclass(frozen=True, slots=True)
class FillMove:
    """What a fill did to the account: shares in or out, and cash the other way."""

    instrument_id: uuid.UUID
    filled_at: datetime
    quantity: Decimal  # positive when bought, negative when sold
    cash: Decimal  # positive when received, negative when paid
    # Its taxes and fees as (amount, currency), as sent; the cash includes them.
    taxes: tuple[tuple[Decimal, str | None], ...] = ()

    @classmethod
    def of(
        cls,
        instrument_id: uuid.UUID,
        filled_at: datetime,
        side: str,
        quantity: Decimal,
        net_value: Decimal | None,
        taxes: Iterable[Mapping[str, Any]] = (),
    ) -> FillMove:
        """`taxes` as stored: [{name, amount, currency, charged_at}], amounts as strings."""
        sign = 1 if side == BUY else -1
        return cls(
            instrument_id,
            filled_at,
            sign * abs(quantity),
            -sign * abs(net_value or Decimal(0)),
            tuple((Decimal(str(tax["amount"])), tax.get("currency")) for tax in taxes),
        )

    @property
    def on(self) -> date:
        return self.filled_at.astimezone(UTC).date()


@dataclass
class Portfolio:
    account_id: uuid.UUID
    currency: str  # the account's
    as_of: datetime  # when the latest snapshot was read
    cash: Decimal  # then: available, in pies and reserved for orders
    total_value: Decimal  # the broker's own, then
    holdings: dict[uuid.UUID, Decimal]  # instrument → quantity, then
    fills: list[FillMove] = field(default_factory=list[FillMove])
    movements: dict[date, Decimal] = field(default_factory=dict[date, Decimal])  # booked, per day

    @property
    def on(self) -> date:
        return self.as_of.astimezone(UTC).date()

    @property
    def instrument_ids(self) -> set[uuid.UUID]:
        return set(self.holdings) | {fill.instrument_id for fill in self.fills}

    @property
    def first_day(self) -> date | None:
        """Its first movement's day: the broker keeps the whole history, so it was empty
        before."""
        return min([*self.movements, *(fill.on for fill in self.fills)], default=None)


@dataclass(frozen=True, slots=True)
class DayValue:
    on: date
    value: Decimal | None  # in the account's currency; None without an exchange rate for it
    eur: Decimal | None  # likewise; neither is rounded
    unpriced: frozenset[uuid.UUID]  # holdings left out: no price or exchange rate


class Rebuild:
    def __init__(self, portfolio: Portfolio) -> None:
        self.portfolio = portfolio
        before = [fill for fill in portfolio.fills if fill.filled_at <= portfolio.as_of]
        moved = sum((v for d, v in portfolio.movements.items() if d <= portfolio.on), Decimal(0))
        # What the rebuild holds before any movement: what the history doesn't explain.
        self.opening_cash = portfolio.cash - moved - sum((f.cash for f in before), Decimal(0))
        self.opening_quantities = {
            instrument_id: portfolio.holdings.get(instrument_id, Decimal(0))
            - sum((f.quantity for f in before if f.instrument_id == instrument_id), Decimal(0))
            for instrument_id in portfolio.instrument_ids
        }
        self._cash: dict[date, Decimal] = defaultdict(Decimal, portfolio.movements)
        self._quantities: dict[date, dict[uuid.UUID, Decimal]] = defaultdict(
            lambda: defaultdict(Decimal)
        )
        for fill in portfolio.fills:
            self._cash[fill.on] += fill.cash
            self._quantities[fill.on][fill.instrument_id] += fill.quantity

    def values(
        self, start: date, end: date, prices: PriceTable, rates: RateTable
    ) -> list[DayValue]:
        """The value at the end of each day from `start` to `end`."""
        cash = self.opening_cash + sum((v for d, v in self._cash.items() if d < start), Decimal(0))
        quantities = defaultdict(Decimal, self.opening_quantities)
        for day, moves in self._quantities.items():
            if day < start:
                for instrument_id, quantity in moves.items():
                    quantities[instrument_id] += quantity
        out: list[DayValue] = []
        day = start
        while day <= end:
            cash += self._cash.get(day, Decimal(0))
            for instrument_id, quantity in self._quantities.get(day, {}).items():
                quantities[instrument_id] += quantity
            out.append(self._value(day, cash, quantities.items(), prices, rates))
            day += timedelta(days=1)
        return out

    def quantities(self, day: date) -> dict[uuid.UUID, Decimal]:
        """Each holding's quantity at the end of the day, those it holds none of left out."""
        quantities = defaultdict(Decimal, self.opening_quantities)
        for on, moves in self._quantities.items():
            if on <= day:
                for instrument_id, quantity in moves.items():
                    quantities[instrument_id] += quantity
        return {instrument_id: q for instrument_id, q in quantities.items() if q != 0}

    def _value(
        self,
        day: date,
        cash: Decimal,
        quantities: Iterable[tuple[uuid.UUID, Decimal]],
        prices: PriceTable,
        rates: RateTable,
    ) -> DayValue:
        held = Decimal(0)  # in euros
        unpriced: set[uuid.UUID] = set()
        for instrument_id, quantity in quantities:
            if quantity == 0:
                continue
            eur = prices.value_eur(instrument_id, quantity, day, rates)
            if eur is None:
                unpriced.add(instrument_id)
            else:
                held += eur
        currency = self.portfolio.currency
        rate, cash_eur = rates.rate(currency, day), rates.to_eur(cash, currency, day)
        if rate is None or cash_eur is None:
            return DayValue(day, None, None, frozenset(unpriced))
        return DayValue(day, cash + held * rate, cash_eur + held, frozenset(unpriced))


def check(portfolio: Portfolio, prices: PriceTable, rates: RateTable) -> schemas.InvestmentCheck:
    """The rebuild against the broker on the snapshot's day, and what the history doesn't
    explain. `prices` and `rates` must cover that day."""
    rebuild = Rebuild(portfolio)
    day = rebuild.values(portfolio.on, portfolio.on, prices, rates)[0]
    rebuilt = None if day.value is None else cents(day.value)

    def described(instrument_id: uuid.UUID) -> tuple[str, str]:
        info = prices.instruments.get(instrument_id)
        return (info.ticker, info.label) if info else (str(instrument_id), str(instrument_id))

    return schemas.InvestmentCheck(
        on=portfolio.on,
        rebuilt_value=rebuilt,
        difference=None if rebuilt is None else rebuilt - cents(portfolio.total_value),
        unpriced=sorted(described(instrument_id)[1] for instrument_id in day.unpriced),
        unexplained_cash=cents(rebuild.opening_cash),
        unexplained=sorted(
            (
                schemas.UnexplainedQuantity(
                    ticker=described(instrument_id)[0],
                    name=described(instrument_id)[1],
                    quantity=quantity,
                )
                for instrument_id, quantity in rebuild.opening_quantities.items()
                if quantity != 0
            ),
            key=lambda item: item.name,
        ),
    )


async def load_portfolios(
    session: AsyncSession, account_ids: Collection[uuid.UUID]
) -> dict[uuid.UUID, Portfolio]:
    """The accounts' latest portfolio snapshots, with their fills and cash movements. An
    account without a snapshot yet has none."""
    if not account_ids:
        return {}
    snapshots = list(
        await session.scalars(
            select(PortfolioSnapshot)
            .where(PortfolioSnapshot.account_id.in_(list(account_ids)))
            .order_by(
                PortfolioSnapshot.account_id,
                PortfolioSnapshot.fetched_at.desc(),
                PortfolioSnapshot.id.desc(),
            )
            .ext(distinct_on(PortfolioSnapshot.account_id))
        )
    )
    portfolios = {
        snapshot.account_id: Portfolio(
            account_id=snapshot.account_id,
            currency=snapshot.currency,
            as_of=snapshot.fetched_at,
            cash=snapshot.cash + snapshot.cash_in_pies + snapshot.cash_reserved,
            total_value=snapshot.total_value,
            holdings={},
        )
        for snapshot in snapshots
    }
    if not portfolios:
        return {}
    ids = list(portfolios)
    for account_id, instrument_id, quantity in await session.execute(
        select(
            HoldingSnapshot.account_id,
            HoldingSnapshot.instrument_id,
            func.sum(HoldingSnapshot.quantity),
        )
        .where(HoldingSnapshot.portfolio_snapshot_id.in_([s.id for s in snapshots]))
        .group_by(HoldingSnapshot.account_id, HoldingSnapshot.instrument_id)
    ):
        portfolios[account_id].holdings[instrument_id] = quantity
    for row in await session.execute(
        select(
            Fill.account_id,
            Fill.instrument_id,
            Fill.filled_at,
            Fill.side,
            Fill.quantity,
            Fill.net_value,
            Fill.taxes,
        )
        .where(Fill.account_id.in_(ids))
        .order_by(Fill.filled_at, Fill.id)
    ):
        portfolios[row.account_id].fills.append(
            FillMove.of(
                row.instrument_id,
                row.filled_at,
                row.side,
                row.quantity,
                row.net_value,
                row.taxes,
            )
        )
    for account_id, on, total in await session.execute(
        select(Transaction.account_id, Transaction.occurred_on, func.sum(Transaction.amount))
        .where(Transaction.account_id.in_(ids), Transaction.status == TransactionStatus.BOOKED)
        .group_by(Transaction.account_id, Transaction.occurred_on)
    ):
        portfolios[account_id].movements[on] = total
    return portfolios
