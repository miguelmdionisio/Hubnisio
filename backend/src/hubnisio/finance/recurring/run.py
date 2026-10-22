"""Applying detection to the database: after each sync, on "Run rules now", and from the CLI.

A detected chain that shares a transaction with an existing series *is* that series: it's
updated and keeps the user's choices (review, name, cancellation). That's how a confirmation or
a dismissal survives every later run. A new chain becomes a suggestion, unless it already
stopped long ago.
"""

import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import date

from sqlalchemy import func, not_, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from hubnisio.finance.kinds import IS_TRANSFER
from hubnisio.finance.models import (
    Account,
    Counterparty,
    RecurringSeries,
    RecurringStatus,
    Transaction,
    TransactionAnnotation,
    TransactionStatus,
    Transfer,
)
from hubnisio.finance.recurring.detect import Candidate, Payment, detect, status_on


@dataclass(frozen=True)
class RecurringResult:
    series: int  # detected this run
    created: int


async def detect_recurring(
    session: AsyncSession, household_id: uuid.UUID, today: date
) -> RecurringResult:
    """Re-detect every account's series. The caller commits."""
    rows = await session.execute(
        select(
            Transaction.id,
            Transaction.account_id,
            Transaction.occurred_on,
            Transaction.amount,
            Transaction.currency,
            Transaction.description,
            TransactionAnnotation.counterparty_id,
            Counterparty.name,
        )
        .join(Account, Account.id == Transaction.account_id)
        .outerjoin(TransactionAnnotation, TransactionAnnotation.transaction_id == Transaction.id)
        .outerjoin(Counterparty, Counterparty.id == TransactionAnnotation.counterparty_id)
        .outerjoin(
            Transfer,
            or_(Transfer.outgoing_id == Transaction.id, Transfer.incoming_id == Transaction.id),
        )
        .where(
            Account.household_id == household_id,
            Transaction.status == TransactionStatus.BOOKED,
            not_(IS_TRANSFER),
        )
    )
    by_account: dict[uuid.UUID, list[Payment]] = defaultdict(list)
    for id_, account_id, on, amount, currency, description, counterparty_id, name in rows:
        by_account[account_id].append(
            Payment(id_, on, amount, currency, counterparty_id, name, description)
        )

    existing = list(
        await session.scalars(
            select(RecurringSeries).where(RecurringSeries.household_id == household_id)
        )
    )
    links_now = await session.execute(
        select(
            TransactionAnnotation.transaction_id, TransactionAnnotation.recurring_series_id
        ).where(
            TransactionAnnotation.household_id == household_id,
            TransactionAnnotation.recurring_series_id.is_not(None),
        )
    )
    member_of = {
        transaction_id: series_id
        for transaction_id, series_id in links_now
        if series_id is not None
    }
    series_by_id = {series.id: series for series in existing}

    detected = 0
    created = 0
    claimed: set[uuid.UUID] = set()
    links: dict[uuid.UUID, uuid.UUID] = {}  # transaction -> series, for this run's series
    for account_id, payments in by_account.items():
        for candidate in detect(payments):
            series = _match(candidate, member_of, series_by_id, claimed)
            status = status_on(
                candidate.cadence,
                candidate.next_expected_on,
                today,
                series.cancelled_on if series else None,
            )
            restarted = (
                series is not None
                and series.cancelled_on is not None
                and candidate.members[-1].on > series.cancelled_on
            )
            if series is not None and restarted:
                series.cancelled_on = None  # paid again after the user cancelled it
                status = status_on(candidate.cadence, candidate.next_expected_on, today)
            if series is None:
                if status == RecurringStatus.CANCELLED:
                    continue  # long over: not worth suggesting
                series = RecurringSeries(household_id=household_id, account_id=account_id)
                session.add(series)
                created += 1
            _apply(series, candidate, status)
            await session.flush()
            claimed.add(series.id)
            detected += 1
            for payment in candidate.members:
                links[payment.id] = series.id

    # Series no chain matched this time keep their links; their status still moves on.
    for series in existing:
        if series.id not in claimed:
            series.status = status_on(
                series.cadence, series.next_expected_on, today, series.cancelled_on
            )

    stale = [
        transaction_id
        for transaction_id, series_id in member_of.items()
        if series_id in claimed and links.get(transaction_id) != series_id
    ]
    if stale:
        await session.execute(
            update(TransactionAnnotation)
            .where(TransactionAnnotation.transaction_id.in_(stale))
            .values(recurring_series_id=None)
        )
    if links:
        statement = insert(TransactionAnnotation).values(
            [
                {
                    "transaction_id": transaction_id,
                    "household_id": household_id,
                    "recurring_series_id": series_id,
                }
                for transaction_id, series_id in links.items()
            ]
        )
        await session.execute(
            statement.on_conflict_do_update(
                index_elements=["transaction_id"],
                set_={"recurring_series_id": statement.excluded.recurring_series_id},
            )
        )
    return RecurringResult(series=detected, created=created)


def _match(
    candidate: Candidate,
    member_of: dict[uuid.UUID, uuid.UUID],
    series_by_id: dict[uuid.UUID, RecurringSeries],
    claimed: set[uuid.UUID],
) -> RecurringSeries | None:
    """The existing series sharing the most transactions with the candidate, if any."""
    shared: dict[uuid.UUID, int] = defaultdict(int)
    for payment in candidate.members:
        series_id = member_of.get(payment.id)
        if series_id is not None and series_id not in claimed:
            shared[series_id] += 1
    if not shared:
        return None
    return series_by_id[max(shared, key=lambda series_id: shared[series_id])]


def _apply(series: RecurringSeries, candidate: Candidate, status: RecurringStatus) -> None:
    series.counterparty_id = candidate.counterparty_id
    series.match_key = candidate.match_key
    series.name = candidate.name
    series.cadence = candidate.cadence
    series.kind = candidate.kind
    series.expected_amount = candidate.expected_amount
    series.currency = candidate.currency
    series.amount_varies = candidate.amount_varies
    series.occurrences = len(candidate.members)
    series.first_seen_on = candidate.members[0].on
    series.last_seen_on = candidate.members[-1].on
    series.next_expected_on = candidate.next_expected_on
    series.previous_amount = candidate.previous_amount
    series.amount_changed_on = candidate.amount_changed_on
    series.status = status
    series.updated_at = func.now()
