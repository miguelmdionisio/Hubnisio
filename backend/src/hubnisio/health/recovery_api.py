"""Recovery: HRV against the member's normal range, resting heart rate, Body Battery, stress and
the day's signals (ADR-0009, "As built in H4"). The member's own rows only (health/scoping.py)."""

import enum

from fastapi import APIRouter

from hubnisio.health.api import CurrentPrincipal, DbSession
from hubnisio.health.insights.recovery import Recovery, recovery
from hubnisio.health.insights.recovery_loader import load_recovery_facts
from hubnisio.health.insights.training import current_form
from hubnisio.health.insights.training_loader import load_activity_rows
from hubnisio.health.scoping import own_connection
from hubnisio.health.sync import today_in

router = APIRouter(prefix="/health", tags=["health"])


class Period(enum.IntEnum):
    MONTH = 30
    QUARTER = 90
    YEAR = 365


@router.get("/recovery", operation_id="getRecovery")
async def get_recovery(
    session: DbSession, principal: CurrentPrincipal, days: Period = Period.QUARTER
) -> Recovery:
    """The `days` ending today (the member's own), a day without data as a gap."""
    connection = await own_connection(session, principal)
    today = today_in(connection.time_zone if connection else None)
    facts = await load_recovery_facts(session, principal, today, days.value)
    form = current_form(await load_activity_rows(session, principal), today)
    return recovery(facts, today, days.value, form)
