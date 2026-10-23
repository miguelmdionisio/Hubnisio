"""Budgets: monthly limits per expense category or group, and one on all spending
(ADR-0007, "Budgets").

Budgets belong to the household, like categories; the spending shown against them counts only
the accounts the principal may see (finance/scoping.py).
"""

import uuid
from datetime import date

from fastapi import APIRouter, HTTPException, Response, status
from sqlalchemy import delete, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from hubnisio.core.auth import Principal
from hubnisio.finance import schemas
from hubnisio.finance.budgets import budgets_for_month
from hubnisio.finance.deps import CurrentPrincipal, DbSession
from hubnisio.finance.insights.spending import month_start
from hubnisio.finance.models import Budget, BudgetLimit, Category, CategoryKind

router = APIRouter(prefix="/finance", tags=["finance"])


@router.get("/budgets", operation_id="listBudgets")
async def list_budgets(
    session: DbSession, principal: CurrentPrincipal, month: date | None = None
) -> schemas.BudgetsOut:
    """Each budget for `month`'s month (default: this one): its limit, what last month carried
    in, what's available, spent and remaining."""
    return await budgets_for_month(session, principal, month or date.today())


@router.put("/budgets/overall", operation_id="setOverallBudget")
async def set_overall_budget(
    body: schemas.BudgetIn, session: DbSession, principal: CurrentPrincipal
) -> schemas.BudgetSettings:
    """Cap all spending, uncategorized included, from `from_month` on. Works like `setBudget`."""
    budget = await session.scalar(
        select(Budget).where(
            Budget.household_id == principal.household_id, Budget.category_id.is_(None)
        )
    )
    return await _save_budget(session, principal, budget, None, body)


@router.delete(
    "/budgets/overall",
    status_code=status.HTTP_204_NO_CONTENT,
    operation_id="deleteOverallBudget",
)
async def delete_overall_budget(session: DbSession, principal: CurrentPrincipal) -> Response:
    """Remove the overall budget, its past months included."""
    await session.execute(
        delete(Budget).where(
            Budget.household_id == principal.household_id, Budget.category_id.is_(None)
        )
    )
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.put("/budgets/{category_id}", operation_id="setBudget")
async def set_budget(
    category_id: uuid.UUID,
    body: schemas.BudgetIn,
    session: DbSession,
    principal: CurrentPrincipal,
) -> schemas.BudgetSettings:
    """Budget the category from `from_month` on: earlier months keep their amounts, later
    changes are replaced. Rollover and overspend apply to every month."""
    await _expense_category(session, principal, category_id)
    budget = await session.scalar(select(Budget).where(Budget.category_id == category_id))
    return await _save_budget(session, principal, budget, category_id, body)


@router.delete(
    "/budgets/{category_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    operation_id="deleteBudget",
)
async def delete_budget(
    category_id: uuid.UUID, session: DbSession, principal: CurrentPrincipal
) -> Response:
    """Remove the budget, its past months included."""
    await _expense_category(session, principal, category_id)
    await session.execute(delete(Budget).where(Budget.category_id == category_id))
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


async def _save_budget(
    session: AsyncSession,
    principal: Principal,
    budget: Budget | None,
    category_id: uuid.UUID | None,
    body: schemas.BudgetIn,
) -> schemas.BudgetSettings:
    """Create or update the budget (`category_id` None: the overall one), then set its limit
    from `body.from_month`, dropping any later ones."""
    if budget is None:
        budget = Budget(household_id=principal.household_id, category_id=category_id)
        session.add(budget)
    budget.rollover = body.rollover
    budget.overspend = body.overspend
    await session.flush()
    starts_on = month_start(body.from_month)
    await session.execute(
        delete(BudgetLimit).where(
            BudgetLimit.budget_id == budget.id, BudgetLimit.starts_on > starts_on
        )
    )
    await session.execute(
        insert(BudgetLimit)
        .values(budget_id=budget.id, starts_on=starts_on, amount=body.amount)
        .on_conflict_do_update(
            index_elements=["budget_id", "starts_on"], set_={"amount": body.amount}
        )
    )
    limits = list(
        await session.scalars(
            select(BudgetLimit)
            .where(BudgetLimit.budget_id == budget.id)
            .order_by(BudgetLimit.starts_on)
        )
    )
    settings = schemas.BudgetSettings(
        category_id=category_id,
        rollover=budget.rollover,
        overspend=budget.overspend,
        limits=[
            schemas.BudgetLimitOut(starts_on=limit.starts_on, amount=limit.amount)
            for limit in limits
        ],
    )
    await session.commit()
    return settings


async def _expense_category(
    session: AsyncSession, principal: Principal, category_id: uuid.UUID
) -> Category:
    category = await session.scalar(
        select(Category).where(
            Category.id == category_id,
            Category.household_id == principal.household_id,
            or_(Category.user_id.is_(None), Category.user_id == principal.user_id),
        )
    )
    if category is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such category.")
    if category.kind != CategoryKind.EXPENSE:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "Only expense categories can have a budget."
        )
    return category
