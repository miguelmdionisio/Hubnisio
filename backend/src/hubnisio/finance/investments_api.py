"""Investment accounts (ADR-0008): their value, holdings, dividends and interest by month, and
their returns over a period.

Only the accounts the principal may see are listed (finance/scoping.py), whichever view.
"""

from datetime import date
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status

from hubnisio.finance import schemas
from hubnisio.finance.deps import CurrentPrincipal, DbSession
from hubnisio.finance.insights.investments import investments
from hubnisio.finance.insights.returns import investment_returns
from hubnisio.finance.insights.spending import months_until

router = APIRouter(prefix="/finance/investments", tags=["finance"])


@router.get("", operation_id="getInvestments")
async def get_investments(
    session: DbSession,
    principal: CurrentPrincipal,
    months: Annotated[int, Query(ge=1, le=36)] = 12,
    until: date | None = None,
) -> schemas.InvestmentsOut:
    """Each investment account as of its latest sync, with its dividends and interest per
    month. The months end with `until`'s (default: this month)."""
    return await investments(session, principal, months_until(until or date.today(), months))


@router.get("/returns", operation_id="getInvestmentReturns")
async def get_investment_returns(
    session: DbSession,
    principal: CurrentPrincipal,
    date_from: date | None = None,
    date_to: date | None = None,
) -> schemas.InvestmentReturnsOut:
    """Each investment account's returns from `date_from` (default: its first movement) to
    `date_to` (default: today): the breakdown of its result, the time- and money-weighted
    returns, and its value against net deposits on each day."""
    if date_from is not None and date_to is not None and date_from > date_to:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "The period ends before it starts."
        )
    return await investment_returns(session, principal, date.today(), date_from, date_to)
