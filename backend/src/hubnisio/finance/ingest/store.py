"""Writing records to the bank-facts layer (ADR-0007).

Booked transactions are upserted on their identity, and only bank-fact columns change, so
anything stored about a transaction elsewhere survives. Pending transactions have no stable
identity: each sync replaces the account's whole pending set with what the bank reports now,
moving any user layer on a replaced pending row to the row it became.
"""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import TextClause, delete, insert, literal_column, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from hubnisio.finance.ingest.identity import Identified, SeenRecord, identify
from hubnisio.finance.models import (
    BalanceSnapshot,
    CategoryAssignment,
    Transaction,
    TransactionAnnotation,
    TransactionStatus,
)
from hubnisio.finance.providers.base import BalanceRecord

# The columns a sync may overwrite. Identity and first_seen_at are only ever inserted.
BANK_FACTS = (
    "amount",
    "currency",
    "original_amount",
    "original_currency",
    "occurred_on",
    "booking_date",
    "value_date",
    "transaction_date",
    "counterparty_name",
    "counterparty_iban",
    "description",
    "reference",
    "mcc",
    "bank_transaction_code",
    "balance_after",
)
_UPDATED_ON_CONFLICT = (*BANK_FACTS, "fingerprint", "payload_id", "last_seen_at")
_CHUNK = 500  # rows per statement, well under Postgres's bind parameter limit
# How far apart a pending transaction and its booked version can be dated (ADR-0007).
PENDING_MATCH = timedelta(days=5)

# Must match the partial unique indexes on finance.transactions exactly.
_BY_REFERENCE = text("status = 'booked' AND entry_reference IS NOT NULL")
_BY_FINGERPRINT = text("status = 'booked' AND entry_reference IS NULL")


@dataclass(frozen=True, slots=True)
class StoreResult:
    seen: int
    added: int  # booked transactions stored for the first time
    # Every booked transaction written (new or updated): what a sync touched.
    booked_ids: frozenset[uuid.UUID] = frozenset()


async def store_transactions(
    session: AsyncSession,
    *,
    household_id: uuid.UUID,
    account_id: uuid.UUID,
    seen: Sequence[SeenRecord],
) -> StoreResult:
    """Store everything one sync fetched for one account. Call once per sync, with all pages."""
    identified = identify(seen)
    booked = [item for item in identified if item.seen.record.status is TransactionStatus.BOOKED]
    pending = [item for item in identified if item.seen.record.status is TransactionStatus.PENDING]

    def rows(items: list[Identified]) -> list[dict[str, Any]]:
        return [_row(item, household_id, account_id) for item in items]

    written = await _upsert(
        session,
        rows([item for item in booked if item.entry_reference is not None]),
        index_elements=("account_id", "entry_reference"),
        index_where=_BY_REFERENCE,
    )
    written += await _upsert(
        session,
        rows([item for item in booked if item.entry_reference is None]),
        index_elements=("account_id", "fingerprint", "occurrence_index"),
        index_where=_BY_FINGERPRINT,
    )
    old_pending = set(
        await session.scalars(
            select(Transaction.id).where(
                Transaction.account_id == account_id,
                Transaction.status == TransactionStatus.PENDING,
            )
        )
    )
    pending_rows = rows(pending)
    new_pending = [row["id"] for row in pending_rows]
    if pending_rows:
        await session.execute(insert(Transaction), pending_rows)
    booked_ids = frozenset(id_ for id_, _ in written)
    if old_pending:
        await _carry_over(session, old_pending, [*booked_ids, *new_pending])
        await session.execute(delete(Transaction).where(Transaction.id.in_(old_pending)))
    return StoreResult(
        seen=len(seen),
        added=sum(1 for _, inserted in written if inserted),
        booked_ids=booked_ids,
    )


