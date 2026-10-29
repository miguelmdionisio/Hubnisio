"""Monthly sums per category: the base of the spending charts, cash flow and budgets.

What counts (ADR-0007): booked transactions that aren't transfers, in euros at the rate on
their date. A category's sum is net, so a refund in an expense category lowers its spending.
Transactions without a category are summed by their kind (expense or income).

In the personal view (ADR-0005, "Shared pots") only the principal's own accounts count, and a
transfer pair with a shared pot isn't a transfer: the principal's side counts by its sign in
the pot's contributions category, or by its sign as uncategorized. Money moved back from the
pot lowers that category's spending.
"""

import uuid
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    ColumnElement,
    Date,
    DateTime,
    and_,
    cast,
    false,
    func,
    not_,
    or_,
    select,
)
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute, aliased

from hubnisio.core.auth import Principal
from hubnisio.finance import schemas
from hubnisio.finance.fx.convert import eur_amount
from hubnisio.finance.kinds import IS_TRANSFER
from hubnisio.finance.models import (
    Account,
    Category,
    CategoryAssignment,
    CategoryKind,
    Transaction,
    TransactionAnnotation,
    TransactionKind,
    TransactionStatus,
    Transfer,
)
from hubnisio.finance.scoping import View, counted_account_ids, visible_account_ids

CENT = Decimal("0.01")


@dataclass
class MonthlySums:
    """Signed sums in euros (negative = money out), by month (its first day)."""

    by_category: dict[tuple[date, uuid.UUID], Decimal] = field(
        default_factory=lambda: defaultdict(Decimal)
    )
    uncategorized: dict[tuple[date, TransactionKind], Decimal] = field(
        default_factory=lambda: defaultdict(Decimal)
    )
    unconverted: int = 0  # transactions left out: no exchange rate for their day

    def add(
        self,
        month: date,
        category_id: uuid.UUID | None,
        kind: TransactionKind,
        total: Decimal | None,
        unconverted: int,
    ) -> None:
        """One group of transactions: their category, else their kind (`kind` is ignored for
        a category). The query here and `analytics.monthly_category_spend` both load this way."""
        self.unconverted += unconverted
        if total is None:
            return
        if category_id is not None:
            self.by_category[(month, category_id)] += total
        else:
            self.uncategorized[(month, kind)] += total


@dataclass(frozen=True)
class CategoryInfo:
    id: uuid.UUID
    name: str
    kind: CategoryKind
    parent_id: uuid.UUID | None
    position: int

    @property
    def group_id(self) -> uuid.UUID:
        return self.parent_id or self.id


def month_start(day: date) -> date:
    return day.replace(day=1)


