"""Body: weigh-ins against the goal and fitness age (ADR-0009, "As built in H8"). The member's
own rows only (health/scoping.py)."""

import enum

from fastapi import APIRouter

from hubnisio.health.api import CurrentPrincipal, DbSession
from hubnisio.health.insights.body import Body, body
from hubnisio.health.insights.body_loader import load_body_facts
from hubnisio.health.scoping import own_connection
from hubnisio.health.sync import today_in

router = APIRouter(prefix="/health", tags=["health"])


class Period(enum.StrEnum):
    QUARTER = "90"
    YEAR = "365"
    ALL = "all"


@router.get("/body", operation_id="getBody")
async def get_body(
    session: DbSession, principal: CurrentPrincipal, days: Period = Period.YEAR
) -> Body:
    """The `days` ending today (the member's own), or everything stored."""
    connection = await own_connection(session, principal)
    today = today_in(connection.time_zone if connection else None)
    weigh_ins, readings, goal = await load_body_facts(session, principal)
    return body(weigh_ins, readings, goal, today, None if days is Period.ALL else int(days.value))
