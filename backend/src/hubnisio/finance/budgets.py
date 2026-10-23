"""Budgets: monthly limits per category and for all spending, computed on read (ADR-0007,
"Budgets").

A month's money is its limit plus what the previous month carried in. What's left over carries
into the next month only with rollover on; an overspend carries (as a negative) only with
overspend set to carry. A group's budget covers its categories; when a category inside it has a
budget too, that's a sub-limit and totals count the group alone. The overall budget has no
category: it counts everything spent, uncategorized included (`total_spending`).

`compute_budgets` is pure, so whatever can load the sums (a query, a view) can use it.
"""

import uuid
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
    MonthlySums,
    add_months,
    cents,
    household_categories,
    month_start,
    monthly_sums,
    spent,
    total_spending,
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


@dataclass(frozen=True)
class BudgetSpec:
    """A budget as stored; `category_id` is None for the household's overall budget."""

    category_id: uuid.UUID | None
    rollover: bool
    overspend: Overspend
    limits: Sequence[tuple[date, Decimal]]  # (first day of a month, amount)


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
        if budget.category_id is None or budget.category_id in categories
    ]
    limits: dict[uuid.UUID, list[tuple[date, Decimal]]] = {budget.id: [] for budget in budgets}
    for row in await session.scalars(select(BudgetLimit).where(BudgetLimit.budget_id.in_(limits))):
        limits[row.budget_id].append((row.starts_on, row.amount))
    specs = [
        BudgetSpec(budget.category_id, budget.rollover, budget.overspend, limits[budget.id])
        for budget in budgets
    ]
    sums = await monthly_sums(session, principal, first_month(specs, month), month)
    return compute_budgets(month, specs, categories, sums)


def first_month(specs: Sequence[BudgetSpec], month: date) -> date:
    """The earliest month the budgets need sums for, `month` at the latest."""
    return min((starts_on for spec in specs for starts_on, _ in spec.limits), default=month)


def compute_budgets(
    month: date,
    specs: Sequence[BudgetSpec],
    categories: Mapping[uuid.UUID, CategoryInfo],
    sums: MonthlySums,
) -> schemas.BudgetsOut:
    """Each budget for `month`'s month. `specs` are in scope (their categories are in
    `categories`), and `sums` cover every month from `first_month` to `month`."""
    month = month_start(month)
    window = []
    cursor = min(first_month(specs, month), month)
    while cursor <= month:
        window.append(cursor)
        cursor = add_months(cursor, 1)
    by_month = spent(sums, categories, window)

    def current(spec: BudgetSpec, spending: Mapping[date, Decimal]) -> BudgetMonth | None:
        history = budget_months(
            spec.limits, spending, rollover=spec.rollover, overspend=spec.overspend, until=month
        )
        return history[-1] if history and history[-1].month == month else None

    overall: schemas.OverallBudgetOut | None = None
    computed: dict[uuid.UUID, tuple[BudgetSpec, BudgetMonth]] = {}
    for spec in specs:
        if spec.category_id is None:
            everything = {m: total_spending(sums, categories, m) for m in window}
            if (this := current(spec, everything)) is not None:
                overall = schemas.OverallBudgetOut(
                    rollover=spec.rollover,
                    overspend=spec.overspend,
                    starts_on=min(starts_on for starts_on, _ in spec.limits),
                    limit=cents(this.limit),
                    carried_in=cents(this.carried_in),
                    available=cents(this.available),
                    spent=cents(this.spent),
                    remaining=cents(this.remaining),
                )
            continue
        category_id = spec.category_id
        by_category = {m: by_month.get((m, category_id), Decimal()) for m in window}
        if (this := current(spec, by_category)) is not None:
            computed[category_id] = (spec, this)

    def out(category: CategoryInfo, children: list[schemas.BudgetOut]) -> schemas.BudgetOut:
        spec, this = computed[category.id]
        return schemas.BudgetOut(
            category_id=category.id,
            name=category.name,
            group_id=category.parent_id,
            rollover=spec.rollover,
            overspend=spec.overspend,
            starts_on=min(starts_on for starts_on, _ in spec.limits),
            limit=cents(this.limit),
            carried_in=cents(this.carried_in),
            available=cents(this.available),
            spent=cents(this.spent),
            remaining=cents(this.remaining),
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
        overall=overall,
        budgets=top,
        total_limit=sum((b.limit for b in top), Decimal()),
        total_available=sum((b.available for b in top), Decimal()),
        total_spent=covered,
        unbudgeted=cents(all_expenses) - covered,
        uncategorized=cents(-sums.uncategorized.get((month, TransactionKind.EXPENSE), Decimal())),
        unconverted=sums.unconverted,
    )
