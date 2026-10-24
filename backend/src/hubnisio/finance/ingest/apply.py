"""Turning one sync's stored payloads into rows. Used by the live sync and by renormalize."""

import uuid
from collections.abc import Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from hubnisio.finance.ingest.identity import SeenRecord
from hubnisio.finance.ingest.store import StoreResult, store_balances, store_transactions
from hubnisio.finance.models import ProviderName, ProviderPayload
from hubnisio.finance.providers.base import Normalizer
from hubnisio.finance.providers.enable_banking.normalize import normalizer as enable_banking
from hubnisio.finance.providers.trading212.normalize import normalizer as trading212

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
    for payload in payloads:
        if (balances := normalizer.balances.get(payload.kind)) is not None:
            await store_balances(
                session,
                household_id=household_id,
                account_id=account_id,
                sync_run_id=sync_run_id,
                records=balances(payload.response),
                fetched_at=payload.fetched_at,
            )
        elif (transactions := normalizer.transactions.get(payload.kind)) is not None:
            page = transactions(payload.response)
            seen.extend(
                SeenRecord(record=record, payload_id=payload.id, seen_at=payload.fetched_at)
                for record in page.records
            )
    return await store_transactions(
        session, household_id=household_id, account_id=account_id, seen=seen
    )
