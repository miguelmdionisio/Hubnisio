"""One month's spending day by day, by category and by merchant: the Spending page's data.

Same rules as `monthly_sums` (spending.py): booked non-transfer transactions in euros on their
day, a category's sum net of refunds, a shared pot by view. A row counts if its category is an
expense category, or it has none and is an expense (`total_spending`).
"""

import uuid
from calendar import monthrange
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from hubnisio.core.auth import Principal
from hubnisio.finance import schemas
from hubnisio.finance.insights.spending import (
    CategoryInfo,
    DayRow,
    add_months,
    cents,
    daily_rows,
    first_booked_day,
    household_categories,
    month_start,
)
from hubnisio.finance.models import CategoryKind, Counterparty, TransactionKind
from hubnisio.finance.scoping import View

SHARE_STEP = Decimal("0.0001")


@dataclass(frozen=True)
class MonthFilter:
    """What narrows the rows; the account is applied when loading them."""

    category_id: uuid.UUID | None = None  # a group includes its categories
    counterparty_id: uuid.UUID | None = None


NO_FILTER = MonthFilter()


@dataclass
class Tally:
    amount: Decimal = Decimal()
    count: int = 0

    def add(self, amount: Decimal, count: int) -> None:
        self.amount += amount
        self.count += count


@dataclass
class _Month:
    days: dict[date, Tally]
    categories: dict[uuid.UUID | None, Tally]
    merchants: dict[uuid.UUID | None, Tally]
    total: Decimal = Decimal()
    count: int = 0


def counts_as_spending(row: DayRow, categories: Mapping[uuid.UUID, CategoryInfo]) -> bool:
    if row.category_id is None:
        return row.kind == TransactionKind.EXPENSE
    category = categories.get(row.category_id)
    return category is not None and category.kind == CategoryKind.EXPENSE


def matches(
    row: DayRow, categories: Mapping[uuid.UUID, CategoryInfo], narrowed: MonthFilter
) -> bool:
    if narrowed.counterparty_id is not None and row.counterparty_id != narrowed.counterparty_id:
        return False
    if narrowed.category_id is not None:
        category = categories.get(row.category_id) if row.category_id else None
        if category is None or narrowed.category_id not in (category.id, category.parent_id):
            return False
    return True


def _part(
    rows: Sequence[DayRow],
    categories: Mapping[uuid.UUID, CategoryInfo],
    narrowed: MonthFilter,
    month: date,
) -> _Month:
    last = monthrange(month.year, month.month)[1]
    result = _Month(
        days={month + timedelta(days=n): Tally() for n in range(last)}, categories={}, merchants={}
    )
    for row in rows:
        if month_start(row.day) != month or not counts_as_spending(row, categories):
            continue
        if not matches(row, categories, narrowed):
            continue
        spent = -row.total
        result.days[row.day].add(spent, row.count)
        result.categories.setdefault(row.category_id, Tally()).add(spent, row.count)
        result.merchants.setdefault(row.counterparty_id, Tally()).add(spent, row.count)
        result.total += spent
        result.count += row.count
    return result


def _days(part: _Month, through: date | None) -> list[schemas.SpendingDay]:
    days: list[schemas.SpendingDay] = []
    running = Decimal()
    for day, tally in part.days.items():
        running += tally.amount
        days.append(
            schemas.SpendingDay(
                day=day,
                amount=cents(tally.amount),
                count=tally.count,
                running=cents(running) if through is not None and day <= through else None,
            )
        )
    return days


def _ranks(
    tallies: Mapping[uuid.UUID | None, Tally],
    total: Decimal,
    names: Mapping[uuid.UUID, str],
    parents: Mapping[uuid.UUID, uuid.UUID | None],
) -> list[schemas.SpendingRank]:
    ranks = [
        schemas.SpendingRank(
            id=key,
            name=names.get(key) if key else None,
            parent_id=parents.get(key) if key else None,
            amount=cents(tally.amount),
            count=tally.count,
            share=(tally.amount / total).quantize(SHARE_STEP) if total > 0 else Decimal(0),
        )
        for key, tally in tallies.items()
    ]
    ranks.sort(key=lambda r: r.amount, reverse=True)
    return ranks


def month_spending(
    rows: Sequence[DayRow],
    categories: Mapping[uuid.UUID, CategoryInfo],
    merchants: Mapping[uuid.UUID, str],
    month: date,
    *,
    today: date,
    first_data: date | None,
    narrowed: MonthFilter = NO_FILTER,
) -> schemas.SpendingMonth:
    """The month's spending from `rows` (which cover it and the month before). `today` is
    the current day; `first_data` the earliest booked transaction of the accounts counted."""
    month = month_start(month)
    before = add_months(month, -1)

    def part_of(first: date) -> tuple[_Month, date | None, bool]:
        end = add_months(first, 1) - timedelta(days=1)
        through = None if today < first else min(today, end)
        incomplete = end >= today or first_data is None or first_data > first
        return _part(rows, categories, narrowed, first), through, incomplete

    current, through, incomplete = part_of(month)
    previous, previous_through, previous_incomplete = part_of(before)
    elapsed = through.day if through else 0
    previous_days = _days(previous, previous_through)
    to_date = Decimal("0.00")
    if elapsed:
        running = previous_days[min(elapsed, len(previous_days)) - 1].running
        to_date = running if running is not None else cents(previous.total)
    names = {c.id: c.name for c in categories.values()}
    parents = {c.id: c.parent_id for c in categories.values()}
    return schemas.SpendingMonth(
        month=month,
        through=through,
        incomplete=incomplete,
        total=cents(current.total),
        count=current.count,
        days=_days(current, through),
        daily_average=cents(current.total / elapsed) if elapsed else Decimal("0.00"),
        categories=_ranks(current.categories, current.total, names, parents),
        merchants=_ranks(current.merchants, current.total, merchants, {}),
        previous=schemas.SpendingMonthPart(
            month=before,
            through=previous_through,
            incomplete=previous_incomplete,
            total=cents(previous.total),
            count=previous.count,
            days=previous_days,
        ),
        previous_to_date=to_date,
    )


async def load_month_spending(
    session: AsyncSession,
    principal: Principal,
    month: date,
    *,
    view: View,
    today: date,
    account_id: uuid.UUID | None = None,
    narrowed: MonthFilter = NO_FILTER,
) -> schemas.SpendingMonth:
    month = month_start(month)
    rows = await daily_rows(
        session,
        principal,
        add_months(month, -1),
        add_months(month, 1),
        view=view,
        account_id=account_id,
    )
    names = {
        id_: name
        for id_, name in await session.execute(
            select(Counterparty.id, Counterparty.name).where(
                Counterparty.household_id == principal.household_id
            )
        )
    }
    return month_spending(
        rows,
        await household_categories(session, principal),
        names,
        month,
        today=today,
        first_data=await first_booked_day(session, principal, view=view, account_id=account_id),
        narrowed=narrowed,
    )
