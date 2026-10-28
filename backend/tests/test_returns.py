"""Returns on an investment account (ADR-0008, "Returns"): the breakdown adds up to the change in
value less net deposits, price movements split by average cost, the time-weighted return
chained across deposits and withdrawals, the money-weighted one as an XIRR, and the edge cases.
Pure functions, so no database."""

import itertools
import uuid
from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from hubnisio.finance import schemas
from hubnisio.finance.fx.convert import RateTable
from hubnisio.finance.insights.portfolio import FillMove, Portfolio
from hubnisio.finance.insights.returns import (
    ReturnsInputs,
    account_returns,
    add_movement,
    compute_returns,
    period,
    xirr,
)
from hubnisio.finance.prices.table import InstrumentInfo, PriceTable

WORLD, ACME = uuid.uuid4(), uuid.uuid4()
INSTRUMENTS = {
    WORLD: InstrumentInfo("XWLDm_EQ", "Test World ETF", "EUR"),
    ACME: InstrumentInfo("XACM_US_EQ", "Acme Test Inc", "USD"),
}
DEPOSIT, WITHDRAW, FEE = "T212_DEPOSIT", "T212_WITHDRAW", "T212_FEE"
INTEREST, DIVIDEND = "T212_INTEREST_ON_FREE_CASH", "T212_DIVIDEND"
# Dollars at 2 to the euro, every day of October and November.
RATES = RateTable({"USD": [(date(2026, 10, 1) + timedelta(days=n), Decimal(2)) for n in range(61)]})


def day(n: int) -> date:
    return date(2026, 10, n)


def trade(
    instrument: uuid.UUID,
    on: int,
    quantity: str,
    net: str,
    tax: str = "0",
    tax_currency: str = "EUR",
) -> FillMove:
    """A buy, or a sell when `quantity` is negative, as Trading 212 sends them: the net value
    positive both ways, fees included, and the taxes negative."""
    side = "SELL" if Decimal(quantity) < 0 else "BUY"
    taxes = [{"amount": tax, "currency": tax_currency}] if Decimal(tax) else []
    filled_at = datetime(2026, 10, on, 12, tzinfo=UTC)
    return FillMove.of(instrument, filled_at, side, Decimal(quantity), Decimal(net), taxes)


def account(
    fills: list[FillMove], movements: list[tuple[int, str | None, str]], as_of: int
) -> ReturnsInputs:
    """An account whose latest snapshot, on day `as_of`, holds what the fills and movements
    (day, bank code, amount) add up to: so it explains its whole history."""
    portfolio = Portfolio(
        account_id=uuid.uuid4(),
        currency="EUR",
        as_of=datetime(2026, 10, as_of, 23, tzinfo=UTC),
        cash=Decimal(0),
        total_value=Decimal(0),
        holdings={},
        fills=fills,
    )
    inputs = ReturnsInputs(portfolio.account_id, "Trading 212 EUR", "EUR", portfolio)
    for on, code, amount in movements:
        portfolio.movements[day(on)] = portfolio.movements.get(day(on), Decimal(0)) + Decimal(
            amount
        )
        add_movement(inputs, day(on), code, Decimal(amount) > 0, Decimal(amount))
    portfolio.cash = sum(portfolio.movements.values(), Decimal(0)) + sum(
        (fill.cash for fill in fills), Decimal(0)
    )
    holdings: dict[uuid.UUID, Decimal] = defaultdict(Decimal)
    for fill in fills:
        holdings[fill.instrument_id] += fill.quantity
    portfolio.holdings = {i: q for i, q in holdings.items() if q}
    return inputs


def prices(rows: dict[uuid.UUID, dict[int, str]]) -> PriceTable:
    return PriceTable(
        INSTRUMENTS,
        {
            instrument: [(day(on), Decimal(price)) for on, price in sorted(days.items())]
            for instrument, days in rows.items()
        },
    )


def scenario() -> ReturnsInputs:
    """Deposited 1000 on the 1st; bought 10 World for 500.20 (a 0.20 fee) on the 2nd;
    deposited 500 on the 4th; sold 5 for 299.70 on the 5th, with a fee of 0.60 dollars (0.30
    euros); withdrew 300 on the 6th. Then 5 World and 999.50 cash."""
    return account(
        [trade(WORLD, 2, "10", "500.20", "-0.20"), trade(WORLD, 5, "-5", "299.70", "-0.60", "USD")],
        [(1, DEPOSIT, "1000"), (4, DEPOSIT, "500"), (6, WITHDRAW, "-300")],
        as_of=6,
    )


