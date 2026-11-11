"""Training: fitness, fatigue, form, ramp, hours per week, time in zones and monthly totals
(ADR-0009, "As built in H6"). The member's own activities only (health/scoping.py)."""

import enum
from dataclasses import dataclass
from datetime import date, timedelta

from fastapi import APIRouter

from hubnisio.health.api import CurrentPrincipal, DbSession
from hubnisio.health.insights.training import (
    ActivityRow,
    Band,
    TrainingIntensity,
    TrainingMonth,
    TrainingSummary,
    TrainingWeek,
    first_monday,
    intensity,
    load_series,
    monday,
    monthly_totals,
    summarize,
    weekly_hours,
)
from hubnisio.health.insights.training_loader import load_activity_rows
from hubnisio.health.scoping import own_connection
from hubnisio.health.sync import today_in

router = APIRouter(prefix="/health", tags=["health"])


class Period(enum.StrEnum):
    QUARTER = "90"
    HALF = "180"
    YEAR = "365"
    ALL = "all"


@dataclass(frozen=True)
class TrainingPoint:
    day: date
    load: float
    fitness: float
    fatigue: float
    form: float
    band: Band


@dataclass(frozen=True)
class Training:
    period: str
    first_day: date | None  # None without activities
    last_day: date
    summary: TrainingSummary
    points: list[TrainingPoint]
    weeks: list[TrainingWeek]
    average_week_hours: float | None
    intensity: list[TrainingIntensity]
    months: list[TrainingMonth]  # newest first, the current one partial


@router.get("/training", operation_id="getTraining")
async def get_training(
    session: DbSession, principal: CurrentPrincipal, days: Period = Period.QUARTER
) -> Training:
    """The member's training over the period ending today; fitness is computed over all
    history, the period only crops what is returned."""
    connection = await own_connection(session, principal)
    today = today_in(connection.time_zone if connection else None)
    return training(await load_activity_rows(session, principal), today, days)


def training(rows: list[ActivityRow], today: date, days: Period) -> Training:
    """The page's figures from the member's activities (the MCP server calls it too)."""
    series = load_series(rows, today)
    if not series:
        return Training(days.value, None, today, summarize([]), [], [], None, [], [])
    earliest = series[0].day
    if days is Period.ALL:
        first, weeks_start = earliest, monday(earliest)
    else:
        first = max(earliest, today - timedelta(days=int(days.value) - 1))
        weeks_start = first_monday(first)
    weeks = weekly_hours(rows, weeks_start, today)
    return Training(
        period=days.value,
        first_day=first,
        last_day=today,
        summary=summarize(series),
        points=[
            TrainingPoint(
                p.day,
                round(p.load, 1),
                round(p.fitness, 1),
                round(p.fatigue, 1),
                round(p.form, 1),
                p.band,
            )
            for p in series
            if p.day >= first
        ],
        weeks=weeks.weeks,
        average_week_hours=weeks.average,
        intensity=intensity(rows, first, today),
        months=monthly_totals(rows, first, today),
    )
