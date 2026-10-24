"""Value over time rebuilt from trades (ADR-0008): quantities and cash moved back from the
latest snapshot, holdings at each day's price, the gaps counted, and the check against the
broker. Pure functions, so no database."""

import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from hubnisio.finance.fx.convert import RateTable
from hubnisio.finance.insights.portfolio import FillMove, Portfolio, Rebuild, check
from hubnisio.finance.prices.table import InstrumentInfo, PriceTable

WORLD, ACME, PENCE = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
AS_OF = datetime(2026, 10, 20, 9, 0, tzinfo=UTC)
INSTRUMENTS = {
    WORLD: InstrumentInfo("XWLDm_EQ", "Test World ETF", "EUR"),
    ACME: InstrumentInfo("XACM_US_EQ", "Acme Test Inc", "USD"),
    PENCE: InstrumentInfo("XPNCl_EQ", None, "GBX"),
}
# Every day from 1 October: dollars at 2 to the euro; pounds at 0.5, so pence at 50.
DAYS = [date(2026, 10, 1) + timedelta(days=n) for n in range(20)]
RATES = RateTable(
    {
        "USD": [(day, Decimal(2)) for day in DAYS],
        "GBP": [(day, Decimal("0.5")) for day in DAYS],
    }
)


def at(day: int, hour: int = 12) -> datetime:
    return datetime(2026, 10, day, hour, tzinfo=UTC)


def buy(instrument: uuid.UUID, day: int, quantity: str, net: str, hour: int = 12) -> FillMove:
    return FillMove.of(instrument, at(day, hour), "BUY", Decimal(quantity), Decimal(net))


def sell(instrument: uuid.UUID, day: int, quantity: str, net: str) -> FillMove:
    """As Trading 212 sends a sell: the quantity negative, the net value positive."""
    return FillMove.of(instrument, at(day), "SELL", -Decimal(quantity), Decimal(net))


def portfolio(**changes: object) -> Portfolio:
    """Deposited 1000 on 1 October; bought 4 World for 400 on the 5th, sold 1 for 120 on the
    12th; bought 2 Acme for 300 on the 15th. Cash at the snapshot: 420; 3 World and 2 Acme."""
    base = Portfolio(
        account_id=uuid.uuid4(),
        currency="EUR",
        as_of=AS_OF,
        cash=Decimal(420),
        total_value=Decimal("940.00"),
        holdings={WORLD: Decimal(3), ACME: Decimal(2)},
        fills=[
            buy(WORLD, 5, "4", "400"),
            sell(WORLD, 12, "1", "120"),
            buy(ACME, 15, "2", "300"),
        ],
        movements={date(2026, 10, 1): Decimal(1000)},
    )
    for name, value in changes.items():
        setattr(base, name, value)
    return base


def prices(rows: dict[uuid.UUID, dict[int, str]]) -> PriceTable:
    return PriceTable(
        INSTRUMENTS,
        {
            instrument: [
                (date(2026, 10, day), Decimal(price)) for day, price in sorted(days.items())
            ]
            for instrument, days in rows.items()
        },
    )


EVERY_DAY = prices(
    {
        WORLD: {d: str(100 + d) for d in range(1, 21)},
        ACME: {d: "300" for d in range(1, 21)},  # dollars: 150 euros
    }
)


def values(p: Portfolio, table: PriceTable, start: int, end: int) -> dict[int, Decimal | None]:
    return {
        value.on.day: value.value
        for value in Rebuild(p).values(date(2026, 10, start), date(2026, 10, end), table, RATES)
    }


def test_quantities_and_cash_move_back_from_the_snapshot() -> None:
    by_day = values(portfolio(), EVERY_DAY, 1, 20)

    assert by_day[1] == 1000  # only the deposit
    assert by_day[5] == 600 + 4 * 105  # the buy took 400 cash for 4 shares
    assert by_day[12] == 720 + 3 * 112  # a sell's quantity comes negative: 1 share out, 120 in
    assert by_day[15] == 420 + 3 * 115 + 2 * 150  # Acme in dollars, at 2 to the euro
    assert by_day[20] == 420 + 3 * 120 + 300


def test_before_the_first_movement_the_account_is_empty_when_the_history_explains_it() -> None:
    rebuild = Rebuild(portfolio())
    (before,) = rebuild.values(date(2026, 9, 30), date(2026, 9, 30), EVERY_DAY, RATES)

    assert (rebuild.opening_cash, before.value, before.unpriced) == (0, 0, frozenset())
    assert set(rebuild.opening_quantities.values()) == {0}


