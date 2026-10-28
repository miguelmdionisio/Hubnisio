"""An investment account's returns over a period (ADR-0008, "Returns").

Everything comes from the account's daily values, rebuilt from its trades and daily prices
(insights/portfolio.py), and from its cash movements, in the account's currency:

- **Net deposits** are deposits, withdrawals and transfers to and from other Trading 212
  accounts: money from outside the account, not what it earned.
- **The breakdown** splits the result, the change in value less net deposits, into parts that
  add up to it. Price movements are split by average cost, as Trading 212 does, with what's
  held at the start costing its value that day: realised on what was sold in the period,
  unrealised on what's held at its end. A fill that moved no cash (a corporate action) changes
  the quantity, not the cost. Fees and taxes are those on trades, which their net values
  include, and those charged on their own. Rounded to cents, the price movements take the
  rounding: unrealised while something's held at the end, else realised.
- **The time-weighted return** chains each day's return: the day's change less its net
  deposit, over the value it started from plus any money in that day. Money out counts at the
  end of the day, so a full withdrawal leaves something to divide by. A day with nothing
  invested counts for nothing. It shows how the investments did, whatever the timing.
- **The money-weighted return** is the rate (XIRR) at which the start value and the net
  deposits grow into the end value: what the money earned, given when it came in. Over the
  period, it runs from the first money in.
- **Value against net deposits:** each day's value, and the net deposits since the account
  opened.

A period starts on the account's first movement at the earliest, and ends today at the latest.
Its start value is the value at the end of the day before. A year's equivalent of either
return is given only for a period of a year or more. A day's value leaves out holdings without
a price or exchange rate, as net worth does: they're counted (`unpriced`), never hidden.

`investment_returns` loads the inputs and `compute_returns` computes from them, so the MCP
server can load the same inputs from the `analytics` views and give the same figures
(ADR-0006).
"""

import math
import uuid
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from hubnisio.core.auth import Principal
from hubnisio.finance import schemas
from hubnisio.finance.fx.convert import RateTable
from hubnisio.finance.insights.investments import INCOME_CODES
from hubnisio.finance.insights.portfolio import (
    DayValue,
    FillMove,
    Portfolio,
    Rebuild,
    load_portfolios,
)
from hubnisio.finance.insights.spending import cents
from hubnisio.finance.models import Account, Transaction, TransactionStatus
from hubnisio.finance.naming import account_name
from hubnisio.finance.prices.table import PriceTable
from hubnisio.finance.providers.trading212.normalize import CODE_PREFIX
from hubnisio.finance.scoping import listed_account_ids

# Money from outside the account (ADR-0008, "As built in T1"): by its sign, a deposit or a
# withdrawal.
DEPOSIT_CODES = {f"{CODE_PREFIX}DEPOSIT", f"{CODE_PREFIX}WITHDRAW", f"{CODE_PREFIX}TRANSFER"}
FEE_CODES = {f"{CODE_PREFIX}FEE"}
DEPOSITS, WITHDRAWALS, FEES, OTHER = "deposits", "withdrawals", "fees", "other"
RATE = Decimal("0.0001")
YEAR = 365  # days


def part(code: str | None, money_in: bool) -> str:
    """What a cash movement is: deposits, withdrawals, dividends, interest, fees or other."""
    if code in DEPOSIT_CODES:
        return DEPOSITS if money_in else WITHDRAWALS
    if code in FEE_CODES:
        return FEES
    return INCOME_CODES.get(code or "", OTHER)


@dataclass
class ReturnsInputs:
    id: uuid.UUID
    name: str
    currency: str
    portfolio: Portfolio | None = None  # None until a sync has read the positions
    # Booked cash movements: (day, part) → their sum, where `part` names the part.
    movements: dict[tuple[date, str], Decimal] = field(
        default_factory=dict[tuple[date, str], Decimal]
    )

    def deposits(self) -> dict[date, Decimal]:
        """Net deposits per day."""
        out: dict[date, Decimal] = defaultdict(Decimal)
        for (on, kind), amount in self.movements.items():
            if kind in (DEPOSITS, WITHDRAWALS):
                out[on] += amount
        return out


def period(
    account: ReturnsInputs, today: date, date_from: date | None, date_to: date | None
) -> tuple[date, date] | None:
    """The account's first and last day in the period; None without a history yet."""
    first = account.portfolio.first_day if account.portfolio else None
    if first is None:
        return None
    end = min(date_to or today, today)
    return min(max(date_from or first, first), end), end


async def investment_returns(
    session: AsyncSession,
    principal: Principal,
    today: date,
    date_from: date | None = None,
    date_to: date | None = None,
) -> schemas.InvestmentReturnsOut:
    accounts = await load_returns(session, principal)
    prices, rates = PriceTable({}, {}), RateTable({})
    if (needed := tables_needed(accounts, today, date_from, date_to)) is not None:
        instruments, wanted, first, last = needed
        prices = await PriceTable.load(session, instruments, first, last)
        rates = await RateTable.load(session, wanted | prices.currencies, first, last)
    return compute_returns(accounts, prices, rates, today, date_from, date_to)


