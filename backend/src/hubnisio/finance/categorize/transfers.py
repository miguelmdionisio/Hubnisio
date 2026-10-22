"""Finding transfers between the household's own accounts (ADR-0007).

An outgoing and an incoming transaction pair up when they're on two different accounts of the
household, in the same currency, for the same amount, at most `WINDOW` apart, and neither is
already in a pair. Only unique matches are linked: if an outgoing transaction could pair with
two incoming ones (or the reverse), nothing is linked and the user decides. Pairs the user
unlinked are never linked again.
"""

import uuid
from collections import defaultdict
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from hubnisio.finance.models import (
    Account,
    Source,
    Transaction,
    TransactionAnnotation,
    TransactionKind,
    TransactionStatus,
    Transfer,
    TransferDismissal,
)

WINDOW = timedelta(days=3)


async def detect_transfers(
    session: AsyncSession, household_id: uuid.UUID, since: date | None = None
) -> set[uuid.UUID]:
    """Link the unique pairs among booked transactions from `since` on (all if None).
    Returns the IDs of the transactions newly linked. The caller commits."""
    paired = set()
    for pair in await session.execute(
        select(Transfer.outgoing_id, Transfer.incoming_id).where(
            Transfer.household_id == household_id
        )
    ):
        paired.update(pair)
    dismissed = {
        (outgoing_id, incoming_id)
        for outgoing_id, incoming_id in await session.execute(
            select(TransferDismissal.outgoing_id, TransferDismissal.incoming_id).where(
                TransferDismissal.household_id == household_id
            )
        )
    }
    # A kind set by hand to income or expense means "this is not a transfer".
    not_transfers = set(
        await session.scalars(
            select(TransactionAnnotation.transaction_id).where(
                TransactionAnnotation.household_id == household_id,
                TransactionAnnotation.kind_source == Source.MANUAL,
                TransactionAnnotation.kind_override != TransactionKind.TRANSFER,
            )
        )
    )

    query = (
        select(
            Transaction.id,
            Transaction.account_id,
            Transaction.amount,
            Transaction.currency,
            Transaction.occurred_on,
        )
        .join(Account, Account.id == Transaction.account_id)
        .where(
            Account.household_id == household_id,
            Transaction.status == TransactionStatus.BOOKED,
            Transaction.amount != 0,
        )
    )
    if since is not None:
        query = query.where(Transaction.occurred_on >= since - WINDOW)
    incoming_by_key: dict[tuple[str, object], list[tuple[uuid.UUID, uuid.UUID, date]]] = (
        defaultdict(list)
    )
    outgoing: list[tuple[uuid.UUID, uuid.UUID, str, object, date]] = []
    for id_, account_id, amount, currency, occurred_on in await session.execute(query):
        if id_ in paired or id_ in not_transfers:
            continue
        if amount < 0:
            outgoing.append((id_, account_id, currency, -amount, occurred_on))
        else:
            incoming_by_key[(currency, amount)].append((id_, account_id, occurred_on))

    candidates: list[tuple[uuid.UUID, uuid.UUID]] = []
    for out_id, out_account, currency, size, out_day in outgoing:
        for in_id, in_account, in_day in incoming_by_key.get((currency, size), []):
            if (
                in_account != out_account
                and abs(in_day - out_day) <= WINDOW
                and (out_id, in_id) not in dismissed
            ):
                candidates.append((out_id, in_id))

    out_counts: dict[uuid.UUID, int] = defaultdict(int)
    in_counts: dict[uuid.UUID, int] = defaultdict(int)
    for out_id, in_id in candidates:
        out_counts[out_id] += 1
        in_counts[in_id] += 1
    linked: set[uuid.UUID] = set()
    for out_id, in_id in candidates:
        if out_counts[out_id] == 1 and in_counts[in_id] == 1:
            session.add(
                Transfer(
                    household_id=household_id,
                    outgoing_id=out_id,
                    incoming_id=in_id,
                    source=Source.AUTO,
                )
            )
            linked.update((out_id, in_id))
    await session.flush()
    return linked
