"""Keeping `instrument_prices` filled (ADR-0008, "Value over time"). Callers commit.

- **The broker's prices:** each trade's price on its day (source `fill`) and each position's
  current price on its sync's day (`trading212`), rebuilt from the stored fills and snapshots
  after every sync, by renormalize and by every refresh.
- **The daily source's closes** (`yahoo`) on every day an instrument was held, from its first
  fill to its last, or to yesterday while it's still held: today's close isn't final yet.

One row per instrument and day. A close wins, as the day's value; then the latest sync's
price, then the latest fill's. The broker's prices cover what the source lacks: today, and
instruments it doesn't list.

An instrument's symbol at the source is found once, then kept: from Trading 212's ticker for a
European listing (its exchange is the ticker's last letter), else from the ISIN, which follows
renames that Trading 212's US tickers don't (FB is META's). A candidate counts only if it's
quoted in the instrument's currency, is the same type, and its closes agree with the broker's
prices on the same days. `cli prices-symbol` sets one by hand when nothing maps.
"""

import logging
import uuid
from collections.abc import Collection, Mapping
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import (
    ColumnElement,
    Date,
    Integer,
    SQLColumnExpression,
    cast,
    delete,
    func,
    literal,
    or_,
    select,
    union_all,
)
from sqlalchemy.dialects.postgresql import distinct_on, insert
from sqlalchemy.ext.asyncio import AsyncSession

from hubnisio.finance.models import (
    Fill,
    HoldingSnapshot,
    Instrument,
    InstrumentPrice,
    PortfolioSnapshot,
    PriceSource,
)
from hubnisio.finance.prices.sources import Chart, PriceClient, PriceSourceError

logger = logging.getLogger(__name__)

US_TICKER = "_US_EQ"
# The letter ending a European Trading 212 ticker's symbol (VUSAl_EQ) names its exchange; this
# is Yahoo's suffix for it. Xetra and Milan are confirmed by instruments traded; a wrong guess
# fails the checks below and the ISIN is tried instead.
EXCHANGE_SUFFIXES = {"l": ".L", "d": ".DE", "m": ".MI", "p": ".PA", "a": ".AS"}
# Trading 212's types against Yahoo's; others aren't checked.
TYPES = {"STOCK": {"EQUITY"}, "ETF": {"ETF"}}
# A candidate's closes against the broker's prices on the same days: the median ratio must be
# within these. Wide enough for a day's moves; a different instrument is rarely this close.
RATIO_RANGE = (Decimal("0.8"), Decimal("1.25"))
MAX_CANDIDATES = 5
_PRECEDENCE = {PriceSource.TRADING212: 1, PriceSource.FILL: 2}
_INSERT_CHUNK = 5000


@dataclass(frozen=True, slots=True)
class Held:
    instrument: Instrument
    first: date  # the day of its first fill or position
    last: date  # of its last one; today while a latest snapshot holds it


@dataclass
class PriceRefresh:
    written: dict[str, int] = field(default_factory=dict[str, int])  # ticker → closes written
    found: dict[str, str] = field(default_factory=dict[str, str])  # ticker → symbol found now
    unmapped: list[str] = field(default_factory=list[str])  # tickers without a symbol
    failed: dict[str, str] = field(default_factory=dict[str, str])  # ticker → what went wrong


@dataclass(frozen=True, slots=True)
class PriceSummary:
    source: PriceSource
    instruments: int
    rows: int
    first: date
    last: date


def _utc_day(column: SQLColumnExpression[datetime]) -> ColumnElement[date]:
    return cast(func.timezone("UTC", column), Date)


def _source(source: PriceSource) -> ColumnElement[PriceSource]:
    return cast(literal(source.value), InstrumentPrice.__table__.c.source.type)


async def account_instruments(session: AsyncSession, account_id: uuid.UUID) -> set[uuid.UUID]:
    """The instruments an account has traded or held."""
    return set(
        await session.scalars(
            union_all(
                select(Fill.instrument_id).where(Fill.account_id == account_id),
                select(HoldingSnapshot.instrument_id).where(
                    HoldingSnapshot.account_id == account_id
                ),
            )
        )
    )


