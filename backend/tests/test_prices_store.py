"""Keeping instrument prices (ADR-0008): the broker's own prices from trades and positions, the
daily source's closes on the days each instrument was held, finding its symbol there, and the
daily job and CLI."""

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal

import pytest
from households import Home
from portfolios import Trade, investment_account, new_instrument, set_prices
from sqlalchemy import delete, select
from yahoo import FakeYahoo, Listed

from hubnisio import cli
from hubnisio.core.db import get_sessionmaker
from hubnisio.core.models import Household
from hubnisio.finance import tasks
from hubnisio.finance.models import Instrument, InstrumentPrice, PriceSource
from hubnisio.finance.prices.store import (
    PriceRefresh,
    refresh_prices,
    set_symbol,
    store_broker_prices,
    ticker_symbol,
)

pytestmark = pytest.mark.anyio

# Relative to the real today, because the job and the CLI read the clock.
TODAY = datetime.now(UTC).date()


def ago(days: int) -> date:
    return TODAY - timedelta(days=days)


def daily(first: int, last: int, price: str) -> dict[date, Decimal]:
    """A close on every day from `first` days ago to `last` days ago."""
    return {ago(n): Decimal(price) for n in range(first, last - 1, -1)}


@pytest.fixture
async def home(home: Home) -> AsyncIterator[Home]:
    """Removed afterwards: every refresh looks at every instrument held anywhere."""
    yield home
    async with get_sessionmaker()() as session, session.begin():
        await session.execute(delete(Household).where(Household.id == home.owner.household_id))


async def prices_of(instrument: uuid.UUID) -> dict[date, tuple[Decimal, PriceSource]]:
    async with get_sessionmaker()() as session:
        rows = await session.execute(
            select(InstrumentPrice.on, InstrumentPrice.price, InstrumentPrice.source).where(
                InstrumentPrice.instrument_id == instrument
            )
        )
        return {on: (price, source) for on, price, source in rows}


async def symbol_of(instrument: uuid.UUID) -> tuple[str | None, bool]:
    async with get_sessionmaker()() as session:
        found = await session.get_one(Instrument, instrument)
        return found.price_symbol, found.price_symbol_by_hand


async def refresh(yahoo: FakeYahoo, since: date | None = None) -> PriceRefresh:
    async with yahoo.client() as client, get_sessionmaker()() as session, session.begin():
        return await refresh_prices(session, client, since=since, today=TODAY)


def test_a_tickers_format_gives_the_listing() -> None:
    assert ticker_symbol("XACM_US_EQ") == "XACM"
    assert ticker_symbol("BRK.B_US_EQ") == "BRK-B"
    assert ticker_symbol("XWLDm_EQ") == "XWLD.MI"
    assert ticker_symbol("XWLDd_EQ") == "XWLD.DE"
    assert ticker_symbol("XWLDl_EQ") == "XWLD.L"
    assert ticker_symbol("XWLD_EQ") is None  # no exchange letter
    assert ticker_symbol("XWLDz_EQ") is None  # one the hub doesn't know


async def test_broker_prices_take_the_latest_sync_then_the_latest_fill(home: Home) -> None:
    acme = await new_instrument()
    at = datetime.combine(ago(1), time(18), UTC)
    await investment_account(
        home,
        home.owner,
        as_of=at,
        cash="0",
        total_value="330",
        holdings={acme.id: ("3", "110")},
        trades=[
            Trade(acme.id, ago(10), "2", "90", "180"),
            Trade(acme.id, ago(1), "1", "105", "105"),
            Trade(acme.id, ago(5), "3", "0.01", "0", fill_type="STOCK_SPLIT"),
        ],
    )
    # A second account bought later the same day, at a later price.
    await investment_account(
        home,
        home.member,
        as_of=at,
        cash="0",
        total_value="0",
        trades=[Trade(acme.id, ago(10), "1", "95", "95", hour=15)],
    )
    async with get_sessionmaker()() as session, session.begin():
        assert await store_broker_prices(session, [acme.id]) == 2

    assert await prices_of(acme.id) == {
        ago(10): (Decimal(95), PriceSource.FILL),
        ago(1): (Decimal(110), PriceSource.TRADING212),  # a corporate action's isn't a price
    }


