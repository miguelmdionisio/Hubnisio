"""Performance: season curves, critical power and speed, swim threshold, VO2max, race
predictions, easy-run efficiency, the bike and records (ADR-0009, "As built in H7"). The
member's own rows only (health/scoping.py)."""

from fastapi import APIRouter

from hubnisio.health.api import CurrentPrincipal, DbSession
from hubnisio.health.insights.performance import Performance, Period, performance
from hubnisio.health.insights.performance_loader import (
    load_activity_facts,
    load_run_zone3_floor,
    load_weight,
)
from hubnisio.health.scoping import own_connection
from hubnisio.health.sync import today_in

router = APIRouter(prefix="/health", tags=["health"])


@router.get("/performance", operation_id="getPerformance")
async def get_performance(
    session: DbSession, principal: CurrentPrincipal, period: Period = "season"
) -> Performance:
    """This season (the calendar year), the last 90 days or all time, to today."""
    connection = await own_connection(session, principal)
    today = today_in(connection.time_zone if connection else None)
    rows = await load_activity_facts(session, principal)
    return performance(
        rows,
        today,
        period,
        zone3_floor=await load_run_zone3_floor(session, principal),
        weight_kg=await load_weight(session, principal, today),
    )
