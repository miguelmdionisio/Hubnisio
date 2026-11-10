"""Body over time: weigh-ins against the goal, and Garmin's fitness age against the member's
real age (ADR-0009, "As built in H8"). Pure: rows in, figures out.

Weigh-ins are rare (a handful a year), so every figure works with none, one or two of them: the
page decides what to draw from the counts. A day with two weigh-ins keeps the later one. BMI is
only what the stored weigh-in says; nothing is derived from a height that isn't stored.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta


@dataclass(frozen=True)
class WeighIn:
    measured_at: datetime
    day: date
    weight_kg: float
    bmi: float | None = None
    body_fat_pct: float | None = None


@dataclass(frozen=True)
class AgeReading:
    day: date
    fitness_age: float | None
    chronological_age: int | None = None
    resting_hr: int | None = None
    bmi: float | None = None
    vigorous_days_avg: float | None = None
    vigorous_minutes_avg: float | None = None


@dataclass(frozen=True)
class WeightPoint:
    day: date
    kg: float
    bmi: float | None
    body_fat_pct: float | None


@dataclass(frozen=True)
class WeightSummary:
    count: int  # weigh-ins in the window
    latest_kg: float | None  # the latest weigh-in, even before the window
    latest_day: date | None
    # Last minus the first weigh-in of the window; none under two weigh-ins.
    change_kg: float | None
    bmi: float | None  # as stored with the latest weigh-in
    to_goal_kg: float | None  # latest minus the goal


@dataclass(frozen=True)
class WeightOut:
    points: list[WeightPoint]
    goal_kg: float | None
    summary: WeightSummary


@dataclass(frozen=True)
class AgePoint:
    day: date
    fitness_age: float | None
    chronological_age: int | None


@dataclass(frozen=True)
class AgeLatest:
    day: date
    fitness_age: float
    chronological_age: int | None
    difference: float | None  # fitness age minus real age: negative is younger
    resting_hr: int | None
    bmi: float | None
    vigorous_days_avg: float | None
    vigorous_minutes_avg: float | None


@dataclass(frozen=True)
class FitnessAgeOut:
    points: list[AgePoint]
    latest: AgeLatest | None


@dataclass(frozen=True)
class Body:
    days: int | None  # None: all time
    first_day: date | None
    last_day: date
    weight: WeightOut
    fitness_age: FitnessAgeOut


def body(
    weigh_ins: Sequence[WeighIn],
    readings: Sequence[AgeReading],
    goal_kg: float | None,
    today: date,
    days: int | None,
) -> Body:
    """The window is the `days` ending `today`, or everything stored when `days` is None."""
    ordered = sorted((w for w in weigh_ins if w.day <= today), key=lambda w: (w.day, w.measured_at))
    latest_by_day = {w.day: w for w in ordered}  # a later weigh-in replaces the day's earlier
    ages = sorted((a for a in readings if a.day <= today), key=lambda a: a.day)
    start = today - timedelta(days=days - 1) if days is not None else None

    def inside(day: date) -> bool:
        return start is None or day >= start

    points = [
        WeightPoint(w.day, w.weight_kg, w.bmi, w.body_fat_pct)
        for w in latest_by_day.values()
        if inside(w.day)
    ]
    latest = list(latest_by_day.values())[-1] if latest_by_day else None
    age_points = [
        AgePoint(a.day, a.fitness_age, a.chronological_age) for a in ages if inside(a.day)
    ]
    first_day = start
    if first_day is None:
        first_day = min([p.day for p in points] + [p.day for p in age_points], default=None)

    newest = next((a for a in reversed(ages) if a.fitness_age is not None), None)
    age_latest = None
    if newest is not None and newest.fitness_age is not None:
        real = newest.chronological_age
        age_latest = AgeLatest(
            day=newest.day,
            fitness_age=newest.fitness_age,
            chronological_age=real,
            difference=round(newest.fitness_age - real, 1) if real is not None else None,
            resting_hr=newest.resting_hr,
            bmi=newest.bmi,
            vigorous_days_avg=newest.vigorous_days_avg,
            vigorous_minutes_avg=newest.vigorous_minutes_avg,
        )
    return Body(
        days=days,
        first_day=first_day,
        last_day=today,
        weight=WeightOut(
            points=points,
            goal_kg=goal_kg,
            summary=WeightSummary(
                count=len(points),
                latest_kg=latest.weight_kg if latest else None,
                latest_day=latest.day if latest else None,
                change_kg=round(points[-1].kg - points[0].kg, 1) if len(points) >= 2 else None,
                bmi=latest.bmi if latest else None,
                to_goal_kg=(
                    round(latest.weight_kg - goal_kg, 1) if latest and goal_kg is not None else None
                ),
            ),
        ),
        fitness_age=FitnessAgeOut(points=age_points, latest=age_latest),
    )
