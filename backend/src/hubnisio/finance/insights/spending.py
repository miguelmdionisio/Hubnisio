"""Monthly sums per category: the base of the spending charts, cash flow and budgets.

What counts (ADR-0007): booked transactions that aren't transfers, in euros at the rate on
their date. A category's sum is net, so a refund in an expense category lowers its spending.
Transactions without a category are summed by their kind (expense or income).
"""

import uuid
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from sqlalchemy import Date, DateTime, cast, func, not_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from hubnisio.core.auth import Principal
from hubnisio.finance.fx.convert import eur_amount
from hubnisio.finance.kinds import IS_TRANSFER
from hubnisio.finance.models import (
    Category,
    CategoryAssignment,
    CategoryKind,
    Transaction,
    TransactionAnnotation,
    TransactionKind,
    TransactionStatus,
    Transfer,
)
from hubnisio.finance.scoping import visible_account_ids

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
    session: AsyncSession, principal: Principal, first: date, last: date
) -> MonthlySums:
    """Sums for the months from `first`'s to `last`'s, over the accounts the principal sees."""
    month = cast(func.date_trunc("month", cast(Transaction.occurred_on, DateTime)), Date)
    eur = eur_amount(
        func.coalesce(CategoryAssignment.amount, Transaction.amount),
        Transaction.currency,
        Transaction.occurred_on,
    )
    positive = Transaction.amount > 0
    rows = await session.execute(
        select(
            month,
            CategoryAssignment.category_id,
            TransactionAnnotation.kind_override,
            positive,
            func.sum(eur),
            func.count().filter(eur.is_(None)),
        )
        .select_from(Transaction)
        .outerjoin(TransactionAnnotation, TransactionAnnotation.transaction_id == Transaction.id)
        .outerjoin(CategoryAssignment, CategoryAssignment.transaction_id == Transaction.id)
        .outerjoin(
            Transfer,
            or_(Transfer.outgoing_id == Transaction.id, Transfer.incoming_id == Transaction.id),
        )
        .where(
            Transaction.account_id.in_(visible_account_ids(principal)),
            Transaction.status == TransactionStatus.BOOKED,
            Transaction.occurred_on >= month_start(first),
            Transaction.occurred_on < add_months(month_start(last), 1),
            not_(IS_TRANSFER),
        )
        .group_by(
            month, CategoryAssignment.category_id, TransactionAnnotation.kind_override, positive
        )
    )
    sums = MonthlySums()
    for month_, category_id, override, is_positive, total, unconverted in rows:
        sums.unconverted += unconverted
        if total is None:
            continue
        if category_id is not None:
            sums.by_category[(month_, category_id)] += total
        else:
            kind = override or (TransactionKind.INCOME if is_positive else TransactionKind.EXPENSE)
            sums.uncategorized[(month_, kind)] += total
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
    sums: MonthlySums, categories: dict[uuid.UUID, CategoryInfo], months: Sequence[date]
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