def test_fills_after_the_snapshot_move_it_forward() -> None:
    later = buy(WORLD, 20, "1", "120", hour=15)  # the snapshot was read at 9:00 that day
    p = portfolio(fills=[*portfolio().fills, later])
    by_day = values(p, EVERY_DAY, 19, 20)

    assert by_day[19] == 420 + 3 * 119 + 300
    assert by_day[20] == 300 + 4 * 120 + 300
    assert Rebuild(p).opening_cash == 0


def test_a_day_uses_a_price_up_to_ten_days_old_and_leaves_out_what_has_none() -> None:
    sparse = prices({WORLD: {5: "100"}, ACME: {15: "300"}})
    by_value = {
        value.on.day: value
        for value in Rebuild(portfolio()).values(
            date(2026, 10, 14), date(2026, 10, 16), sparse, RATES
        )
    }

    # World's price from the 5th is 10 days old on the 15th, then too old: left out, counted.
    assert by_value[14].value == 720 + 3 * 100
    assert (by_value[15].value, by_value[15].unpriced) == (420 + 3 * 100 + 2 * 150, frozenset())
    assert by_value[16].unpriced == frozenset({WORLD})
    assert by_value[16].value == 420 + 2 * 150  # never at cost instead


def test_a_holding_without_an_exchange_rate_is_left_out_too() -> None:
    p = portfolio(holdings={WORLD: Decimal(3), ACME: Decimal(2), PENCE: Decimal(10)})
    table = prices({**{WORLD: {20: "120"}, ACME: {20: "300"}}, PENCE: {20: "250"}})
    (today,) = Rebuild(p).values(date(2026, 10, 20), date(2026, 10, 20), table, RATES)

    # 10 shares at 250 pence: 25 pounds, 50 euros at the pound's rate times 100.
    assert today.value == 420 + 360 + 300 + 50
    (unrated,) = Rebuild(p).values(
        date(2026, 10, 20), date(2026, 10, 20), table, RateTable({"GBP": []})
    )
    assert unrated.unpriced == frozenset({ACME, PENCE})


def test_an_account_in_another_currency_is_valued_in_it_and_in_euros() -> None:
    p = portfolio(currency="USD", cash=Decimal(840), movements={date(2026, 10, 1): Decimal(1420)})
    (today,) = Rebuild(p).values(date(2026, 10, 20), date(2026, 10, 20), EVERY_DAY, RATES)

    # Cash in dollars; World's 360 euros are 720 dollars; Acme 600 dollars.
    assert (today.value, today.eur) == (840 + 720 + 600, 420 + 360 + 300)


def test_the_check_matches_the_broker_when_the_history_explains_the_snapshot() -> None:
    result = check(portfolio(total_value=Decimal("1080.00")), EVERY_DAY, RATES)

    assert result.on == date(2026, 10, 20)
    assert (result.rebuilt_value, result.difference) == (Decimal("1080.00"), Decimal("0.00"))
    assert (result.unexplained_cash, result.unexplained, result.unpriced) == (0, [], [])


def test_the_check_reports_what_the_history_misses_and_what_has_no_price() -> None:
    # A 2-for-1 split the order history doesn't show, and a fee it doesn't either.
    p = portfolio(holdings={WORLD: Decimal(6), ACME: Decimal(2)}, cash=Decimal(415))
    table = prices({WORLD: {20: "60"}})
    result = check(p, table, RATES)

    assert result.unexplained_cash == -5
    assert [(item.ticker, item.name, item.quantity) for item in result.unexplained] == [
        ("XWLDm_EQ", "Test World ETF", 3)
    ]
    assert result.unpriced == ["Acme Test Inc"]
    assert result.rebuilt_value == 415 + 360  # Acme left out, never hidden
    assert result.difference == Decimal("775.00") - Decimal("940.00")


def test_the_first_day_is_the_first_movement() -> None:
    assert portfolio().first_day == date(2026, 10, 1)
    assert portfolio(movements={}).first_day == date(2026, 10, 5)
    assert portfolio(movements={}, fills=[]).first_day is None


def test_signs_come_from_the_side() -> None:
    bought = FillMove.of(WORLD, AS_OF, "BUY", Decimal(2), Decimal(-200))
    sold = FillMove.of(WORLD, AS_OF, "SELL", Decimal(2), Decimal(200))

    assert (bought.quantity, bought.cash) == (2, -200)
    assert (sold.quantity, sold.cash) == (-2, 200)
    assert (sold.on, AS_OF - timedelta(hours=9)) == (date(2026, 10, 20), at(20, 0))