async def _carry_over(
    session: AsyncSession, old_pending: set[uuid.UUID], new_ids: list[uuid.UUID]
) -> None:
    """Move what people, rules or the AI recorded on pending transactions that are about to be
    replaced onto the transaction each became: same account and amount, at most
    `PENDING_MATCH` apart, preferring a booked one. Unmatched user-layer rows go with the
    pending row."""
    with_user_layer = set(
        await session.scalars(
            select(TransactionAnnotation.transaction_id).where(
                TransactionAnnotation.transaction_id.in_(old_pending)
            )
        )
    ) | set(
        await session.scalars(
            select(CategoryAssignment.transaction_id).where(
                CategoryAssignment.transaction_id.in_(old_pending)
            )
        )
    )
    if not with_user_layer or not new_ids:
        return
    occupied = set(
        await session.scalars(
            select(TransactionAnnotation.transaction_id).where(
                TransactionAnnotation.transaction_id.in_(new_ids)
            )
        )
    ) | set(
        await session.scalars(
            select(CategoryAssignment.transaction_id).where(
                CategoryAssignment.transaction_id.in_(new_ids)
            )
        )
    )
    columns = (Transaction.id, Transaction.status, Transaction.amount, Transaction.occurred_on)
    olds = (
        await session.execute(
            select(*columns)
            .where(Transaction.id.in_(with_user_layer))
            .order_by(Transaction.occurred_on)
        )
    ).all()
    targets = [
        target
        for target in (await session.execute(select(*columns).where(Transaction.id.in_(new_ids))))
        if target.id not in occupied
    ]
    for old in olds:
        options = [
            target
            for target in targets
            if target.amount == old.amount
            and abs(target.occurred_on - old.occurred_on) <= PENDING_MATCH
        ]
        if not options:
            continue
        chosen = min(
            options,
            key=lambda target: (
                target.status is not TransactionStatus.BOOKED,
                abs(target.occurred_on - old.occurred_on),
            ),
        )
        targets.remove(chosen)
        for model in (TransactionAnnotation, CategoryAssignment):
            await session.execute(
                update(model).where(model.transaction_id == old.id).values(transaction_id=chosen.id)
            )


async def store_balances(
    session: AsyncSession,
    *,
    household_id: uuid.UUID,
    account_id: uuid.UUID,
    sync_run_id: uuid.UUID | None,
    records: Sequence[BalanceRecord],
    fetched_at: datetime,
) -> None:
    if not records:
        return
    await session.execute(
        insert(BalanceSnapshot),
        [
            {
                "id": uuid.uuid7(),
                "household_id": household_id,
                "account_id": account_id,
                "sync_run_id": sync_run_id,
                "balance_type": record.balance_type,
                "amount": record.amount,
                "currency": record.currency,
                "reference_date": record.reference_date,
                "last_change_at": record.last_change_at,
                "fetched_at": fetched_at,
            }
            for record in records
        ],
    )


def _row(item: Identified, household_id: uuid.UUID, account_id: uuid.UUID) -> dict[str, Any]:
    record = item.seen.record
    return {
        "id": uuid.uuid7(),
        "household_id": household_id,
        "account_id": account_id,
        "status": record.status,
        "entry_reference": item.entry_reference,
        "fingerprint": item.fingerprint,
        "occurrence_index": item.occurrence_index,
        **{column: getattr(record, column) for column in BANK_FACTS},
        "payload_id": item.seen.payload_id,
        "first_seen_at": item.seen.seen_at,
        "last_seen_at": item.seen.seen_at,
    }


async def _upsert(
    session: AsyncSession,
    rows: list[dict[str, Any]],
    *,
    index_elements: tuple[str, ...],
    index_where: TextClause,
) -> list[tuple[uuid.UUID, bool]]:
    """Insert new rows and update the bank facts of existing ones. Returns each row's ID and
    whether it was new."""
    written: list[tuple[uuid.UUID, bool]] = []
    for start in range(0, len(rows), _CHUNK):
        statement = pg_insert(Transaction).values(rows[start : start + _CHUNK])
        statement = statement.on_conflict_do_update(
            index_elements=index_elements,
            index_where=index_where,
            set_={column: statement.excluded[column] for column in _UPDATED_ON_CONFLICT},
        ).returning(Transaction.id, literal_column("xmax = 0"))  # true for inserted rows
        result = await session.execute(statement)
        written.extend((id_, inserted) for id_, inserted in result)
    return written
