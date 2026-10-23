"""Insights: spending by category, cash flow and net worth, computed on read (ADR-0007).

Everything is in euros and counts the accounts of the chosen view (finance/scoping.py):
"personal" (Mine, the default) or "household".
"""

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Query

from hubnisio.finance import schemas
from hubnisio.finance.deps import CurrentPrincipal, DbSession
from hubnisio.finance.insights.net_worth import net_worth
from hubnisio.finance.insights.spending import (
    cash_flow,
    household_categories,
    monthly_sums,
    months_until,
    spending_by_group,
)
from hubnisio.finance.scoping import View

router = APIRouter(prefix="/finance/insights", tags=["finance"])

Months = Annotated[int, Query(ge=1, le=36)]


@router.get("/spending", operation_id="getSpending")
async def get_spending(
    session: DbSession,
    principal: CurrentPrincipal,
    months: Months = 12,
    until: date | None = None,
    view: View = "personal",
) -> schemas.Spending:
    """Spending per expense group and category, per month: booked transactions that aren't
    transfers, net of refunds. The months end with `until`'s (default: this month)."""
    window = months_until(until or date.today(), months)
    sums = await monthly_sums(session, principal, window[0], window[-1], view=view)
    return spending_by_group(sums, await household_categories(session, principal), window)


@router.get("/cash-flow", operation_id="getCashFlow")
async def get_cash_flow(
    session: DbSession,
    principal: CurrentPrincipal,
    months: Months = 12,
    until: date | None = None,
    view: View = "personal",
) -> schemas.CashFlow:
    """Income and spending per month, from the same sums as the spending chart."""
    window = months_until(until or date.today(), months)
    sums = await monthly_sums(session, principal, window[0], window[-1], view=view)
    return cash_flow(sums, await household_categories(session, principal), window)


@router.get("/net-worth", operation_id="getNetWorth")
async def get_net_worth(
    session: DbSession,
    principal: CurrentPrincipal,
    date_from: date | None = None,
    view: View = "personal",
) -> schemas.NetWorthOut:
    """Net worth per day, from the first day every included account has data for (or
    `date_from`, if later) to today, plus each included account's balance today."""
    return await net_worth(session, principal, date.today(), date_from, view=view)
