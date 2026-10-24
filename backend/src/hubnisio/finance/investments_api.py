"""Investment accounts (ADR-0008): their value, holdings, and dividends and interest by month.

Only the accounts the principal may see are listed (finance/scoping.py), whichever view.
"""

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Query

from hubnisio.finance import schemas
from hubnisio.finance.deps import CurrentPrincipal, DbSession
from hubnisio.finance.insights.investments import investments
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
