"""Turning one sync's stored payloads into rows. Used by the live sync and by renormalize."""

import logging
import uuid
from collections.abc import Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from hubnisio.finance.ingest.identity import SeenRecord
from hubnisio.finance.ingest.investments import (
    Positions,
    SeenFill,
    store_fills,
    store_instruments,
    store_portfolio,
)
from hubnisio.finance.ingest.store import StoreResult, store_balances, store_transactions
from hubnisio.finance.models import ProviderName, ProviderPayload
from hubnisio.finance.providers.base import InstrumentRecord, Normalizer, PortfolioRecord
from hubnisio.finance.providers.enable_banking.normalize import normalizer as enable_banking
from hubnisio.finance.providers.trading212.normalize import normalizer as trading212

logger = logging.getLogger(__name__)

NORMALIZERS: dict[ProviderName, Normalizer] = {
    ProviderName.ENABLE_BANKING: enable_banking,
    ProviderName.TRADING212: trading212,
}

# The error code of a sync whose fetch completed but whose payloads couldn't be applied (a
# parser bug). Its payloads are complete, so renormalize replays it once the bug is fixed.
APPLY_FAILED = "APPLY_FAILED"


async def apply_payloads(
    session: AsyncSession,
    *,
    provider: ProviderName,
    household_id: uuid.UUID,
    account_id: uuid.UUID,
    sync_run_id: uuid.UUID,
    payloads: Sequence[ProviderPayload],
) -> StoreResult:
    """Apply everything one successful sync fetched for one account, in fetch order."""
    normalizer = NORMALIZERS[provider]
    seen: list[SeenRecord] = []
    # An investment account's (ADR-0008).
    totals: PortfolioRecord | None = None
    positions: Positions | None = None
    fills: list[SeenFill] = []
    instruments: list[InstrumentRecord] = []
    for payload in payloads:
        kind, raw = payload.kind, payload.response
        if (balances := normalizer.balances.get(kind)) is not None:
            await store_balances(
                session,
                household_id=household_id,
                account_id=account_id,
                sync_run_id=sync_run_id,
                records=balances(raw),
                fetched_at=payload.fetched_at,
            )
        if (transactions := normalizer.transactions.get(kind)) is not None:
            page = transactions(raw)
            seen.extend(
                SeenRecord(record=record, payload_id=payload.id, seen_at=payload.fetched_at)
                for record in page.records
            )
        if (portfolio := normalizer.portfolios.get(kind)) is not None:
            totals = portfolio(raw)
        if (holdings := normalizer.holdings.get(kind)) is not None:
            positions = Positions(holdings(raw).records, payload.fetched_at)
            instruments.extend(record.instrument for record in positions.records)
        if (fill_page := normalizer.fills.get(kind)) is not None:
            for record in fill_page(raw).records:
                fills.append(SeenFill(record, payload.id, payload.fetched_at))
                instruments.append(record.instrument)
        if (listed := normalizer.instruments.get(kind)) is not None:
            instruments.extend(listed(raw))

    stored = await store_transactions(
        session, household_id=household_id, account_id=account_id, seen=seen
    )
    if not (instruments or positions):
        return stored
    ids = await store_instruments(session, instruments)
    added = await store_fills(
        session, household_id=household_id, account_id=account_id, seen=fills, instruments=ids
    )
    if positions is not None:
        if totals is None:
            raise ValueError("Positions without the summary to go with them.")
        await store_portfolio(
            session,
            household_id=household_id,
            account_id=account_id,
            sync_run_id=sync_run_id,
            totals=totals,
            positions=positions,
            instruments=ids,
        )
    logger.info(
        "Stored %d fills (%d new) and %d positions.",
        len(fills),
        added,
        len(positions.records) if positions else 0,
    )
    return stored
