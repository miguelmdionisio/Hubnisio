"""When the user layer is refreshed: after each sync, and on demand. Recurring series are
detected last, as they group transactions by the merchants categorizing sets."""

import uuid
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from hubnisio.finance.categorize.engine import CategorizeResult, categorize
from hubnisio.finance.categorize.transfers import detect_transfers
from hubnisio.finance.models import Account, Transaction
from hubnisio.finance.recurring.run import detect_recurring

# A sync re-fetches two weeks; look further back so a transfer whose other leg synced on an
# earlier day (or from another bank) still pairs.
TRANSFER_LOOKBACK = timedelta(days=60)


async def after_sync(
    session: AsyncSession, household_id: uuid.UUID, since: datetime, *, initial: bool = False
) -> CategorizeResult:
    """Pair recent transfers, categorize what the sync touched (and anything just paired), then
    detect recurring series. The caller commits.

    After a newly linked account's first sync (`initial`), transfers are paired across all
    history: its past may meet older moves on other accounts, such as deposits to a broker."""
    touched = set(
        await session.scalars(
            select(Transaction.id)
            .join(Account, Account.id == Transaction.account_id)
            .where(Account.household_id == household_id, Transaction.last_seen_at >= since)
        )
    )
    lookback = None if initial else (datetime.now(UTC) - TRANSFER_LOOKBACK).date()
    linked = await detect_transfers(session, household_id, since=lookback)
    result = await categorize(session, household_id, touched | linked)
    await detect_recurring(session, household_id, date.today())
    return result


async def run_all(session: AsyncSession, household_id: uuid.UUID) -> CategorizeResult:
    """Everything, from scratch: pair transfers across all history, categorize every
    transaction, then detect recurring series. For "Run rules now" and `cli recategorize`.
    The caller commits."""
    await detect_transfers(session, household_id)
    result = await categorize(session, household_id)
    await detect_recurring(session, household_id, date.today())
    return result
