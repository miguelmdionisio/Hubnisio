"""Net worth over time (ADR-0007, "Balances and net worth").

Each account's latest snapshot is the anchor: its booked balance if the bank sends one, as an
available balance can include an overdraft. The balance on another day is the anchor moved by
the booked transactions between that day and the anchor's date.

The series starts on the first day every included account has data for: before that, at least
one account's movements are unknown. A bank gives every account of one consent the same history,
so an account's data starts with the earliest transaction of any account on its connection: an
account opened later was simply empty before. Accounts without transactions count at their
anchor throughout. Hidden accounts are left out, like those not included in net worth.
"""

import uuid
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from hubnisio.core.auth import Principal
from hubnisio.finance import schemas
from hubnisio.finance.balances import BOOKED_FIRST, latest_balances
from hubnisio.finance.fx.convert import RateTable
from hubnisio.finance.insights.spending import cents
from hubnisio.finance.models import Account, ProviderAccount, Transaction, TransactionStatus
from hubnisio.finance.naming import account_name
from hubnisio.finance.scoping import listed_account_ids


async def net_worth(
    session: AsyncSession, principal: Principal, today: date, date_from: date | None = None
) -> schemas.NetWorthOut:
    accounts = list(
        await session.scalars(
            select(Account)
            .where(Account.id.in_(listed_account_ids(principal)), Account.include_in_net_worth)
            .order_by(Account.institution_name, Account.created_at)
        )
    )
    anchors = await latest_balances(session, [account.id for account in accounts], BOOKED_FIRST)
    anchor_dates = {
        account_id: snapshot.reference_date or snapshot.fetched_at.date()
        for account_id, snapshot in anchors.items()
    }

    daily: dict[uuid.UUID, dict[date, Decimal]] = defaultdict(dict)
    if anchors:
        rows = await session.execute(
            select(Transaction.account_id, Transaction.occurred_on, func.sum(Transaction.amount))
            .where(
                Transaction.account_id.in_(list(anchors)),
                Transaction.status == TransactionStatus.BOOKED,
            )
            .group_by(Transaction.account_id, Transaction.occurred_on)
        )
        for account_id, on, total in rows:
            daily[account_id][on] = total

    known_from = await _history_starts(session, {a: min(days) for a, days in daily.items()})
    start = max(known_from.values(), default=today)
    if date_from is not None:
        start = max(start, date_from)
    start = min(start, today)
    rates = await RateTable.load(
        session, {snapshot.currency for snapshot in anchors.values()}, start, today
    )

    # balance(d) = anchor + (movements up to d) - (movements up to the anchor's date)
    offsets: dict[uuid.UUID, Decimal] = {}
    running: dict[uuid.UUID, Decimal] = {}
    for account_id, snapshot in anchors.items():
        days = daily.get(account_id, {})
        up_to_anchor = sum((v for d, v in days.items() if d <= anchor_dates[account_id]), Decimal())
        offsets[account_id] = snapshot.amount - up_to_anchor
        running[account_id] = sum((v for d, v in days.items() if d < start), Decimal())

    points: list[schemas.NetWorthPoint] = []
    unconverted = 0
    day = start
    while day <= today:
        total = Decimal()
        for account_id, snapshot in anchors.items():
            running[account_id] += daily.get(account_id, {}).get(day, Decimal())
            eur = rates.to_eur(offsets[account_id] + running[account_id], snapshot.currency, day)
            if eur is None:
                unconverted += 1
            else:
                total += eur
        points.append(schemas.NetWorthPoint(on=day, amount=cents(total)))
        day += timedelta(days=1)

    out_accounts: list[schemas.NetWorthAccount] = []
    for account in accounts:
        snapshot = anchors.get(account.id)
        balance = offsets[account.id] + running[account.id] if snapshot else None
        eur = (
            rates.to_eur(balance, snapshot.currency, today)
            if snapshot is not None and balance is not None
            else None
        )
        out_accounts.append(
            schemas.NetWorthAccount(
                id=account.id,
                name=account_name(account),
                currency=snapshot.currency if snapshot else account.currency,
                balance=balance,
                balance_eur=cents(eur) if eur is not None else None,
                as_of=anchor_dates.get(account.id),
            )
        )
    return schemas.NetWorthOut(
        total=points[-1].amount if points else Decimal("0.00"),
        points=points,
        accounts=out_accounts,
        unconverted=unconverted,
    )


async def _history_starts(
    session: AsyncSession, first_transactions: dict[uuid.UUID, date]
) -> dict[uuid.UUID, date]:
    """Per account with transactions: the earliest first transaction among the accounts that
    share a connection with it (its own, if it shares none)."""
    links = list(
        await session.execute(
            select(ProviderAccount.connection_id, ProviderAccount.account_id).where(
                ProviderAccount.account_id.in_(list(first_transactions))
            )
        )
    )
    by_connection: dict[uuid.UUID, date] = {}
    for connection_id, account_id in links:
        first = first_transactions[account_id]
        by_connection[connection_id] = min(by_connection.get(connection_id, first), first)
    starts = dict(first_transactions)
    for connection_id, account_id in links:
        starts[account_id] = min(starts[account_id], by_connection[connection_id])
    return starts
