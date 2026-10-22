"""When the user layer is refreshed: after each sync, and on demand."""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from hubnisio.finance.categorize.engine import CategorizeResult, categorize
from hubnisio.finance.categorize.transfers import detect_transfers
from hubnisio.finance.models import Account, Transaction

# A sync re-fetches two weeks; look further back so a transfer whose other leg synced on an
# earlier day (or from another bank) still pairs.
TRANSFER_LOOKBACK = timedelta(days=60)


async def after_sync(
    session: AsyncSession, household_id: uuid.UUID, since: datetime
) -> CategorizeResult:
    """Pair recent transfers, then categorize what the sync touched (and anything just paired).
    The caller commits."""
    touched = set(
        await session.scalars(
            select(Transaction.id)
            .join(Account, Account.id == Transaction.account_id)
            .where(Account.household_id == household_id, Transaction.last_seen_at >= since)
        )
    )
    lookback = (datetime.now(UTC) - TRANSFER_LOOKBACK).date()
    linked = await detect_transfers(session, household_id, since=lookback)
    return await categorize(session, household_id, touched | linked)


async def run_all(session: AsyncSession, household_id: uuid.UUID) -> CategorizeResult:
    """Everything, from scratch: pair transfers across all history, then categorize every
    transaction. For "Run rules now" and `cli recategorize`. The caller commits."""
    await detect_transfers(session, household_id)
    return await categorize(session, household_id)
