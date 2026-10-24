"""Investment accounts as they stand (ADR-0008): value, cash, cost and result, the holdings, and
the dividends and interest they paid by month.

Everything comes from the account's latest portfolio snapshot (the summary and positions of its
latest sync) and from its cash movements, in the account's currency. A holding's weight is its
share of the holdings' value, cash left out. The check sets the value rebuilt from trades and
daily prices against Trading 212's own (insights/portfolio.py).

`investments` loads the inputs and `compute_investments` computes from them, so the MCP server
can load the same inputs from the `analytics` views and give the same figures (ADR-0006).
"""

import uuid
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Date, DateTime, cast, func, select
from sqlalchemy.dialects.postgresql import distinct_on
from sqlalchemy.ext.asyncio import AsyncSession

from hubnisio.core.auth import Principal
from hubnisio.finance import schemas
from hubnisio.finance.fx.convert import RateTable
from hubnisio.finance.insights.portfolio import Portfolio, check, load_portfolios
from hubnisio.finance.insights.spending import add_months, cents, month_start
from hubnisio.finance.models import (
    Account,
    HoldingSnapshot,
    Instrument,
    PortfolioSnapshot,
    Transaction,
    TransactionStatus,
)
from hubnisio.finance.naming import account_name
from hubnisio.finance.prices.table import PriceTable
from hubnisio.finance.providers.trading212.normalize import CODE_PREFIX, DIVIDEND_CODE
from hubnisio.finance.scoping import listed_account_ids

# The bank codes of an investment account's income (ADR-0008, "As built in T1").
INCOME_CODES = {
    DIVIDEND_CODE: "dividends",
    f"{CODE_PREFIX}INTEREST_ON_FREE_CASH": "interest",
    f"{CODE_PREFIX}LENDING_INTEREST": "interest",
}
WEIGHT = Decimal("0.0001")


@dataclass(frozen=True)
class Totals:
    """The summary's figures at the latest sync."""

    as_of: datetime
    total_value: Decimal
    cash: Decimal  # available, in pies and reserved for orders
    investments_value: Decimal | None
    investments_cost: Decimal | None
    realised_result: Decimal | None
    unrealised_result: Decimal | None


@dataclass(frozen=True)
class Holding:
    ticker: str
    isin: str | None
    name: str | None
    type: str | None
    instrument_currency: str | None
    quantity: Decimal
    average_price: Decimal | None
    current_price: Decimal | None
    value: Decimal | None
    cost: Decimal | None
    result: Decimal | None


@dataclass
class InvestmentInputs:
    id: uuid.UUID
    name: str
    currency: str
    totals: Totals | None = None  # None until a sync has read the positions
    holdings: list[Holding] = field(default_factory=list[Holding])
    # Dividends and interest: (month's first day, "dividends" or "interest") → their sum.
    income: dict[tuple[date, str], Decimal] = field(default_factory=dict[tuple[date, str], Decimal])
    portfolio: Portfolio | None = None  # the rebuild's inputs, with the same snapshot as totals


async def investments(
    session: AsyncSession, principal: Principal, months: Sequence[date]
) -> schemas.InvestmentsOut:
    accounts = await load_investments(session, principal, months)
    portfolios = [account.portfolio for account in accounts if account.portfolio is not None]
    days = [portfolio.on for portfolio in portfolios]
    if not days:
        return compute_investments(accounts, months, PriceTable({}, {}), RateTable({}))
    instruments = {i for portfolio in portfolios for i in portfolio.instrument_ids}
    prices = await PriceTable.load(session, instruments, min(days), max(days))
    currencies = {portfolio.currency for portfolio in portfolios} | prices.currencies
    rates = await RateTable.load(session, currencies, min(days), max(days))
    return compute_investments(accounts, months, prices, rates)