SCENARIO_PRICES = prices({WORLD: {2: "50", 3: "55", 4: "60", 5: "60", 6: "66"}})


def returns(
    inputs: ReturnsInputs, start: int, end: int, table: PriceTable = SCENARIO_PRICES
) -> schemas.InvestmentReturns:
    return account_returns(inputs, table, RATES, (day(start), day(end)))


def parts(breakdown: schemas.ReturnsBreakdown | None) -> Decimal:
    assert breakdown is not None
    return (
        breakdown.unrealised
        + breakdown.realised
        + breakdown.dividends
        + breakdown.interest
        + breakdown.fees
        + breakdown.other
    )


def test_the_breakdown_splits_the_result_by_average_cost() -> None:
    result = returns(scenario(), 1, 6)

    assert (result.start_value, result.end_value) == (Decimal("0.00"), Decimal("1329.50"))
    assert (result.deposits, result.withdrawals, result.net_deposits) == (
        Decimal("1500.00"),
        Decimal("-300.00"),
        Decimal("1200.00"),
    )
    # Cost 500 for 10 (the fee apart); sold 5 for 300: 250 of the cost, so 50 realised. The 5
    # left cost 250 and are worth 330.
    assert result.breakdown == schemas.ReturnsBreakdown(
        unrealised=Decimal("80.00"),
        realised=Decimal("50.00"),
        dividends=Decimal("0.00"),
        interest=Decimal("0.00"),
        fees=Decimal("-0.50"),
        other=Decimal("0.00"),
        total=Decimal("129.50"),
    )

    # From the 4th, what's held costs its value on the 3rd: 10 at 55.
    later = returns(scenario(), 4, 6)
    assert later.start_value == Decimal("1049.80")
    assert later.breakdown == schemas.ReturnsBreakdown(
        unrealised=Decimal("55.00"),
        realised=Decimal("25.00"),
        dividends=Decimal("0.00"),
        interest=Decimal("0.00"),
        fees=Decimal("-0.30"),
        other=Decimal("0.00"),
        total=Decimal("79.70"),
    )


def test_the_parts_add_up_to_the_change_in_value_less_net_deposits() -> None:
    """Over every period, with prices to fractions of a cent, dividends, interest, a fee on its
    own and a movement of another type."""
    inputs = account(
        [
            trade(WORLD, 2, "3.3333", "500.27", "-0.27"),
            trade(ACME, 3, "2.5", "200.00", "-0.31", "USD"),
            trade(WORLD, 5, "-1.1111", "190.13", "-0.12"),
            trade(ACME, 7, "-2.5", "260.00"),
        ],
        [
            (1, DEPOSIT, "1000"),
            (4, DIVIDEND, "1.23"),
            (5, INTEREST, "0.07"),
            (6, FEE, "-2.50"),
            (6, None, "3.00"),
            (7, WITHDRAW, "-250"),
            (8, DEPOSIT, "100"),
        ],
        as_of=8,
    )
    table = prices(
        {
            WORLD: {n: str(Decimal("150.1234") + Decimal("7.7777") * n) for n in range(1, 9)},
            ACME: {n: str(Decimal("160.4321") + Decimal("3.3333") * n) for n in range(1, 9)},
        }
    )
    for start, end in itertools.combinations_with_replacement(range(1, 9), 2):
        result = returns(inputs, start, end, table)
        assert result.breakdown is not None and result.start_value is not None
        assert result.end_value is not None
        expected = result.end_value - result.start_value - result.net_deposits
        assert result.breakdown.total == expected, (start, end)
        assert parts(result.breakdown) == expected, (start, end)
    whole = returns(inputs, 1, 8, table).breakdown
    assert whole is not None
    assert (whole.dividends, whole.interest, whole.other) == (
        Decimal("1.23"),
        Decimal("0.07"),
        Decimal("3.00"),
    )
    # 2.50 on its own, and on trades 0.27, 0.31 dollars (0.155 euros) and 0.12.
    assert whole.fees == Decimal("-3.04")