def tables_needed(
    accounts: Sequence[ReturnsInputs], today: date, date_from: date | None, date_to: date | None
) -> tuple[set[uuid.UUID], set[str], date, date] | None:
    """The instruments, currencies and days `compute_returns` needs prices and rates for; None
    when no account has a history in the period. The instruments' currencies come with their
    prices."""
    spans = [s for account in accounts if (s := period(account, today, date_from, date_to))]
    if not spans:
        return None
    instruments = {i for a in accounts if a.portfolio for i in a.portfolio.instrument_ids}
    first = min(start for start, _ in spans) - timedelta(days=1)
    return instruments, currencies(accounts), first, max(end for _, end in spans)


def currencies(accounts: Sequence[ReturnsInputs]) -> set[str]:
    """The accounts' own and their trades' taxes'; the instruments' come with their prices."""
    return {account.currency for account in accounts} | {
        currency
        for account in accounts
        if account.portfolio
        for fill in account.portfolio.fills
        for _, currency in fill.taxes
        if currency
    }


async def load_returns(session: AsyncSession, principal: Principal) -> list[ReturnsInputs]:
    """The principal's listed investment accounts, with their portfolios and cash movements."""
    accounts = {
        account.id: ReturnsInputs(account.id, account_name(account), account.currency)
        for account in await session.scalars(
            select(Account)
            .where(Account.id.in_(listed_account_ids(principal)), Account.is_investment)
            .order_by(Account.institution_name, Account.created_at)
        )
    }
    if not accounts:
        return []
    for account_id, portfolio in (await load_portfolios(session, list(accounts))).items():
        accounts[account_id].portfolio = portfolio
    await _load_movements(session, accounts)
    return list(accounts.values())


async def _load_movements(session: AsyncSession, accounts: dict[uuid.UUID, ReturnsInputs]) -> None:
    code = Transaction.bank_transaction_code["code"].astext
    money_in = Transaction.amount > 0
    rows = await session.execute(
        select(
            Transaction.account_id,
            Transaction.occurred_on,
            code,
            money_in,
            func.sum(Transaction.amount),
        )
        .where(
            Transaction.account_id.in_(list(accounts)),
            Transaction.status == TransactionStatus.BOOKED,
        )
        .group_by(Transaction.account_id, Transaction.occurred_on, code, money_in)
    )
    for account_id, on, bank_code, is_in, amount in rows:
        add_movement(accounts[account_id], on, bank_code, is_in, amount)


def add_movement(
    account: ReturnsInputs, on: date, code: str | None, money_in: bool, amount: Decimal
) -> None:
    key = (on, part(code, money_in))
    account.movements[key] = account.movements.get(key, Decimal(0)) + amount


def compute_returns(
    accounts: Sequence[ReturnsInputs],
    prices: PriceTable,
    rates: RateTable,
    today: date,
    date_from: date | None = None,
    date_to: date | None = None,
) -> schemas.InvestmentReturnsOut:
    """`prices` and `rates` must cover each account's period (`period`) and the day before."""
    return schemas.InvestmentReturnsOut(
        accounts=[
            account_returns(account, prices, rates, period(account, today, date_from, date_to))
            for account in accounts
        ]
    )


def account_returns(
    account: ReturnsInputs,
    prices: PriceTable,
    rates: RateTable,
    span: tuple[date, date] | None,
) -> schemas.InvestmentReturns:
    if account.portfolio is None or span is None:
        return _no_history(account)
    start, end = span
    before = start - timedelta(days=1)
    rebuild = Rebuild(account.portfolio)
    values = rebuild.values(before, end, prices, rates)
    opening, days = values[0], values[1:]
    deposits = account.deposits()
    sums: dict[str, Decimal] = defaultdict(Decimal)
    for (on, kind), amount in account.movements.items():
        if start <= on <= end:
            sums[kind] += amount
    net_deposits = sums[DEPOSITS] + sums[WITHDRAWALS]
    time_weighted, time_gap = _time_weighted(opening, days, deposits)
    money_weighted, money_annual, money_gap = _money_weighted(opening, days, deposits)
    length = (end - start).days + 1
    return schemas.InvestmentReturns(
        id=account.id,
        name=account.name,
        currency=account.currency,
        date_from=start,
        date_to=end,
        start_value=_cents(opening.value),
        end_value=_cents(days[-1].value),
        deposits=cents(sums[DEPOSITS]),
        withdrawals=cents(sums[WITHDRAWALS]),
        net_deposits=cents(net_deposits),
        breakdown=_breakdown(
            account.portfolio, rebuild, prices, rates, span, sums, opening, days[-1]
        ),
        time_weighted=_rate(time_weighted),
        time_weighted_annual=_rate(
            None if time_weighted is None or length < YEAR else _annual(time_weighted, length)
        ),
        time_weighted_gap=time_gap,
        money_weighted=_rate(money_weighted),
        money_weighted_annual=_rate(money_annual if length >= YEAR else None),
        money_weighted_gap=money_gap,
        unpriced=sum(len(day.unpriced) for day in days),
        unconverted=sum(day.value is None for day in days),
        points=_points(days, deposits, before),
    )


