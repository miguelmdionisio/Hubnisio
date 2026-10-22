"""Rebuild an account's bank facts from its raw payloads, so parser fixes never need a re-fetch.

Every successful sync is replayed in order, which reproduces the rows a live sync produced.
Transaction IDs change. Nothing refers to them yet; once the user layer exists (M2), this has
to carry categories and notes over to the rebuilt rows.
"""

import uuid
from dataclasses import dataclass

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from hubnisio.finance.ingest.apply import apply_payloads
from hubnisio.finance.models import (
    BalanceSnapshot,
    Connection,
    ProviderPayload,
    SyncRun,
    SyncStatus,
    Transaction,
)


@dataclass(frozen=True, slots=True)
class RenormalizeResult:
    syncs: int
    transactions: int


async def renormalize_account(session: AsyncSession, account_id: uuid.UUID) -> RenormalizeResult:
    """Run inside a transaction: on any error, the account is left as it was."""
    await session.execute(delete(Transaction).where(Transaction.account_id == account_id))
    await session.execute(delete(BalanceSnapshot).where(BalanceSnapshot.account_id == account_id))

    runs = (
        await session.execute(
            select(SyncRun.id, SyncRun.household_id, Connection.provider)
            .join(Connection, Connection.id == SyncRun.connection_id)
            .where(SyncRun.account_id == account_id, SyncRun.status == SyncStatus.SUCCEEDED)
            .order_by(SyncRun.started_at, SyncRun.id)
        )
    ).all()
    for run in runs:
        payloads = (
            await session.scalars(
                select(ProviderPayload)
                .where(ProviderPayload.sync_run_id == run.id)
                .order_by(ProviderPayload.fetched_at, ProviderPayload.id)
            )
        ).all()
        await apply_payloads(
            session,
            provider=run.provider,
            household_id=run.household_id,
            account_id=account_id,
            sync_run_id=run.id,
            payloads=payloads,
        )

    count = await session.scalar(
        select(func.count()).select_from(Transaction).where(Transaction.account_id == account_id)
    )
    return RenormalizeResult(syncs=len(runs), transactions=count or 0)
