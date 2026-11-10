"""Reads the member's activities and their derived rows into `ActivityFacts` for `performance`
(through health/scoping.py), with zone 3's floor for runs and the latest weight."""

from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from hubnisio.core.auth import Principal
from hubnisio.health.insights.performance import ActivityFacts, ClimbFacts
from hubnisio.health.models import Activity, ActivityDerived, HeartRateZones, Weight
from hubnisio.health.scoping import mine


async def load_activity_facts(session: AsyncSession, principal: Principal) -> list[ActivityFacts]:
    rows = await session.execute(
        select(Activity, ActivityDerived)
        .outerjoin(
            ActivityDerived,
            (ActivityDerived.user_id == Activity.user_id)
            & (ActivityDerived.activity_id == Activity.activity_id),
        )
        .where(mine(Activity, principal))
        .order_by(Activity.started_at)
    )
    out: list[ActivityFacts] = []
    for activity, derived in rows:
        day = (activity.start_local or activity.started_at).date()
        duration = activity.duration_s if activity.duration_s is not None else activity.elapsed_s
        efforts = (
            {int(metres): float(s) for metres, s in derived.best_efforts.items()}
            if derived is not None and derived.best_efforts
            else None
        )
        climbs = (
            [
                ClimbFacts(
                    distance_m=float(c["distance_m"]),
                    gain_m=float(c["gain_m"]),
                    duration_s=float(c["duration_s"]),
                    grade=float(c["grade"]),
                    vam=float(c["vam"]),
                )
                for c in derived.climbs
            ]
            if derived is not None and derived.climbs
            else []
        )
        out.append(
            ActivityFacts(
                activity_id=activity.activity_id,
                day=day,
                sport=activity.sport,
                name=activity.name,
                distance_m=float(activity.distance_m) if activity.distance_m is not None else None,
                duration_s=float(duration) if duration is not None else None,
                elevation_gain_m=float(activity.elevation_gain_m)
                if activity.elevation_gain_m is not None
                else None,
                avg_hr=float(activity.avg_hr) if activity.avg_hr is not None else None,
                is_parent=activity.is_parent,
                parent_id=activity.parent_id,
                moving_s=derived.moving_s if derived else None,
                hr_threshold=derived.hr_threshold if derived else None,
                power_curve=derived.power_curve if derived else None,
                hr_curve=derived.hr_curve if derived else None,
                speed_curve=derived.speed_curve if derived else None,
                best_efforts=efforts,
                efficiency_factor=derived.efficiency_factor if derived else None,
                steady=derived.steady if derived else None,
                vo2max=derived.vo2max if derived else None,
                climbs=climbs,
            )
        )
    return out


async def load_run_zone3_floor(session: AsyncSession, principal: Principal) -> float | None:
    """Zone 3's floor from the member's running zones, else their default ones."""
    zones = {
        z.sport: z
        for z in await session.scalars(
            select(HeartRateZones).where(mine(HeartRateZones, principal))
        )
    }
    for sport in ("RUNNING", "DEFAULT"):
        zone = zones.get(sport)
        if zone is not None and zone.zone3_floor is not None:
            return float(zone.zone3_floor)
    return None


async def load_weight(session: AsyncSession, principal: Principal, today: date) -> float | None:
    """The latest weigh-in up to today, kg."""
    weight = await session.scalar(
        select(Weight.weight_kg)
        .where(mine(Weight, principal), Weight.day <= today)
        .order_by(Weight.measured_at.desc())
        .limit(1)
    )
    return float(weight) if weight is not None else None
