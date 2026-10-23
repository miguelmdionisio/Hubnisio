"""Net worth over time (ADR-0007, "Balances and net worth").

Each account's latest snapshot is the anchor: its booked balance if the bank sends one, as an
available balance can include an overdraft. The balance on another day is the anchor moved by
the booked transactions between that day and the anchor's date.

The series starts on the first day every included account has data for: before that, at least
one account's movements are unknown. A bank gives every account of one consent the same history,
so an account's data starts with the earliest transaction of any account on its connection: an
account opened later was simply empty before. Accounts without transactions count at their
anchor throughout. Hidden accounts are left out, like those not included in net worth, and
in the personal view so are shared pots and other members' accounts (finance/scoping.py).

`net_worth` loads the inputs and `compute_net_worth` computes from them, so the MCP server can
load the same inputs from the `analytics` views and give the same figures (ADR-0006).
"""

import uuid
from collections import defaultdict
from collections.abc import Collection, Iterable, Mapping
from dataclasses import dataclass, field
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
from hubnisio.finance.scoping import View, listed_counted_account_ids


@dataclass(frozen=True)
class IncludedAccount:
    id: uuid.UUID
    name: str
    currency: str  # the account's own, shown while it has no balance


@dataclass(frozen=True)
class Anchor:
    """An account's latest booked balance from the bank."""

    amount: Decimal
    currency: str
    on: date  # its reference date, else the day it was fetched


@dataclass
class NetWorthInputs:
    accounts: list[IncludedAccount]  # in the order they're listed
    anchors: dict[uuid.UUID, Anchor]  # the accounts that have a balance
    # Per account with a balance: the sum of its booked transactions on each day.
    daily: dict[uuid.UUID, dict[date, Decimal]] = field(default_factory=dict)
    links: list[tuple[uuid.UUID, uuid.UUID]] = field(default_factory=list)  # (connection, account)

    @property
    def currencies(self) -> set[str]:
        return {anchor.currency for anchor in self.anchors.values()}

    def only(self, account_ids: Collection[uuid.UUID]) -> NetWorthInputs:
        """The same inputs for some of the accounts."""
        return NetWorthInputs(
            accounts=[account for account in self.accounts if account.id in account_ids],
            anchors={a: anchor for a, anchor in self.anchors.items() if a in account_ids},
            daily={a: days for a, days in self.daily.items() if a in account_ids},
            links=[(c, a) for c, a in self.links if a in account_ids],
        )


async def net_worth(
    session: AsyncSession,
    principal: Principal,
    today: date,
    date_from: date | None = None,
    *,
    view: View,
) -> schemas.NetWorthOut:
    inputs = await load_inputs(session, principal, view)
    start = series_start(inputs, today, date_from)
    rates = await RateTable.load(session, inputs.currencies, start, today)
    return compute_net_worth(inputs, rates, start, today)


async def load_inputs(session: AsyncSession, principal: Principal, view: View) -> NetWorthInputs:
    accounts = list(
        await session.scalars(
            select(Account)
            .where(
                Account.id.in_(listed_counted_account_ids(principal, view)),
                Account.include_in_net_worth,
            )
            .order_by(Account.institution_name, Account.created_at)
        )
    )
    snapshots = await latest_balances(session, [account.id for account in accounts], BOOKED_FIRST)
    inputs = NetWorthInputs(
        accounts=[IncludedAccount(a.id, account_name(a), a.currency) for a in accounts],
        anchors={
            account_id: Anchor(
                snapshot.amount,
                snapshot.currency,
                snapshot.reference_date or snapshot.fetched_at.date(),
            )
            for account_id, snapshot in snapshots.items()
        },
    )
    if not inputs.anchors:
        return inputs

    daily: dict[uuid.UUID, dict[date, Decimal]] = defaultdict(dict)
    rows = await session.execute(
        select(Transaction.account_id, Transaction.occurred_on, func.sum(Transaction.amount))
        .where(
            Transaction.account_id.in_(list(inputs.anchors)),
            Transaction.status == TransactionStatus.BOOKED,
        )
        .group_by(Transaction.account_id, Transaction.occurred_on)
    )
    for account_id, on, total in rows:
        daily[account_id][on] = total
    inputs.daily = dict(daily)
    inputs.links = [
        (connection_id, account_id)
        for connection_id, account_id in await session.execute(
            select(ProviderAccount.connection_id, ProviderAccount.account_id).where(
                ProviderAccount.account_id.in_(list(daily))
            )
        )
    ]
    return inputs