def _no_history(account: ReturnsInputs) -> schemas.InvestmentReturns:
    zero = Decimal("0.00")
    return schemas.InvestmentReturns(
        id=account.id,
        name=account.name,
        currency=account.currency,
        date_from=None,
        date_to=None,
        start_value=None,
        end_value=None,
        deposits=zero,
        withdrawals=zero,
        net_deposits=zero,
        breakdown=None,
        time_weighted=None,
        time_weighted_annual=None,
        time_weighted_gap=schemas.ReturnGap.NO_MONEY,
        money_weighted=None,
        money_weighted_annual=None,
        money_weighted_gap=schemas.ReturnGap.NO_MONEY,
        unpriced=0,
        unconverted=0,
        points=[],
    )


@dataclass
class PriceMovements:
    """Not rounded."""

    realised: Decimal
    unrealised: Decimal
    fees: Decimal  # on trades, negative when paid
    held: bool  # whether anything is held at the end


def price_movements(
    portfolio: Portfolio,
    rebuild: Rebuild,
    prices: PriceTable,
    rates: RateTable,
    span: tuple[date, date],
) -> PriceMovements:
    """The trades' result over the period, by average cost."""
    start, end = span
    before = start - timedelta(days=1)
    currency = portfolio.currency
    held: dict[uuid.UUID, Decimal] = defaultdict(Decimal, rebuild.quantities(before))
    # What's held at the start costs its value then; one left out of that day's value, nothing.
    cost: dict[uuid.UUID, Decimal] = defaultdict(Decimal)
    for instrument_id, quantity in held.items():
        cost[instrument_id] = _value(instrument_id, quantity, before, currency, prices, rates)
    realised = fees = Decimal(0)
    for fill in portfolio.fills:
        if not start <= fill.on <= end:
            continue
        fee = _fee(fill, currency, rates)  # positive when charged
        fees -= fee
        instrument_id = fill.instrument_id
        if fill.quantity > 0:
            cost[instrument_id] += -fill.cash - fee  # the price paid, without the fee
        elif fill.quantity < 0 and fill.cash != 0:
            quantity = held[instrument_id]
            share = min(-fill.quantity / quantity, Decimal(1)) if quantity > 0 else Decimal(0)
            sold = cost[instrument_id] * share
            cost[instrument_id] -= sold
            realised += fill.cash + fee - sold  # the price received, without the fee
        held[instrument_id] += fill.quantity
    unrealised = Decimal(0)
    for instrument_id, remaining in cost.items():
        quantity = held[instrument_id]
        if quantity == 0:
            realised -= remaining  # nothing left of it: what it cost is gone
        else:
            value = _value(instrument_id, quantity, end, currency, prices, rates)
            unrealised += value - remaining
    return PriceMovements(
        realised, unrealised, fees, any(quantity != 0 for quantity in held.values())
    )


def _breakdown(
    portfolio: Portfolio,
    rebuild: Rebuild,
    prices: PriceTable,
    rates: RateTable,
    span: tuple[date, date],
    sums: dict[str, Decimal],
    opening: DayValue,
    closing: DayValue,
) -> schemas.ReturnsBreakdown | None:
    if opening.value is None or closing.value is None:
        return None
    moves = price_movements(portfolio, rebuild, prices, rates, span)
    total = cents(closing.value) - cents(opening.value) - cents(sums[DEPOSITS] + sums[WITHDRAWALS])
    dividends, interest = cents(sums["dividends"]), cents(sums["interest"])
    fees, other = cents(sums[FEES] + moves.fees), cents(sums[OTHER])
    rest = dividends + interest + fees + other
    if moves.held:
        realised = cents(moves.realised)
        unrealised = total - rest - realised
    else:
        unrealised = Decimal("0.00")
        realised = total - rest
    return schemas.ReturnsBreakdown(
        unrealised=unrealised,
        realised=realised,
        dividends=dividends,
        interest=interest,
        fees=fees,
        other=other,
        total=total,
    )


