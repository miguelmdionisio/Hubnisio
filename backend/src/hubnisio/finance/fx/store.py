"""Keeping `fx_rates` filled: which currencies the hub holds, which days are missing, and the
fetching and upserting (ADR-0007, "FX rates"). Callers commit."""

import logging
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import Date, cast, func, or_, select, union_all
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from hubnisio.finance.fx.convert import BASE_CURRENCY
from hubnisio.finance.fx.sources import (
    CURRENCY_API_FIRST_DATE,
    FxClient,
    FxSourceError,
    is_currency_code,
)
from hubnisio.finance.models import Account, BalanceSnapshot, FxRate, FxSource, Transaction

logger = logging.getLogger(__name__)

# The ECB publishes on every TARGET business day, so a series whose newest rate is older than
# this has stopped (its MAD series ended in 2020) and the currency isn't the ECB's to supply.
ECB_STALE_AFTER = timedelta(days=30)
# currency-api needs one request per day: daily for the last two weeks, weekly before that.
DAILY_WINDOW = timedelta(days=14)
_WEEK = timedelta(days=7)
_INSERT_CHUNK = 5000


@dataclass
class RefreshResult:
    # Rows inserted or changed by this run.
    written: dict[tuple[str, FxSource], int] = field(default_factory=dict)
    # Currencies that couldn't be fetched (completely or partly), with the reason.
    failed: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class RateSummary:
    currency: str
    source: FxSource
    rows: int
    first: date
    last: date


async def earliest_transaction_day(session: AsyncSession) -> date | None:
    return await session.scalar(select(func.min(Transaction.occurred_on)))


async def currencies_in_use(session: AsyncSession) -> dict[str, date]:
    """Every non-euro currency an account, transaction (its own or original) or balance
    snapshot uses, with the first day it shows up."""
    snapshot_day = func.coalesce(
        BalanceSnapshot.reference_date, cast(BalanceSnapshot.fetched_at, Date)
    )
    appearances = union_all(
        select(Account.currency, func.min(cast(Account.created_at, Date))).group_by(
            Account.currency
        ),
        select(Transaction.currency, func.min(Transaction.occurred_on)).group_by(
            Transaction.currency
        ),
        select(Transaction.original_currency, func.min(Transaction.occurred_on))
        .where(Transaction.original_currency.is_not(None))
        .group_by(Transaction.original_currency),
        select(BalanceSnapshot.currency, func.min(snapshot_day)).group_by(BalanceSnapshot.currency),
    ).subquery()
    rows = await session.execute(
        select(appearances.c[0], func.min(appearances.c[1]))
        .where(appearances.c[0] != BASE_CURRENCY)
        .group_by(appearances.c[0])
    )
    return {currency: first for currency, first in rows if is_currency_code(currency)}


def sample_dates(start: date, end: date) -> list[date]:
    """The days to ask currency-api for: every week from `start` until the last two weeks,
    then every day. The currencies that come from currency-api (MAD, pegged to a basket) move
    well under 1% a week, and conversion accepts a rate up to ten days old, so a weekly sample
    serves the days between."""
    daily_from = max(start, end - DAILY_WINDOW + timedelta(days=1))
    days: list[date] = []
    day = start
    while day < daily_from:
        days.append(day)
        day += _WEEK
    days.extend(daily_from + timedelta(days=n) for n in range((end - daily_from).days + 1))
    return days


async def refresh_rates(
    session: AsyncSession,
    client: FxClient,
    *,
    since: date | None = None,
    today: date | None = None,
) -> RefreshResult:
    """Fetch and store the rates of every currency in use that are missing.

    Without `since`, each currency continues after its newest stored day; one with nothing
    stored starts at the earliest day the hub has data for (any transaction, or the currency's
    own first appearance). With `since`, every currency is checked from that day, and only the
    missing or changed rates are written. Safe to repeat.
    """
    today = today or datetime.now(UTC).date()
    needs = await currencies_in_use(session)
    earliest = await earliest_transaction_day(session)
    stored: dict[str, set[date]] = {}
    for currency, day in await session.execute(
        select(FxRate.quote_currency, FxRate.on).where(FxRate.quote_currency.in_(needs))
    ):
        stored.setdefault(currency, set()).add(day)

    result = RefreshResult()
    for currency in sorted(needs):
        have = stored.get(currency, set())
        if since is not None:
            start = since
        elif have:
            start = max(have) + timedelta(days=1)
        else:
            start = min(needs[currency], earliest or needs[currency])
        if start > today:
            continue
        source, rates, error = await _fetch(client, currency, start, today, have)
        written = await _upsert(session, currency, source, rates)
        if written:
            result.written[(currency, source)] = written
        if error:
            result.failed[currency] = error
        logger.info(
            "%s from %s: %d rates fetched, %d written%s",
            currency,
            start,
            len(rates),
            written,
            f", failed: {error}" if error else "",
        )
    return result


async def _fetch(
    client: FxClient, currency: str, start: date, today: date, have: set[date]
) -> tuple[FxSource, dict[date, Decimal], str | None]:
    """The rates from `start` on, from the source that covers the currency, and what went
    wrong if anything did. A failure part-way keeps the rates fetched before it."""
    try:
        latest = await client.ecb_latest(currency)
        if latest is not None and latest >= today - ECB_STALE_AFTER:
            return FxSource.ECB, await client.ecb_rates(currency, start), None
    except FxSourceError as exc:
        return FxSource.ECB, {}, str(exc)

    rates: dict[date, Decimal] = {}
    try:
        for day in sample_dates(max(start, CURRENCY_API_FIRST_DATE), today):
            if day in have:
                continue
            if (rate := await client.currency_api_rate(currency, day)) is not None:
                rates[day] = rate
    except FxSourceError as exc:
        return FxSource.CURRENCY_API, rates, str(exc)
    return FxSource.CURRENCY_API, rates, None


async def _upsert(
    session: AsyncSession, currency: str, source: FxSource, rates: dict[date, Decimal]
) -> int:
    """Insert the rates, replacing stored ones that differ. Returns how many rows changed."""
    rows = [
        {"quote_currency": currency, "on": day, "rate": rate, "source": source}
        for day, rate in sorted(rates.items())
    ]
    changed = 0
    for offset in range(0, len(rows), _INSERT_CHUNK):
        statement = insert(FxRate).values(rows[offset : offset + _INSERT_CHUNK])
        statement = statement.on_conflict_do_update(
            index_elements=[FxRate.quote_currency, FxRate.on],
            set_={
                "rate": statement.excluded.rate,
                "source": statement.excluded.source,
                "fetched_at": func.now(),
            },
            where=or_(
                FxRate.rate.is_distinct_from(statement.excluded.rate),
                FxRate.source.is_distinct_from(statement.excluded.source),
            ),
        ).returning(FxRate.on)
        changed += len((await session.execute(statement)).all())
    return changed


async def rate_summary(session: AsyncSession) -> list[RateSummary]:
    """What is stored, per currency and source."""
    rows = await session.execute(
        select(
            FxRate.quote_currency,
            FxRate.source,
            func.count(),
            func.min(FxRate.on),
            func.max(FxRate.on),
        )
        .group_by(FxRate.quote_currency, FxRate.source)
        .order_by(FxRate.quote_currency, FxRate.source)
    )
    return [RateSummary(*row) for row in rows]