async def store_broker_prices(
    session: AsyncSession, instrument_ids: Collection[uuid.UUID] | None = None
) -> int:
    """Rebuild the `fill` and `trading212` prices of the instruments (default: all) from every
    account's fills and snapshots, under any close already stored. Returns the rows written."""
    broker = (PriceSource.FILL, PriceSource.TRADING212)
    cleared = delete(InstrumentPrice).where(InstrumentPrice.source.in_(broker))
    fills = select(
        Fill.instrument_id.label("instrument_id"),
        _utc_day(Fill.filled_at).label("on"),
        Fill.price.label("price"),
        _source(PriceSource.FILL).label("source"),
        literal(_PRECEDENCE[PriceSource.FILL], Integer).label("precedence"),
        Fill.filled_at.label("at"),
    ).where(Fill.fill_type == "TRADE", Fill.price > 0)  # a corporate action's isn't a price
    positions = (
        select(
            HoldingSnapshot.instrument_id,
            _utc_day(PortfolioSnapshot.fetched_at),
            HoldingSnapshot.current_price,
            _source(PriceSource.TRADING212),
            literal(_PRECEDENCE[PriceSource.TRADING212], Integer),
            PortfolioSnapshot.fetched_at,
        )
        .join(PortfolioSnapshot, PortfolioSnapshot.id == HoldingSnapshot.portfolio_snapshot_id)
        .where(HoldingSnapshot.current_price > 0)
    )
    if instrument_ids is not None:
        ids = list(instrument_ids)
        if not ids:
            return 0
        cleared = cleared.where(InstrumentPrice.instrument_id.in_(ids))
        fills = fills.where(Fill.instrument_id.in_(ids))
        positions = positions.where(HoldingSnapshot.instrument_id.in_(ids))
    await session.execute(cleared)
    candidates = union_all(fills, positions).subquery()
    best = (
        select(candidates.c.instrument_id, candidates.c.on, candidates.c.price, candidates.c.source)
        .order_by(
            candidates.c.instrument_id,
            candidates.c.on,
            candidates.c.precedence,
            candidates.c.at.desc(),
        )
        .ext(distinct_on(candidates.c.instrument_id, candidates.c.on))
    )
    statement = (
        insert(InstrumentPrice)
        .from_select(["instrument_id", "on", "price", "source"], best)
        .on_conflict_do_nothing(index_elements=["instrument_id", "on"])
        .returning(InstrumentPrice.on)
    )
    return len((await session.execute(statement)).all())


async def held_spans(session: AsyncSession, today: date) -> list[Held]:
    """Every instrument any account has traded or held, with the days it was held between."""
    days = union_all(
        select(Fill.instrument_id.label("instrument_id"), _utc_day(Fill.filled_at).label("day")),
        select(HoldingSnapshot.instrument_id, _utc_day(PortfolioSnapshot.fetched_at)).join(
            PortfolioSnapshot, PortfolioSnapshot.id == HoldingSnapshot.portfolio_snapshot_id
        ),
    ).subquery()
    latest = (
        select(PortfolioSnapshot.id)
        .order_by(
            PortfolioSnapshot.account_id,
            PortfolioSnapshot.fetched_at.desc(),
            PortfolioSnapshot.id.desc(),
        )
        .ext(distinct_on(PortfolioSnapshot.account_id))
    )
    held_now = set(
        await session.scalars(
            select(HoldingSnapshot.instrument_id).where(
                HoldingSnapshot.portfolio_snapshot_id.in_(latest), HoldingSnapshot.quantity != 0
            )
        )
    )
    rows = await session.execute(
        select(Instrument, func.min(days.c.day), func.max(days.c.day))
        .join(days, days.c.instrument_id == Instrument.id)
        .group_by(Instrument.id)
        .order_by(Instrument.ticker)
    )
    return [
        Held(instrument, first, today if instrument.id in held_now else last)
        for instrument, first, last in rows
    ]