def _time_weighted(
    opening: DayValue, days: Sequence[DayValue], deposits: dict[date, Decimal]
) -> tuple[Decimal | None, schemas.ReturnGap | None]:
    """Each day's return, chained. A day without a value passes its deposits to the next."""
    growth, invested = Decimal(1), False
    previous, pending = opening.value, Decimal(0)
    for day in days:
        pending += deposits.get(day.on, Decimal(0))
        if day.value is None:
            continue
        if previous is not None:
            base = previous + max(pending, Decimal(0))
            if base > 0:
                growth *= 1 + (day.value - previous - pending) / base
                invested = True
        previous, pending = day.value, Decimal(0)
    if invested:
        return growth - 1, None
    if all(day.value is None for day in days):
        return None, schemas.ReturnGap.NO_VALUE
    return None, schemas.ReturnGap.NO_MONEY


def _money_weighted(
    opening: DayValue, days: Sequence[DayValue], deposits: dict[date, Decimal]
) -> tuple[Decimal | None, Decimal | None, schemas.ReturnGap | None]:
    """Over the period from its first money in, and a year's rate (the XIRR)."""
    closing = days[-1]
    if opening.value is None or closing.value is None:
        return None, None, schemas.ReturnGap.NO_VALUE
    # The money's side: what goes in is negative, what comes out positive.
    flows: list[tuple[date, Decimal]] = []
    if opening.value > 0:
        flows.append((opening.on, -opening.value))
    flows += [(day.on, -deposits[day.on]) for day in days if deposits.get(day.on)]
    flows.append((closing.on, closing.value))
    first = next((on for on, amount in flows if amount < 0), None)
    if first is None:
        return None, None, schemas.ReturnGap.NO_MONEY
    rate = xirr([((on - first).days / YEAR, float(amount)) for on, amount in flows])
    if rate is None:
        return None, None, schemas.ReturnGap.NO_SOLUTION
    over = (1 + rate) ** ((closing.on - first).days / YEAR) - 1
    return Decimal(over), Decimal(rate), None


def xirr(flows: Sequence[tuple[float, float]]) -> float | None:
    """The yearly rate at which the flows (years from the first, amount) are worth nothing
    together. None without one: flows all one way, or no rate between -100% and a billion
    times over. Bisection, slower than Newton's method but sure to converge once a sign
    change is bracketed."""
    if not (any(a < 0 for _, a in flows) and any(a > 0 for _, a in flows)):
        return None

    def worth(rate: float) -> float:
        total = 0.0
        for years, amount in flows:
            try:
                total += amount * (1 + rate) ** -years
            except OverflowError:
                return math.copysign(math.inf, amount)
        return total

    low, high = -0.999999, 1.0
    at_low = worth(low)
    while worth(high) * at_low > 0:
        if high > 1e9:
            return None
        high *= 10
    for _ in range(200):
        middle = (low + high) / 2
        at_middle = worth(middle)
        if at_middle == 0 or high - low < 1e-12:
            return middle
        if at_middle * at_low > 0:
            low, at_low = middle, at_middle
        else:
            high = middle
    return (low + high) / 2


def _points(
    days: Sequence[DayValue], deposits: dict[date, Decimal], before: date
) -> list[schemas.ValuePoint]:
    net = sum((amount for on, amount in deposits.items() if on <= before), Decimal(0))
    points: list[schemas.ValuePoint] = []
    for day in days:
        net += deposits.get(day.on, Decimal(0))
        points.append(
            schemas.ValuePoint(on=day.on, value=_cents(day.value), net_deposits=cents(net))
        )
    return points


def _value(
    instrument_id: uuid.UUID,
    quantity: Decimal,
    on: date,
    currency: str,
    prices: PriceTable,
    rates: RateTable,
) -> Decimal:
    """In the account's currency, as a day's value counts it: nothing without a price or rate."""
    eur = prices.value_eur(instrument_id, quantity, on, rates)
    rate = rates.rate(currency, on)
    return Decimal(0) if eur is None or rate is None else eur * rate


def _fee(fill: FillMove, currency: str, rates: RateTable) -> Decimal:
    """The fill's taxes and fees in the account's currency, each a charge whatever its sign
    (Trading 212 sends them negative). One in a currency without a rate that day stays in the
    price."""
    total = Decimal(0)
    for amount, tax_currency in fill.taxes:
        if tax_currency in (None, currency):
            total += abs(amount)
            continue
        eur, rate = rates.to_eur(abs(amount), tax_currency, fill.on), rates.rate(currency, fill.on)
        if eur is not None and rate is not None:
            total += eur * rate
    return total


def _annual(over: Decimal, days: int) -> Decimal | None:
    if over <= -1:
        return None
    return Decimal((1 + float(over)) ** (YEAR / days) - 1)


def _rate(rate: Decimal | None) -> Decimal | None:
    if rate is None or not rate.is_finite() or abs(rate) > 10**9:
        return None
    return rate.quantize(RATE)


def _cents(amount: Decimal | None) -> Decimal | None:
    return None if amount is None else cents(amount)
