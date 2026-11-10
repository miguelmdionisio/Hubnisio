"""Reads the member's weigh-ins, goal and fitness ages for `body` (through health/scoping.py)."""

from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from hubnisio.core.auth import Principal
from hubnisio.health.insights.body import AgeReading, WeighIn
from hubnisio.health.models import FitnessAge, Weight, WeightGoal
from hubnisio.health.scoping import mine


def _float(value: Decimal | None) -> float | None:
    return None if value is None else float(value)


async def load_body_facts(
    session: AsyncSession, principal: Principal
) -> tuple[list[WeighIn], list[AgeReading], float | None]:
    """Every weigh-in and fitness age stored (a handful a year), and the goal if set."""
    weigh_ins = [
        WeighIn(
            measured_at=w.measured_at,
            day=w.day,
            weight_kg=float(w.weight_kg),
            bmi=_float(w.bmi),
            body_fat_pct=_float(w.body_fat_pct),
        )
        for w in await session.scalars(select(Weight).where(mine(Weight, principal)))
    ]
    readings = [
        AgeReading(
            day=a.day,
            fitness_age=_float(a.fitness_age),
            chronological_age=a.chronological_age,
            resting_hr=a.resting_hr,
            bmi=_float(a.bmi),
            vigorous_days_avg=_float(a.vigorous_days_avg),
            vigorous_minutes_avg=_float(a.vigorous_minutes_avg),
        )
        for a in await session.scalars(select(FitnessAge).where(mine(FitnessAge, principal)))
    ]
    goal = await session.scalar(select(WeightGoal.target_kg).where(mine(WeightGoal, principal)))
    return weigh_ins, readings, _float(goal)
