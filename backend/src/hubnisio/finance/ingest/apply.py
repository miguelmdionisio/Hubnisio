"""Turning one sync's stored payloads into rows. Used by the live sync and by renormalize."""

import uuid
from collections.abc import Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from hubnisio.finance.ingest.identity import SeenRecord
from hubnisio.finance.ingest.store import StoreResult, store_balances, store_transactions
from hubnisio.finance.models import ProviderName, ProviderPayload
from hubnisio.finance.providers.base import Normalizer
from hubnisio.finance.providers.enable_banking.normalize import normalizer as enable_banking

NORMALIZERS: dict[ProviderName, Normalizer] = {ProviderName.ENABLE_BANKING: enable_banking}


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
        match payload.kind:
            case "balances":
                await store_balances(
                    session,
                    household_id=household_id,
                    account_id=account_id,
                    sync_run_id=sync_run_id,
                    records=normalizer.balances(payload.response),
                    fetched_at=payload.fetched_at,
                )
            case "transactions":
                page = normalizer.transactions(payload.response)
                seen.extend(
                    SeenRecord(record=record, payload_id=payload.id, seen_at=payload.fetched_at)
                    for record in page.records
                )
            case _:
                pass
    return await store_transactions(
        session, household_id=household_id, account_id=account_id, seen=seen
    )