def series_start(inputs: NetWorthInputs, today: date, date_from: date | None = None) -> date:
    """The first day every included account has data for, or `date_from` if later; at most
    `today`."""
    first_transactions = {a: min(days) for a, days in inputs.daily.items() if days}
    known_from = history_starts(first_transactions, inputs.links)
    start = max(known_from.values(), default=today)
    if date_from is not None:
        start = max(start, date_from)
    return min(start, today)


def history_starts(
    first_transactions: Mapping[uuid.UUID, date], links: Iterable[tuple[uuid.UUID, uuid.UUID]]
) -> dict[uuid.UUID, date]:
    """Per account with transactions: the earliest first transaction among the accounts that
    share a connection with it (its own, if it shares none)."""
    links = [(c, a) for c, a in links if a in first_transactions]
    by_connection: dict[uuid.UUID, date] = {}
    for connection_id, account_id in links:
        first = first_transactions[account_id]
        by_connection[connection_id] = min(by_connection.get(connection_id, first), first)
    starts = dict(first_transactions)
    for connection_id, account_id in links:
        starts[account_id] = min(starts[account_id], by_connection[connection_id])
    return starts


def compute_net_worth(
    inputs: NetWorthInputs, rates: RateTable, start: date, today: date
) -> schemas.NetWorthOut:
    """Net worth on each day from `start` to `today`, and each account's balance today. `rates`
    must cover those days."""
    # balance(d) = anchor + (movements up to d) - (movements up to the anchor's date)
    offsets: dict[uuid.UUID, Decimal] = {}
    running: dict[uuid.UUID, Decimal] = {}
    for account_id, anchor in inputs.anchors.items():
        days = inputs.daily.get(account_id, {})
        up_to_anchor = sum((v for d, v in days.items() if d <= anchor.on), Decimal())
        offsets[account_id] = anchor.amount - up_to_anchor
        running[account_id] = sum((v for d, v in days.items() if d < start), Decimal())

    points: list[schemas.NetWorthPoint] = []
    unconverted = 0
    day = start
    while day <= today:
        total = Decimal()
        for account_id, anchor in inputs.anchors.items():
            running[account_id] += inputs.daily.get(account_id, {}).get(day, Decimal())
            eur = rates.to_eur(offsets[account_id] + running[account_id], anchor.currency, day)
            if eur is None:
                unconverted += 1
            else:
                total += eur
        points.append(schemas.NetWorthPoint(on=day, amount=cents(total)))
        day += timedelta(days=1)

    out_accounts: list[schemas.NetWorthAccount] = []
    for account in inputs.accounts:
        anchor = inputs.anchors.get(account.id)
        balance = offsets[account.id] + running[account.id] if anchor else None
        eur = (
            rates.to_eur(balance, anchor.currency, today)
            if anchor is not None and balance is not None
            else None
        )
        out_accounts.append(
            schemas.NetWorthAccount(
                id=account.id,
                name=account.name,
                currency=anchor.currency if anchor else account.currency,
                balance=balance,
                balance_eur=cents(eur) if eur is not None else None,
                as_of=anchor.on if anchor else None,
            )
        )
    return schemas.NetWorthOut(
        total=points[-1].amount if points else Decimal("0.00"),
        points=points,
        accounts=out_accounts,
        unconverted=unconverted,
    )
