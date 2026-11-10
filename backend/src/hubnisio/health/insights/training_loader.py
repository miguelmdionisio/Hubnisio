"""Reads the member's activities into `ActivityRow`s for `training` (through health/scoping.py).
Multisport parents are left out: their legs are the rows."""

from sqlalchemy import false, select
from sqlalchemy.ext.asyncio import AsyncSession

from hubnisio.core.auth import Principal
from hubnisio.health.insights.training import ActivityRow
from hubnisio.health.models import Activity, ActivityDerived
from hubnisio.health.scoping import mine


async def load_activity_rows(session: AsyncSession, principal: Principal) -> list[ActivityRow]:
    result = await session.execute(
        select(Activity, ActivityDerived.hr_load, ActivityDerived.hr_zone_s)
        .outerjoin(
            ActivityDerived,
            (ActivityDerived.user_id == Activity.user_id)
            & (ActivityDerived.activity_id == Activity.activity_id),
        )
        .where(mine(Activity, principal), Activity.is_parent == false())
        .order_by(Activity.started_at)
    )
    rows: list[ActivityRow] = []
    for activity, load, zones in result:
        start = activity.start_local or activity.started_at
        seconds = activity.duration_s or activity.moving_s or 0
        rows.append(
            ActivityRow(
                day=start.date(),
                sport=activity.sport,
                duration_s=float(seconds),
                distance_m=None if activity.distance_m is None else float(activity.distance_m),
                climb_m=(
                    None if activity.elevation_gain_m is None else float(activity.elevation_gain_m)
                ),
                load=load,
                zone_s=zones,
            )
        )
    return rows
