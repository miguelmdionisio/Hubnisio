"""Writing an investment account's records (ADR-0008): instruments, fills and snapshots.

- Instruments are global and upserted on their ticker. What a response doesn't say never
  clears what another one did, so the instrument list's type survives an order's fill.
- Fills are upserted on the account and Trading 212's fill id: a fill seen again updates its
  facts.
- A sync's positions become one portfolio snapshot, with the cash and totals of the same
  sync's summary.
"""

import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any

from sqlalchemy import func, insert, literal_column
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from hubnisio.finance.models import Fill, HoldingSnapshot, Instrument, PortfolioSnapshot
from hubnisio.finance.providers.base import (
    FillRecord,
    HoldingRecord,
    InstrumentRecord,
    PortfolioRecord,
    TaxRecord,
)

_INSTRUMENT_FACTS = ("isin", "name", "currency", "type")
_FILL_FACTS = (
    "instrument_id",
    "order_id",
    "side",
    "fill_type",
    "order_type",
    "initiated_from",
    "filled_at",
    "quantity",
    "price",
    "currency",
    "fx_rate",
    "net_value",
    "realised_result",
    "taxes",
)
_CHUNK = 500  # rows per statement, well under Postgres's bind parameter limit


@dataclass(frozen=True, slots=True)
class SeenFill:
    record: FillRecord
    payload_id: uuid.UUID
    seen_at: datetime


@dataclass(frozen=True, slots=True)
class Positions:
    """One sync's positions, and when they were read."""

    records: Sequence[HoldingRecord]
    fetched_at: datetime


async def store_instruments(
    session: AsyncSession, records: Iterable[InstrumentRecord]
) -> dict[str, uuid.UUID]:
    """Upsert instruments, merged per ticker (later records win where they say something).
    Returns each ticker's ID."""
    merged: dict[str, InstrumentRecord] = {}
    for record in records:
        current = merged.get(record.ticker)
        merged[record.ticker] = record if current is None else _merge(current, record)
    if not merged:
        return {}
    ids: dict[str, uuid.UUID] = {}
    rows = [
        {
            "id": uuid.uuid7(),
            "ticker": record.ticker,
            **{column: getattr(record, column) for column in _INSTRUMENT_FACTS},
        }
        for _, record in sorted(merged.items())
    ]
    table = Instrument.__table__
    for start in range(0, len(rows), _CHUNK):
        statement = pg_insert(Instrument).values(rows[start : start + _CHUNK])
        statement = statement.on_conflict_do_update(
            index_elements=["ticker"],
            set_={
                **{
                    column: func.coalesce(statement.excluded[column], table.c[column])
                    for column in _INSTRUMENT_FACTS
                },
                "updated_at": func.now(),
            },
        ).returning(Instrument.ticker, Instrument.id)
        ids.update({ticker: id_ for ticker, id_ in await session.execute(statement)})
    return ids


async def store_fills(
    session: AsyncSession,
    *,
    household_id: uuid.UUID,
    account_id: uuid.UUID,
    seen: Sequence[SeenFill],
    instruments: dict[str, uuid.UUID],
) -> int:
    """Upsert one sync's fills. Returns how many were new."""
    latest: dict[int, SeenFill] = {}
    for item in seen:  # a fill on two pages (the history moved while paging): the later one
        latest[item.record.fill_id] = item
    rows = [
        _fill_row(item, household_id, account_id, instruments[item.record.instrument.ticker])
        for _, item in sorted(latest.items())
    ]
    added = 0
    for start in range(0, len(rows), _CHUNK):
        statement = pg_insert(Fill).values(rows[start : start + _CHUNK])
        statement = statement.on_conflict_do_update(
            constraint="uq_fills_account_id_fill_id",
            set_={
                column: statement.excluded[column]
                for column in (*_FILL_FACTS, "payload_id", "last_seen_at")
            },
        ).returning(Fill.id, literal_column("xmax = 0"))  # true for inserted rows
        added += sum(1 for _, inserted in await session.execute(statement) if inserted)
    return added


async def store_portfolio(
    session: AsyncSession,
    *,
    household_id: uuid.UUID,
    account_id: uuid.UUID,
    sync_run_id: uuid.UUID | None,
    totals: PortfolioRecord,
    positions: Positions,
    instruments: dict[str, uuid.UUID],
) -> None:
    snapshot_id = uuid.uuid7()
    await session.execute(
        insert(PortfolioSnapshot).values(
            id=snapshot_id,
            household_id=household_id,
            account_id=account_id,
            sync_run_id=sync_run_id,
            currency=totals.currency,
            total_value=totals.total_value,
            cash=totals.cash,
            cash_in_pies=totals.cash_in_pies,
            cash_reserved=totals.cash_reserved,
            investments_value=totals.investments_value,
            investments_cost=totals.investments_cost,
            realised_result=totals.realised_result,
            unrealised_result=totals.unrealised_result,
            fetched_at=positions.fetched_at,
        )
    )
    if not positions.records:
        return
    await session.execute(
        insert(HoldingSnapshot),
        [
            {
                "id": uuid.uuid7(),
                "household_id": household_id,
                "account_id": account_id,
                "portfolio_snapshot_id": snapshot_id,
                "instrument_id": instruments[record.instrument.ticker],
                "quantity": record.quantity,
                "quantity_in_pies": record.quantity_in_pies,
                "average_price": record.average_price,
                "current_price": record.current_price,
                "currency": record.currency,
                "value": record.value,
                "cost": record.cost,
                "unrealised_result": record.unrealised_result,
                "fx_impact": record.fx_impact,
                "opened_at": record.opened_at,
            }
            for record in positions.records
        ],
    )


def _merge(current: InstrumentRecord, later: InstrumentRecord) -> InstrumentRecord:
    return replace(
        current,
        **{
            column: value
            for column in _INSTRUMENT_FACTS
            if (value := getattr(later, column)) is not None
        },
    )


def _fill_row(
    item: SeenFill, household_id: uuid.UUID, account_id: uuid.UUID, instrument_id: uuid.UUID
) -> dict[str, Any]:
    record = item.record
    return {
        "id": uuid.uuid7(),
        "household_id": household_id,
        "account_id": account_id,
        "instrument_id": instrument_id,
        "fill_id": record.fill_id,
        "order_id": record.order_id,
        "side": record.side,
        "fill_type": record.fill_type,
        "order_type": record.order_type,
        "initiated_from": record.initiated_from,
        "filled_at": record.filled_at,
        "quantity": record.quantity,
        "price": record.price,
        "currency": record.currency,
        "fx_rate": record.fx_rate,
        "net_value": record.net_value,
        "realised_result": record.realised_result,
        "taxes": [_tax(tax) for tax in record.taxes],
        "payload_id": item.payload_id,
        "first_seen_at": item.seen_at,
        "last_seen_at": item.seen_at,
    }


def _tax(tax: TaxRecord) -> dict[str, Any]:
    return {
        "name": tax.name,
        "amount": str(tax.amount),
        "currency": tax.currency,
        "charged_at": tax.charged_at.isoformat() if tax.charged_at else None,
    }
