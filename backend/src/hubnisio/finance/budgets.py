"""Budgets: monthly limits per category, computed on read (ADR-0007, "Budgets").

A month's money is its limit plus what the previous month carried in. What's left over carries
into the next month only with rollover on; an overspend carries (as a negative) only with
overspend set to carry. A group's budget covers its categories; when a category inside it has a
budget too, that's a sub-limit and totals count the group alone.
"""

import uuid
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from hubnisio.core.auth import Principal
from hubnisio.finance import schemas
from hubnisio.finance.insights.spending import (
    CategoryInfo,
    add_months,
    cents,
    household_categories,
    month_start,
    monthly_sums,
    spent,
)
from hubnisio.finance.models import Budget, BudgetLimit, CategoryKind, Overspend, TransactionKind


@dataclass(frozen=True)
class BudgetMonth:
    month: date
    limit: Decimal
    carried_in: Decimal
    available: Decimal  # limit + carried_in
    spent: Decimal
    remaining: Decimal  # available - spent; negative when over


def budget_months(
    limits: Sequence[tuple[date, Decimal]],
    spending: Mapping[date, Decimal],
    *,
    rollover: bool,
    overspend: Overspend,
    until: date,
) -> list[BudgetMonth]:
    """Every month from the budget's first limit to `until`'s month. `limits` are (first day
    of a month, amount), each holding until the next; `spending` is per first day of a month."""
    ordered = sorted(limits)
    if not ordered:
        return []
    months: list[BudgetMonth] = []
    month, last = ordered[0][0], month_start(until)
    carry = Decimal()
    while month <= last:
        limit = next(amount for starts_on, amount in reversed(ordered) if starts_on <= month)
        available = limit + carry
        used = spending.get(month, Decimal())
        remaining = available - used
        months.append(BudgetMonth(month, limit, carry, available, used, remaining))
        if remaining > 0:
            carry = remaining if rollover else Decimal()
        else:
            carry = remaining if overspend == Overspend.CARRY else Decimal()
        month = add_months(month, 1)
    return months


async def budgets_for_month(
    session: AsyncSession, principal: Principal, month: date
) -> schemas.BudgetsOut:
    month = month_start(month)
    categories = await household_categories(session, principal)
    budgets = [
        budget
        for budget in await session.scalars(
            select(Budget).where(Budget.household_id == principal.household_id)
        )
        if budget.category_id in categories
    ]
    limits: dict[uuid.UUID, list[tuple[date, Decimal]]] = defaultdict(list)
    for row in await session.scalars(
        select(BudgetLimit).where(BudgetLimit.budget_id.in_([budget.id for budget in budgets]))
    ):
        limits[row.budget_id].append((row.starts_on, row.amount))

    first = min((starts_on for rows in limits.values() for starts_on, _ in rows), default=month)
    first = min(first, month)
    sums = await monthly_sums(session, principal, first, month)
    window = []
    cursor = first
    while cursor <= month:
        window.append(cursor)
        cursor = add_months(cursor, 1)
    by_month = spent(sums, categories, window)

    computed: dict[uuid.UUID, tuple[Budget, BudgetMonth]] = {}
    for budget in budgets:
        history = budget_months(
            limits[budget.id],
            {m: by_month.get((m, budget.category_id), Decimal()) for m in window},
            rollover=budget.rollover,
            overspend=budget.overspend,
            until=month,
        )
        if history and history[-1].month == month:
            computed[budget.category_id] = (budget, history[-1])

    def out(category: CategoryInfo, children: list[schemas.BudgetOut]) -> schemas.BudgetOut:
        budget, current = computed[category.id]
        return schemas.BudgetOut(
            category_id=category.id,
            name=category.name,
            group_id=category.parent_id,
            rollover=budget.rollover,
            overspend=budget.overspend,
            starts_on=min(starts_on for starts_on, _ in limits[budget.id]),
            limit=cents(current.limit),
            carried_in=cents(current.carried_in),
            available=cents(current.available),
            spent=cents(current.spent),
            remaining=cents(current.remaining),
            children=children,
        )

    def order(category: CategoryInfo) -> tuple[int, int, str]:
        group = categories[category.group_id]
        return (group.position, category.position if category.parent_id else -1, category.name)

    top: list[schemas.BudgetOut] = []
    for category in sorted((categories[id_] for id_ in computed), key=order):
        if category.parent_id is not None and category.parent_id in computed:
            continue  # a sub-limit, listed under its group
        children = (
            [
                out(child, [])
                for child in sorted(
                    (categories[id_] for id_ in computed),
                    key=order,
                )
                if child.parent_id == category.id
            ]
            if category.parent_id is None
            else []
        )
        top.append(out(category, children))

    all_expenses = sum(
        (
            by_month.get((month, c.id), Decimal())
            for c in categories.values()
            if c.parent_id is None and c.kind == CategoryKind.EXPENSE
        ),
        Decimal(),
    )
    covered = sum((budget.spent for budget in top), Decimal())
    return schemas.BudgetsOut(
        month=month,
        budgets=top,
        total_limit=sum((b.limit for b in top), Decimal()),
        total_available=sum((b.available for b in top), Decimal()),
        total_spent=covered,
        unbudgeted=cents(all_expenses) - covered,
        uncategorized=cents(-sums.uncategorized.get((month, TransactionKind.EXPENSE), Decimal())),
        unconverted=sums.unconverted,
    )