async def test_closes_are_found_and_stored_for_the_days_held(home: Home) -> None:
    # Trading 212 keeps a US stock's old ticker after a rename; the ISIN finds the new one.
    renamed = await new_instrument(currency="USD", kind="STOCK")
    old = ticker_symbol(renamed.ticker)
    # A Milan ETF, found from its ticker, and one whose ticker's listing is in another currency.
    milan = await new_instrument(exchange="m_EQ", kind="ETF")
    elsewhere = await new_instrument(exchange="d_EQ", kind="ETF")
    # Nothing near its own prices.
    unknown = await new_instrument(kind="ETF")
    await investment_account(
        home,
        home.owner,
        as_of=datetime.combine(TODAY, time(9), UTC),
        cash="0",
        total_value="0",
        holdings={milan.id: ("2", "51")},
        trades=[
            Trade(renamed.id, ago(30), "1", "200", "160"),
            Trade(renamed.id, ago(20), "-1", "210", "168", side="SELL"),
            Trade(milan.id, ago(15), "2", "49", "98"),
            Trade(elsewhere.id, ago(15), "1", "20", "20"),
            Trade(unknown.id, ago(15), "1", "20", "20"),
        ],
    )
    assert old is not None
    milan_symbol = ticker_symbol(milan.ticker) or ""
    yahoo = FakeYahoo(
        charts={
            old: Listed("USD", "ETF", daily(40, 1, "30")),  # another instrument now has it
            "XNEW": Listed("USD", "EQUITY", daily(40, 0, "205")),
            milan_symbol: Listed("EUR", "ETF", daily(40, 0, "50")),
            ticker_symbol(elsewhere.ticker) or "": Listed("USD", "ETF", daily(40, 0, "22")),
            "XELS.SG": Listed("EUR", "ETF", daily(40, 0, "21")),
            "XFAR": Listed("EUR", "ETF", daily(40, 0, "90")),
        },
        searches={
            renamed.isin or "": ["XNEW.DE", "XNEW"],
            elsewhere.isin or "": ["XELS.SG"],
            unknown.isin or "": ["XFAR"],
        },
    )

    result = await refresh(yahoo)

    assert result.found == {
        renamed.ticker: "XNEW",
        milan.ticker: milan_symbol,
        elsewhere.ticker: "XELS.SG",
    }
    assert unknown.ticker in result.unmapped
    assert unknown.ticker not in result.failed
    # The renamed stock, held from its buy to its sale: closes in between, over the fills' prices.
    renamed_prices = await prices_of(renamed.id)
    assert set(renamed_prices) == {ago(n) for n in range(30, 19, -1)}
    assert set(renamed_prices.values()) == {(Decimal(205), PriceSource.YAHOO)}
    # Still held: up to yesterday's close, and today the latest sync's price.
    milan_prices = await prices_of(milan.id)
    assert min(milan_prices) == ago(15)
    assert milan_prices[ago(1)] == (Decimal(50), PriceSource.YAHOO)
    assert milan_prices[TODAY] == (Decimal(51), PriceSource.TRADING212)
    assert await prices_of(unknown.id) == {ago(15): (Decimal(20), PriceSource.FILL)}
    assert await symbol_of(renamed.id) == ("XNEW", False)

    # The next run asks only for what's missing: nothing until today's close is final, and
    # nothing for what was sold. What has no symbol is looked for again.
    yahoo.requests.clear()
    result = await refresh(yahoo)
    assert not {milan.ticker, renamed.ticker} & set(result.written)
    asked = {symbol for symbol, _ in yahoo.charted()}
    assert not {milan_symbol, "XNEW"} & asked
    assert "XFAR" in asked


