"""Insights: spending by category, cash flow and net worth, computed on read (ADR-0007).

Everything is in euros and scoped to the accounts the principal may see (finance/scoping.py).
"""

import uuid
from datetime import date
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Query

from hubnisio.finance import schemas
from hubnisio.finance.deps import CurrentPrincipal, DbSession
from hubnisio.finance.insights.net_worth import net_worth
from hubnisio.finance.insights.spending import (
    cents,
    household_categories,
    monthly_sums,
    months_until,
    spent,
    total_spending,
)
from hubnisio.finance.models import CategoryKind, TransactionKind

router = APIRouter(prefix="/finance/insights", tags=["finance"])

Months = Annotated[int, Query(ge=1, le=36)]


@router.get("/spending", operation_id="getSpending")
async def get_spending(
    session: DbSession,
    principal: CurrentPrincipal,
    months: Months = 12,
    until: date | None = None,
) -> schemas.Spending:
    """Spending per expense group and category, per month: booked transactions that aren't
    transfers, net of refunds. The months end with `until`'s (default: this month)."""
    window = months_until(until or date.today(), months)
    sums = await monthly_sums(session, principal, window[0], window[-1])
    categories = await household_categories(session, principal)
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
        months=window,
        groups=groups,
        uncategorized=[
            cents(-sums.uncategorized.get((month, TransactionKind.EXPENSE), Decimal()))
            for month in window
        ],
        unconverted=sums.unconverted,
    )


@router.get("/cash-flow", operation_id="getCashFlow")
async def get_cash_flow(
    session: DbSession,
    principal: CurrentPrincipal,
    months: Months = 12,
    until: date | None = None,
) -> schemas.CashFlow:
    """Income and spending per month, from the same sums as the spending chart."""
    window = months_until(until or date.today(), months)
    sums = await monthly_sums(session, principal, window[0], window[-1])
    categories = await household_categories(session, principal)
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


@router.get("/net-worth", operation_id="getNetWorth")
async def get_net_worth(
    session: DbSession, principal: CurrentPrincipal, date_from: date | None = None
) -> schemas.NetWorthOut:
    """Net worth per day, from the first day every included account has data for (or
    `date_from`, if later) to today, plus each included account's balance today."""
    return await net_worth(session, principal, date.today(), date_from)