def ticker_symbol(ticker: str) -> str | None:
    """Yahoo's symbol for the listing a Trading 212 ticker names, when its format says."""
    if ticker.endswith(US_TICKER):
        return ticker.removesuffix(US_TICKER).replace(".", "-") or None
    stem = ticker.removesuffix("_EQ")
    if stem != ticker and len(stem) > 1 and (suffix := EXCHANGE_SUFFIXES.get(stem[-1])):
        return stem[:-1] + suffix
    return None


def fits(instrument: Instrument, chart: Chart, known: Mapping[date, Decimal]) -> bool:
    """Whether the chart can be the instrument's: its currency, its type, and its closes
    against the broker's prices on the same days."""
    if not chart.closes:
        return False
    if instrument.currency is not None and chart.currency != instrument.currency:
        return False
    if (types := TYPES.get(instrument.type or "")) is not None and chart.type not in types:
        return False
    ratios = sorted(
        chart.closes[day] / price for day, price in known.items() if day in chart.closes
    )
    if ratios:
        low, high = RATIO_RANGE
        return low <= ratios[len(ratios) // 2] <= high
    return True


async def find_symbol(
    client: PriceClient, instrument: Instrument, since: date, known: Mapping[date, Decimal]
) -> Chart | None:
    """The chart, from `since`, of the first candidate symbol that fits; None if none does."""
    tried: set[str] = set()

    async def first_fit(symbols: list[str]) -> Chart | None:
        for symbol in symbols:
            if symbol in tried or len(tried) >= MAX_CANDIDATES:
                continue
            tried.add(symbol)
            chart = await client.chart(symbol, since)
            if chart is not None and fits(instrument, chart, known):
                return chart
        return None

    derived = ticker_symbol(instrument.ticker)
    us = instrument.ticker.endswith(US_TICKER)
    if derived is not None and not us and (chart := await first_fit([derived])) is not None:
        return chart
    listed = (
        [listing.symbol for listing in await client.search(instrument.isin)]
        if (instrument.isin)
        else []
    )
    if us:  # the US listing, under its current symbol; then the ticker's own
        listed = [symbol for symbol in listed if "." not in symbol]
        listed += [derived] if derived is not None else []
    return await first_fit(listed)


async def refresh_prices(
    session: AsyncSession,
    client: PriceClient,
    *,
    since: date | None = None,
    today: date | None = None,
) -> PriceRefresh:
    """Rebuild the broker's prices, then fetch the closes that are missing.

    Without `since`, each instrument continues after its newest stored close; one with none
    starts at its first day held. With `since`, every instrument is checked from that day (or
    its first day held, if later) and changed closes are written. Safe to repeat.
    """
    today = today or datetime.now(UTC).date()
    await store_broker_prices(session)
    newest: dict[uuid.UUID, date] = {
        instrument_id: on
        for instrument_id, on in await session.execute(
            select(InstrumentPrice.instrument_id, func.max(InstrumentPrice.on))
            .where(InstrumentPrice.source == PriceSource.YAHOO)
            .group_by(InstrumentPrice.instrument_id)
        )
    }
    result = PriceRefresh()
    for held in await held_spans(session, today):
        instrument, ticker = held.instrument, held.instrument.ticker
        last = min(held.last, today - timedelta(days=1))
        if since is not None:
            start = max(since, held.first)
        elif instrument.id in newest:
            start = newest[instrument.id] + timedelta(days=1)
        else:
            start = held.first
        if start > last:
            continue
        try:
            chart = await _chart(session, client, instrument, held, start, result)
        except PriceSourceError as exc:
            result.failed[ticker] = str(exc)
            continue
        if chart is None:
            continue
        written = await _upsert(
            session, instrument.id, {d: p for d, p in chart.closes.items() if start <= d <= last}
        )
        if written:
            result.written[ticker] = written
        logger.info("%s (%s) from %s: %d closes written.", ticker, chart.symbol, start, written)
    return result


async def _chart(
    session: AsyncSession,
    client: PriceClient,
    instrument: Instrument,
    held: Held,
    start: date,
    result: PriceRefresh,
) -> Chart | None:
    """The instrument's chart from `start`, finding its symbol first if it has none. None (and
    why, in `result`) when there's nothing to store."""
    ticker, symbol = instrument.ticker, instrument.price_symbol
    if symbol is None:
        known = await _broker_prices(session, instrument.id)
        chart = await find_symbol(client, instrument, held.first, known)
        if chart is None:
            result.unmapped.append(ticker)
            return None
        instrument.price_symbol = result.found[ticker] = chart.symbol
        return chart
    chart = await client.chart(symbol, start)
    if chart is None:
        result.failed[ticker] = f"Yahoo has no {symbol} any more"
        if not instrument.price_symbol_by_hand:
            instrument.price_symbol = None  # looked for again next time
        return None
    if instrument.currency is not None and chart.currency != instrument.currency:
        result.failed[ticker] = f"{symbol} is quoted in {chart.currency}, not {instrument.currency}"
        return None
    return chart


async def _broker_prices(session: AsyncSession, instrument_id: uuid.UUID) -> dict[date, Decimal]:
    rows = await session.execute(
        select(InstrumentPrice.on, InstrumentPrice.price).where(
            InstrumentPrice.instrument_id == instrument_id,
            InstrumentPrice.source != PriceSource.YAHOO,
        )
    )
    return {on: price for on, price in rows}


async def _upsert(
    session: AsyncSession, instrument_id: uuid.UUID, closes: dict[date, Decimal]
) -> int:
    """Insert the closes, replacing what differs (a broker's price included). Returns how many
    rows changed."""
    rows = [
        {"instrument_id": instrument_id, "on": day, "price": price, "source": PriceSource.YAHOO}
        for day, price in sorted(closes.items())
    ]
    changed = 0
    for offset in range(0, len(rows), _INSERT_CHUNK):
        statement = insert(InstrumentPrice).values(rows[offset : offset + _INSERT_CHUNK])
        statement = statement.on_conflict_do_update(
            index_elements=[InstrumentPrice.instrument_id, InstrumentPrice.on],
            set_={
                "price": statement.excluded.price,
                "source": statement.excluded.source,
                "fetched_at": func.now(),
            },
            where=or_(
                InstrumentPrice.price.is_distinct_from(statement.excluded.price),
                InstrumentPrice.source.is_distinct_from(statement.excluded.source),
            ),
        ).returning(InstrumentPrice.on)
        changed += len((await session.execute(statement)).all())
    return changed


async def set_symbol(session: AsyncSession, ticker: str, symbol: str | None) -> bool:
    """Give an instrument its symbol by hand, or (None) let it be found again. Its closes go
    with the old symbol. False if no instrument has the ticker."""
    instrument = await session.scalar(select(Instrument).where(Instrument.ticker == ticker))
    if instrument is None:
        return False
    instrument.price_symbol = symbol
    instrument.price_symbol_by_hand = symbol is not None
    await session.execute(
        delete(InstrumentPrice).where(
            InstrumentPrice.instrument_id == instrument.id,
            InstrumentPrice.source == PriceSource.YAHOO,
        )
    )
    await store_broker_prices(session, [instrument.id])
    return True


async def price_summary(session: AsyncSession) -> list[PriceSummary]:
    """What is stored, per source."""
    rows = await session.execute(
        select(
            InstrumentPrice.source,
            func.count(func.distinct(InstrumentPrice.instrument_id)),
            func.count(),
            func.min(InstrumentPrice.on),
            func.max(InstrumentPrice.on),
        )
        .group_by(InstrumentPrice.source)
        .order_by(InstrumentPrice.source)
    )
    return [PriceSummary(*row) for row in rows]