async def test_a_symbol_set_by_hand_is_kept_and_must_be_in_the_instruments_currency(
    home: Home,
) -> None:
    acme = await new_instrument(kind="STOCK")
    await investment_account(
        home,
        home.owner,
        as_of=datetime.combine(TODAY, time(9), UTC),
        cash="0",
        total_value="0",
        holdings={acme.id: ("1", "10")},
        trades=[Trade(acme.id, ago(5), "1", "10", "10")],
    )
    yahoo = FakeYahoo(
        charts={
            "XHAND": Listed("EUR", "EQUITY", daily(5, 0, "11")),
            "XDOLLAR": Listed("USD", "EQUITY", daily(5, 0, "12")),
        }
    )
    async with get_sessionmaker()() as session, session.begin():
        assert await set_symbol(session, acme.ticker, "XHAND")
        assert not await set_symbol(session, "XNOPE_US_EQ", "XHAND")

    await refresh(yahoo)
    assert (await prices_of(acme.id))[ago(1)] == (Decimal(11), PriceSource.YAHOO)
    assert await symbol_of(acme.id) == ("XHAND", True)

    # Another symbol: the old one's closes go, the fills' prices come back.
    async with get_sessionmaker()() as session, session.begin():
        await set_symbol(session, acme.ticker, "XDOLLAR")
    assert (await prices_of(acme.id))[ago(5)] == (Decimal(10), PriceSource.FILL)
    result = await refresh(yahoo)
    assert result.failed[acme.ticker] == "XDOLLAR is quoted in USD, not EUR"
    assert await symbol_of(acme.id) == ("XDOLLAR", True)  # kept: the user set it

    # Yahoo dropping a symbol found automatically: it's looked for again next time.
    async with get_sessionmaker()() as session, session.begin():
        await set_symbol(session, acme.ticker, None)
        found = await session.get_one(Instrument, acme.id)
        found.price_symbol = "XGONE"
    result = await refresh(yahoo, since=ago(5))
    assert result.failed[acme.ticker] == "Yahoo has no XGONE any more"
    assert await symbol_of(acme.id) == (None, False)


async def test_the_cli_backfills_and_reports(
    home: Home, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    acme = await new_instrument(kind="STOCK")
    await investment_account(
        home,
        home.owner,
        as_of=datetime.combine(TODAY, time(9), UTC),
        cash="0",
        total_value="0",
        holdings={acme.id: ("1", "10")},
        trades=[Trade(acme.id, ago(3), "1", "10", "10")],
    )
    await set_prices(acme.id, {ago(2): "9.5"})  # a close stored before, now different
    yahoo = FakeYahoo(
        charts={ticker_symbol(acme.ticker) or "": Listed("EUR", "EQUITY", daily(3, 0, "10.5"))}
    )
    monkeypatch.setattr(cli, "PriceClient", yahoo.client)

    assert await cli.prices_backfill(None) in (0, 1)  # other tests' instruments may lack one

    output = capsys.readouterr().out
    assert f"{acme.ticker}: found as {ticker_symbol(acme.ticker)}." in output
    assert f"{acme.ticker}: 3 closes written." in output  # the changed one included
    assert "Stored yahoo:" in output
    assert (await prices_of(acme.id))[ago(2)] == (Decimal("10.5"), PriceSource.YAHOO)

    assert await cli.prices_symbol(acme.ticker, "XNOPE") in (0, 1)
    assert f"{acme.ticker}: symbol set to XNOPE." in capsys.readouterr().out
    assert await cli.prices_symbol("XNOPE_US_EQ", None) == 1


async def test_the_daily_job_keeps_what_it_fetched_and_fails_on_a_failure(
    home: Home, monkeypatch: pytest.MonkeyPatch
) -> None:
    acme = await new_instrument(kind="STOCK")
    await investment_account(
        home,
        home.owner,
        as_of=datetime.combine(TODAY, time(9), UTC),
        cash="0",
        total_value="0",
        holdings={acme.id: ("1", "10")},
        trades=[Trade(acme.id, ago(3), "1", "10", "10")],
    )
    yahoo = FakeYahoo(down=True)
    monkeypatch.setattr(tasks, "PriceClient", yahoo.client)

    with pytest.raises(RuntimeError, match=f"not fetched for .*{acme.ticker}"):
        await tasks.fetch_prices(timestamp=0)
    assert set((await prices_of(acme.id)).values()) == {
        (Decimal(10), PriceSource.FILL),
        (Decimal(10), PriceSource.TRADING212),
    }

    yahoo.down = False
    yahoo.charts = {ticker_symbol(acme.ticker) or "": Listed("EUR", "EQUITY", daily(3, 0, "10.5"))}
    await tasks.fetch_prices(timestamp=0)
    assert (await prices_of(acme.id))[ago(1)] == (Decimal("10.5"), PriceSource.YAHOO)
