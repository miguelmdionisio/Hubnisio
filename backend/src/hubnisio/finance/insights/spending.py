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

from sqlalchemy import ColumnElement, Date, DateTime, and_, cast, false, func, not_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from hubnisio.core.auth import Principal
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


async def monthly_sums(
    session: AsyncSession, principal: Principal, first: date, last: date, *, view: View
) -> MonthlySums:
    """Sums for the months from `first`'s to `last`'s, over the accounts that count in
    `view` (finance/scoping.py)."""
    month = cast(func.date_trunc("month", cast(Transaction.occurred_on, DateTime)), Date)
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
    rows = await session.execute(
        query.add_columns(
            month,
            category,
            TransactionAnnotation.kind_override,
            positive,
            func.sum(eur),
            func.count().filter(eur.is_(None)),
        )
        .outerjoin(
            TransactionAnnotation,
            and_(TransactionAnnotation.transaction_id == Transaction.id, not_(to_pot)),
        )
        .outerjoin(
            CategoryAssignment,
            and_(CategoryAssignment.transaction_id == Transaction.id, not_(to_pot)),
        )
        .where(
            Transaction.account_id.in_(counted_account_ids(principal, view)),
            Transaction.status == TransactionStatus.BOOKED,
            Transaction.occurred_on >= month_start(first),
            Transaction.occurred_on < add_months(month_start(last), 1),
            or_(not_(IS_TRANSFER), to_pot),
        )
        .group_by(month, category, TransactionAnnotation.kind_override, positive)
    )
    sums = MonthlySums()
    for month_, category_id, override, is_positive, total, unconverted in rows:
        kind = override or (TransactionKind.INCOME if is_positive else TransactionKind.EXPENSE)
        sums.add(month_, category_id, kind, total, unconverted)
    return sums


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