def test_the_time_weighted_return_chains_each_days_return() -> None:
    """Money in counts from the start of its day, money out at its end."""
    daily = [
        Decimal(0),  # 1: deposited 1000, all cash
        Decimal("-0.20") / 1000,  # 2: the fee
        Decimal(50) / Decimal("999.80"),  # 3: 10 shares up 5
        Decimal(50) / (Decimal("1049.80") + 500),  # 4: deposited 500; the shares up 5 again
        Decimal("-0.30") / Decimal("1599.80"),  # 5: sold 5, a fee
        Decimal(30) / Decimal("1599.50"),  # 6: withdrew 300; 5 shares up 6
    ]
    growth = Decimal(1)
    for rate in daily:
        growth *= 1 + rate

    result = returns(scenario(), 1, 6)

    assert result.time_weighted == (growth - 1).quantize(Decimal("0.0001"))
    assert result.time_weighted_gap is None
    assert result.time_weighted_annual is None  # a period under a year


def test_the_money_weighted_return_is_the_rate_that_values_the_flows_at_nothing() -> None:
    assert xirr([(0, -1000), (1, 1100)]) == pytest.approx(0.10)
    assert xirr([(0, -1000), (0.5, 1100)]) == pytest.approx(0.21)
    assert xirr([(0, -1000), (1, 500), (1, 400)]) == pytest.approx(-0.10)

    result = returns(scenario(), 1, 6)
    # In: 1000 on the 1st, 500 on the 4th; out: 300 and the 1329.50 left, on the 6th.
    assert result.money_weighted is not None and result.money_weighted_gap is None
    rate = (1 + float(result.money_weighted)) ** (365 / 5) - 1  # a year's, from 5 days
    worth = -1000 - 500 / (1 + rate) ** (3 / 365) + 1629.50 / (1 + rate) ** (5 / 365)
    assert worth == pytest.approx(0, abs=0.1)


def test_a_year_or_more_has_a_years_equivalent() -> None:
    """1000 in on 1 October 2025, and 100 of interest a day short of a year later."""
    inputs = account([], [(1, DEPOSIT, "1000")], as_of=1)
    portfolio = inputs.portfolio
    assert portfolio is not None
    start, end = date(2025, 10, 1), date(2026, 9, 30)
    portfolio.movements = {start: Decimal(1000), end: Decimal(100)}
    portfolio.cash = Decimal(1100)
    inputs.movements = {(start, "deposits"): Decimal(1000), (end, "interest"): Decimal(100)}
    empty = PriceTable({}, {})

    year = account_returns(inputs, empty, RATES, (start, end))  # 365 days
    assert year.breakdown is not None and year.breakdown.interest == Decimal("100.00")
    assert (year.time_weighted, year.time_weighted_annual) == (
        Decimal("0.1000"),
        Decimal("0.1000"),
    )
    # The money was in for 364 days of the 365.
    assert year.money_weighted == Decimal("0.1000")
    assert year.money_weighted_annual == Decimal("0.1003")

    shorter = account_returns(inputs, empty, RATES, (start, end - timedelta(days=1)))
    assert (shorter.time_weighted_annual, shorter.money_weighted_annual) == (None, None)


def test_everything_sold() -> None:
    """The rest sold on the 7th for 349.65 (a 0.35 fee): nothing held, so no unrealised
    result, and the cash still counts. Then all of it withdrawn on the 8th."""
    inputs = scenario()
    sold = account(
        [
            *(inputs.portfolio.fills if inputs.portfolio else []),
            trade(WORLD, 7, "-5", "349.65", "-0.35"),
        ],
        [
            (1, DEPOSIT, "1000"),
            (4, DEPOSIT, "500"),
            (6, WITHDRAW, "-300"),
            (8, WITHDRAW, "-1349.15"),
        ],
        as_of=8,
    )
    table = prices({WORLD: {2: "50", 3: "55", 4: "60", 5: "60", 6: "66", 7: "70"}})

    cash_left = returns(sold, 1, 7, table)
    assert cash_left.end_value == Decimal("1349.15")
    assert cash_left.breakdown is not None
    assert (cash_left.breakdown.unrealised, cash_left.breakdown.realised) == (
        Decimal("0.00"),
        Decimal("150.00"),  # 50, then 350 for the 5 that cost 250
    )
    assert cash_left.breakdown.fees == Decimal("-0.85")
    assert cash_left.time_weighted is not None and cash_left.money_weighted is not None

    emptied = returns(sold, 1, 8, table)
    assert emptied.end_value == Decimal("0.00")
    assert emptied.net_deposits == Decimal("-149.15")
    assert emptied.breakdown is not None and emptied.breakdown.total == Decimal("149.15")
    assert parts(emptied.breakdown) == emptied.breakdown.total
    assert emptied.time_weighted == cash_left.time_weighted  # the withdrawal earns nothing
    assert emptied.money_weighted is not None and emptied.money_weighted > 0


