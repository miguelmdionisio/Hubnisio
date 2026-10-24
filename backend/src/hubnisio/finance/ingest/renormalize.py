"""Rebuild an account's bank facts from its raw payloads, so parser fixes never need a re-fetch.

Every sync whose fetch completed is replayed in order over the existing rows. A transaction
that still has the same identity keeps its row, its ID and so its user layer (category, notes,
transfer link). Booked rows the replay no longer produces are removed; pending rows are
replaced, as on every sync. Balances, an investment account's fills and its snapshots have no
user layer: they're deleted and rebuilt (ADR-0008).
"""

import uuid
from dataclasses import dataclass

from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from hubnisio.finance.ingest.apply import APPLY_FAILED, apply_payloads
from hubnisio.finance.models import (
    BalanceSnapshot,
    Connection,
    Fill,
    PortfolioSnapshot,
    ProviderPayload,
    SyncRun,
    SyncStatus,
    Transaction,
    TransactionStatus,
)


@dataclass(frozen=True, slots=True)
class RenormalizeResult:
    syncs: int
    transactions: int
    removed: int  # booked rows the replay no longer produces
    fills: int = 0


async def renormalize_account(session: AsyncSession, account_id: uuid.UUID) -> RenormalizeResult:
    """Run inside a transaction: on any error, the account is left as it was."""
    for model in (BalanceSnapshot, PortfolioSnapshot, Fill):  # holdings go with their snapshot
        await session.execute(delete(model).where(model.account_id == account_id))
    before = set(
        await session.scalars(
            select(Transaction.id).where(
                Transaction.account_id == account_id,
                Transaction.status == TransactionStatus.BOOKED,
            )
        )
    )

    runs = (
        await session.execute(
            select(SyncRun.id, SyncRun.household_id, Connection.provider)
            .join(Connection, Connection.id == SyncRun.connection_id)
            .where(
                SyncRun.account_id == account_id,
                or_(SyncRun.status == SyncStatus.SUCCEEDED, SyncRun.error_code == APPLY_FAILED),
            )
            .order_by(SyncRun.started_at, SyncRun.id)
        )
    ).all()
    produced: set[uuid.UUID] = set()
    for run in runs:
        payloads = (
            await session.scalars(
                select(ProviderPayload)
                .where(ProviderPayload.sync_run_id == run.id)
                .order_by(ProviderPayload.fetched_at, ProviderPayload.id)
            )
        ).all()
        stored = await apply_payloads(
            session,
            provider=run.provider,
            household_id=run.household_id,
            account_id=account_id,
            sync_run_id=run.id,
            payloads=payloads,
        )
        produced |= stored.booked_ids

    orphans = before - produced
    if orphans:
        await session.execute(delete(Transaction).where(Transaction.id.in_(orphans)))
    count = await session.scalar(
        select(func.count()).select_from(Transaction).where(Transaction.account_id == account_id)
    )
    fills = await session.scalar(
        select(func.count()).select_from(Fill).where(Fill.account_id == account_id)
    )
    return RenormalizeResult(
        syncs=len(runs), transactions=count or 0, removed=len(orphans), fills=fills or 0
    )