async def load_investments(
    session: AsyncSession, principal: Principal, months: Sequence[date]
) -> list[InvestmentInputs]:
    """The principal's listed investment accounts, with their income over `months`."""
    accounts = {
        account.id: InvestmentInputs(account.id, account_name(account), account.currency)
        for account in await session.scalars(
            select(Account)
            .where(Account.id.in_(listed_account_ids(principal)), Account.is_investment)
            .order_by(Account.institution_name, Account.created_at)
        )
    }
    if not accounts:
        return []
    ids = list(accounts)
    for account_id, portfolio in (await load_portfolios(session, ids)).items():
        accounts[account_id].portfolio = portfolio

    snapshots = list(
        await session.scalars(
            select(PortfolioSnapshot)
            .where(PortfolioSnapshot.account_id.in_(ids))
            .order_by(
                PortfolioSnapshot.account_id,
                PortfolioSnapshot.fetched_at.desc(),
                PortfolioSnapshot.id.desc(),
            )
            .ext(distinct_on(PortfolioSnapshot.account_id))
        )
    )
    for snapshot in snapshots:
        accounts[snapshot.account_id].totals = Totals(
            as_of=snapshot.fetched_at,
            total_value=snapshot.total_value,
            cash=snapshot.cash + snapshot.cash_in_pies + snapshot.cash_reserved,
            investments_value=snapshot.investments_value,
            investments_cost=snapshot.investments_cost,
            realised_result=snapshot.realised_result,
            unrealised_result=snapshot.unrealised_result,
        )
    rows = await session.execute(
        select(HoldingSnapshot, Instrument)
        .join(Instrument, Instrument.id == HoldingSnapshot.instrument_id)
        .where(HoldingSnapshot.portfolio_snapshot_id.in_([s.id for s in snapshots]))
    )
    for holding, instrument in rows:
        accounts[holding.account_id].holdings.append(
            Holding(
                ticker=instrument.ticker,
                isin=instrument.isin,
                name=instrument.name,
                type=instrument.type,
                instrument_currency=instrument.currency,
                quantity=holding.quantity,
                average_price=holding.average_price,
                current_price=holding.current_price,
                value=holding.value,
                cost=holding.cost,
                result=holding.unrealised_result,
            )
        )

    if months:
        month = cast(func.date_trunc("month", cast(Transaction.occurred_on, DateTime)), Date)
        code = Transaction.bank_transaction_code["code"].astext
        income = await session.execute(
            select(Transaction.account_id, month, code, func.sum(Transaction.amount))
            .where(
                Transaction.account_id.in_(ids),
                Transaction.status == TransactionStatus.BOOKED,
                code.in_(list(INCOME_CODES)),
                Transaction.occurred_on >= month_start(months[0]),
                Transaction.occurred_on < add_months(month_start(months[-1]), 1),
            )
            .group_by(Transaction.account_id, month, code)
        )
        for account_id, on, bank_code, total in income:
            sums = accounts[account_id].income
            key = (on, INCOME_CODES[bank_code])
            sums[key] = sums.get(key, Decimal(0)) + total
    return list(accounts.values())


def compute_investments(
    accounts: Sequence[InvestmentInputs],
    months: Sequence[date],
    prices: PriceTable,
    rates: RateTable,
) -> schemas.InvestmentsOut:
    """`prices` and `rates` must cover each portfolio's day, for its check."""
    return schemas.InvestmentsOut(
        months=list(months),
        accounts=[_account_out(account, months, prices, rates) for account in accounts],
    )


def _account_out(
    account: InvestmentInputs, months: Sequence[date], prices: PriceTable, rates: RateTable
) -> schemas.InvestmentAccount:
    holdings = sorted(
        account.holdings,
        key=lambda holding: (
            holding.value is None,
            -(holding.value or Decimal(0)),
            holding.name or holding.ticker,
        ),
    )
    held = sum((holding.value for holding in holdings if holding.value is not None), Decimal(0))
    income: dict[str, list[Decimal]] = defaultdict(list)
    for month in months:
        for kind in ("dividends", "interest"):
            income[kind].append(cents(account.income.get((month, kind), Decimal(0))))
    totals = account.totals
    cost = result = None
    if totals is not None:
        cost = totals.investments_cost
        if cost is None and holdings:
            cost = sum((holding.cost or Decimal(0) for holding in holdings), Decimal(0))
        result = totals.unrealised_result
        if result is None and cost is not None:
            result = (totals.investments_value or held) - cost
    return schemas.InvestmentAccount(
        id=account.id,
        name=account.name,
        currency=account.currency,
        as_of=totals.as_of if totals else None,
        value=_cents(totals.total_value if totals else None),
        cash=_cents(totals.cash if totals else None),
        cost=_cents(cost),
        result=_cents(result),
        realised_result=_cents(totals.realised_result if totals else None),
        holdings=[
            schemas.Holding(
                ticker=holding.ticker,
                isin=holding.isin,
                name=holding.name or holding.ticker,
                type=holding.type,
                instrument_currency=holding.instrument_currency,
                quantity=holding.quantity,
                average_price=holding.average_price,
                current_price=holding.current_price,
                value=_cents(holding.value),
                cost=_cents(holding.cost),
                result=_cents(holding.result),
                weight=(holding.value / held).quantize(WEIGHT)
                if holding.value is not None and held
                else None,
            )
            for holding in holdings
        ],
        dividends=income["dividends"],
        interest=income["interest"],
        check=check(account.portfolio, prices, rates) if account.portfolio else None,
    )


def _cents(amount: Decimal | None) -> Decimal | None:
    return None if amount is None else cents(amount)