def test_a_period_with_no_money_in() -> None:
    sold = account(
        [trade(WORLD, 2, "1", "50"), trade(WORLD, 3, "-1", "55")],
        [(1, DEPOSIT, "50"), (4, WITHDRAW, "-55")],
        as_of=4,
    )
    table = prices({WORLD: {2: "50", 3: "55"}})

    after = returns(sold, 5, 9, table)

    assert (after.start_value, after.end_value, after.net_deposits) == (
        Decimal("0.00"),
        Decimal("0.00"),
        Decimal("0.00"),
    )
    assert after.breakdown is not None and after.breakdown.total == 0
    assert (after.time_weighted, after.time_weighted_gap) == (None, schemas.ReturnGap.NO_MONEY)
    assert (after.money_weighted, after.money_weighted_gap) == (None, schemas.ReturnGap.NO_MONEY)
    # The value against net deposits: 5 more than was put in, since the 4th.
    assert {(p.value, p.net_deposits) for p in after.points} == {
        (Decimal("0.00"), Decimal("-5.00"))
    }


def test_a_money_weighted_return_that_no_rate_fits() -> None:
    """In 100, out 250, in 160, on three days, and nothing left: no rate makes those worth
    nothing together."""
    assert xirr([(0, -100), (1 / 365, 250), (2 / 365, -160)]) is None
    assert xirr([(0, -100), (1, -50)]) is None  # all one way
    inputs = account(
        [trade(WORLD, 1, "1", "100"), trade(WORLD, 2, "-1", "250"), trade(WORLD, 3, "1", "160")],
        [(1, DEPOSIT, "100"), (2, WITHDRAW, "-250"), (3, DEPOSIT, "160")],
        as_of=3,
    )

    result = returns(inputs, 1, 3, prices({WORLD: {1: "100", 2: "250", 3: "0"}}))

    assert (result.money_weighted, result.money_weighted_gap) == (
        None,
        schemas.ReturnGap.NO_SOLUTION,
    )
    assert result.time_weighted is not None  # chained all the same: -100% on the 3rd
    assert result.breakdown is not None and parts(result.breakdown) == result.breakdown.total


def test_holding_days_without_a_price_are_counted() -> None:
    """World's only price is the 1st's, good for 10 days: the 12th to the 15th have none."""
    inputs = account([trade(WORLD, 1, "1", "100")], [(1, DEPOSIT, "100")], as_of=15)

    result = returns(inputs, 1, 15, prices({WORLD: {1: "100"}}))

    assert result.unpriced == 4
    assert [p.value for p in result.points[10:]] == [Decimal("100.00")] + [Decimal("0.00")] * 4
    # Left out of the end value, so its cost counts against the result: shown, not hidden.
    assert result.breakdown is not None and result.breakdown.unrealised == Decimal("-100.00")


def test_value_against_net_deposits_since_the_account_opened() -> None:
    result = returns(scenario(), 3, 6)

    assert [(p.on, p.value, p.net_deposits) for p in result.points] == [
        (day(3), Decimal("1049.80"), Decimal("1000.00")),
        (day(4), Decimal("1599.80"), Decimal("1500.00")),
        (day(5), Decimal("1599.50"), Decimal("1500.00")),
        (day(6), Decimal("1329.50"), Decimal("1200.00")),
    ]


def test_the_period_runs_from_the_first_movement_to_today() -> None:
    inputs = scenario()
    today = day(20)

    assert period(inputs, today, None, None) == (day(1), today)
    assert period(inputs, today, date(2026, 1, 1), date(2027, 1, 1)) == (day(1), today)
    assert period(inputs, today, day(3), day(5)) == (day(3), day(5))
    assert period(inputs, today, None, date(2026, 9, 1)) == (date(2026, 9, 1),) * 2

    never = ReturnsInputs(uuid.uuid4(), "Trading 212 EUR", "EUR")
    out = compute_returns([never], SCENARIO_PRICES, RATES, today)
    (shown,) = out.accounts
    assert (shown.date_from, shown.breakdown, shown.points) == (None, None, [])
    assert shown.money_weighted_gap == schemas.ReturnGap.NO_MONEY