def add_months(month: date, count: int) -> date:
    index = month.year * 12 + month.month - 1 + count
    return date(index // 12, index % 12 + 1, 1)


def months_until(last: date, count: int) -> list[date]:
    """The `count` months ending with `last`'s month, oldest first."""
    end = month_start(last)
    return [add_months(end, offset) for offset in range(1 - count, 1)]


def cents(amount: Decimal) -> Decimal:
    return amount.quantize(CENT)


async def _grouped_rows(
    session: AsyncSession,
    principal: Principal,
    first: date,
    end: date,
    *,
    view: View,
    group_by: Sequence[ColumnElement[Any] | InstrumentedAttribute[Any]],
    account_id: uuid.UUID | None = None,
) -> Sequence[tuple[Any, ...]]:
    """Booked, non-transfer transactions from `first` up to `end` (exclusive) in the accounts
    that count in `view`, grouped by `group_by`, the transaction's category (a move to or from
    a pot takes the pot's), its kind override and its sign. Rows are (*group_by, category,
    override, positive, euros, unconverted, converted): the EUR sum, the transactions left out
    for want of a rate, and those summed."""
    query = (
        select()
        .select_from(Transaction)
        .outerjoin(
            Transfer,
            or_(Transfer.outgoing_id == Transaction.id, Transfer.incoming_id == Transaction.id),
        )
    )
    category: ColumnElement[uuid.UUID] = CategoryAssignment.category_id.expression
    to_pot: ColumnElement[bool] = false()
    if view == "personal":
        other_side, pot = aliased(Transaction), aliased(Account)
        query = query.outerjoin(
            other_side,
            and_(
                or_(other_side.id == Transfer.outgoing_id, other_side.id == Transfer.incoming_id),
                other_side.id != Transaction.id,
            ),
        ).outerjoin(
            pot,
            and_(
                pot.id == other_side.account_id,
                pot.is_pot,
                pot.id.in_(visible_account_ids(principal)),
            ),
        )
        to_pot = pot.id.is_not(None)
        # A move to or from a pot takes the pot's category and its own sign, whatever was
        # decided about the transaction.
        category = func.coalesce(pot.pot_category_id, CategoryAssignment.category_id)
    eur = eur_amount(
        func.coalesce(CategoryAssignment.amount, Transaction.amount),
        Transaction.currency,
        Transaction.occurred_on,
    )
    positive = Transaction.amount > 0
    query = query.add_columns(
        *group_by,
        category,
        TransactionAnnotation.kind_override,
        positive,
        func.sum(eur),
        func.count().filter(eur.is_(None)),
        func.count().filter(eur.is_not(None)),
    )
    # A move to a pot has no merchant or kind override of its own.
    query = query.outerjoin(
        TransactionAnnotation,
        and_(TransactionAnnotation.transaction_id == Transaction.id, not_(to_pot)),
    ).outerjoin(
        CategoryAssignment,
        and_(CategoryAssignment.transaction_id == Transaction.id, not_(to_pot)),
    )
    query = query.where(
        Transaction.account_id.in_(counted_account_ids(principal, view)),
        Transaction.status == TransactionStatus.BOOKED,
        Transaction.occurred_on >= first,
        Transaction.occurred_on < end,
        or_(not_(IS_TRANSFER), to_pot),
    )
    if account_id is not None:
        query = query.where(Transaction.account_id == account_id)
    rows = await session.execute(
        query.group_by(*group_by, category, TransactionAnnotation.kind_override, positive)
    )
    return [tuple(row) for row in rows]


def _kind(override: TransactionKind | None, is_positive: bool) -> TransactionKind:
    return override or (TransactionKind.INCOME if is_positive else TransactionKind.EXPENSE)


async def monthly_sums(
    session: AsyncSession, principal: Principal, first: date, last: date, *, view: View
) -> MonthlySums:
    """Sums for the months from `first`'s to `last`'s, over the accounts that count in
    `view` (finance/scoping.py)."""
    month = cast(func.date_trunc("month", cast(Transaction.occurred_on, DateTime)), Date)
    rows = await _grouped_rows(
        session,
        principal,
        month_start(first),
        add_months(month_start(last), 1),
        view=view,
        group_by=[month],
    )
    sums = MonthlySums()
    for month_, category_id, override, is_positive, total, unconverted, _ in rows:
        sums.add(month_, category_id, _kind(override, is_positive), total, unconverted)
    return sums


@dataclass(frozen=True)
class DayRow:
    """Transactions of one day with the same category and merchant: signed euros (negative =
    money out) and how many were summed. `kind` is the category's stand-in when it has none."""

    day: date
    category_id: uuid.UUID | None
    counterparty_id: uuid.UUID | None
    kind: TransactionKind
    total: Decimal
    count: int


async def daily_rows(
    session: AsyncSession,
    principal: Principal,
    first: date,
    end: date,
    *,
    view: View,
    account_id: uuid.UUID | None = None,
) -> list[DayRow]:
    """`DayRow`s from `first` up to `end` (exclusive), by the same rules as `monthly_sums`,
    optionally for one account only (still within `view`)."""
    rows = await _grouped_rows(
        session,
        principal,
        first,
        end,
        view=view,
        group_by=[Transaction.occurred_on, TransactionAnnotation.counterparty_id],
        account_id=account_id,
    )
    return [
        DayRow(day, category_id, counterparty_id, _kind(override, is_positive), total, count)
        for day, counterparty_id, category_id, override, is_positive, total, _, count in rows
        if total is not None
    ]


async def first_booked_day(
    session: AsyncSession,
    principal: Principal,
    *,
    view: View,
    account_id: uuid.UUID | None = None,
) -> date | None:
    """The earliest booked transaction in the accounts counted: before it, a month is only
    partly known."""
    query = select(func.min(Transaction.occurred_on)).where(
        Transaction.account_id.in_(counted_account_ids(principal, view)),
        Transaction.status == TransactionStatus.BOOKED,
    )
    if account_id is not None:
        query = query.where(Transaction.account_id == account_id)
    return await session.scalar(query)


async def household_categories(
    session: AsyncSession, principal: Principal
) -> dict[uuid.UUID, CategoryInfo]:
    """Every category the principal may use, archived ones too: past spending keeps its name."""
    rows = await session.scalars(
        select(Category).where(
            Category.household_id == principal.household_id,
            or_(Category.user_id.is_(None), Category.user_id == principal.user_id),
        )
    )
    return {
        category.id: CategoryInfo(
            category.id, category.name, category.kind, category.parent_id, category.position
        )
        for category in rows
    }


def spent(
    sums: MonthlySums, categories: Mapping[uuid.UUID, CategoryInfo], months: Sequence[date]
) -> dict[tuple[date, uuid.UUID], Decimal]:
    """Spending (positive = spent) per month for each expense category and each expense group,
    a group including its categories."""
    result: dict[tuple[date, uuid.UUID], Decimal] = defaultdict(Decimal)
    wanted = set(months)
    for (month, category_id), total in sums.by_category.items():
        category = categories.get(category_id)
        if month not in wanted or category is None or category.kind != CategoryKind.EXPENSE:
            continue
        result[(month, category_id)] -= total
        if category.parent_id is not None:
            result[(month, category.parent_id)] -= total
    return result


def total_spending(
    sums: MonthlySums, categories: Mapping[uuid.UUID, CategoryInfo], month: date
) -> Decimal:
    """Everything spent in `month` (positive = spent): uncategorized expenses plus every expense
    category, net of refunds. Cash flow's spending, and what the overall budget counts."""
    total = -sums.uncategorized.get((month, TransactionKind.EXPENSE), Decimal())
    for (sum_month, category_id), amount in sums.by_category.items():
        category = categories.get(category_id)
        if sum_month == month and category is not None and category.kind == CategoryKind.EXPENSE:
            total -= amount
    return total


def spending_by_group(
    sums: MonthlySums, categories: Mapping[uuid.UUID, CategoryInfo], window: Sequence[date]
) -> schemas.Spending:
    """The spending chart's data for `window`'s months: each expense group with spending, its
    categories, and uncategorized spending. `sums` cover those months."""
    by_month = spent(sums, categories, window)

    def amounts(category_id: uuid.UUID) -> list[Decimal]:
        return [cents(by_month.get((month, category_id), Decimal())) for month in window]

    used = {category_id for _, category_id in by_month}
    groups: list[schemas.SpendingGroup] = []
    for group in (c for c in categories.values() if c.parent_id is None and c.id in used):
        children = [
            schemas.SpendingCategory(id=c.id, name=c.name, amounts=amounts(c.id))
            for c in categories.values()
            if c.parent_id == group.id and c.id in used
        ]
        children.sort(key=lambda c: sum(c.amounts), reverse=True)
        groups.append(
            schemas.SpendingGroup(
                id=group.id, name=group.name, amounts=amounts(group.id), categories=children
            )
        )
    groups.sort(key=lambda g: sum(g.amounts), reverse=True)
    return schemas.Spending(
        months=list(window),
        groups=groups,
        uncategorized=[
            cents(-sums.uncategorized.get((month, TransactionKind.EXPENSE), Decimal()))
            for month in window
        ],
        unconverted=sums.unconverted,
    )


def cash_flow(
    sums: MonthlySums, categories: Mapping[uuid.UUID, CategoryInfo], window: Sequence[date]
) -> schemas.CashFlow:
    """Income and spending for `window`'s months, from the same sums as the spending chart."""
    income = {
        month: sums.uncategorized.get((month, TransactionKind.INCOME), Decimal())
        for month in window
    }
    for (month, category_id), total in sums.by_category.items():
        category = categories.get(category_id)
        if category is not None and category.kind == CategoryKind.INCOME and month in income:
            income[month] += total
    spending = {month: total_spending(sums, categories, month) for month in window}
    return schemas.CashFlow(
        months=[
            schemas.CashFlowMonth(
                month=month,
                income=cents(income[month]),
                spending=cents(spending[month]),
                net=cents(income[month] - spending[month]),
            )
            for month in window
        ],
        unconverted=sums.unconverted,
    )
