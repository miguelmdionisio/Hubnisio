"""Today: one call that composes the figures of Training, Sleep and Recovery and the latest
activities (ADR-0009, "As built in H8"). Nothing is computed here: every part comes from the
same pure functions and loaders as its own page, and the member's own rows only
(health/scoping.py)."""

from dataclasses import dataclass
from datetime import date, datetime, timedelta

from fastapi import APIRouter
from sqlalchemy.ext.asyncio import AsyncSession

from hubnisio.core.auth import Principal
from hubnisio.health.activities_api import list_activities
from hubnisio.health.api import CurrentPrincipal, DbSession
from hubnisio.health.insights import sleep as sleep_insights
from hubnisio.health.insights.recovery import HrvPoint, HrvSummary, Position, Signals, recovery
from hubnisio.health.insights.recovery_loader import load_recovery_facts
from hubnisio.health.insights.sleep import StageShare
from hubnisio.health.insights.training import (
    Band,
    TrainingDay,
    daily_hours,
    load_series,
    summarize,
)
from hubnisio.health.insights.training_loader import load_activity_rows
from hubnisio.health.models import SampleKind
from hubnisio.health.scoping import own_connection
from hubnisio.health.sync import today_in
from hubnisio.health.training_api import TrainingPoint

router = APIRouter(prefix="/health", tags=["health"])

FITNESS_DAYS = 90
WEEK_DAYS = 7
HRV_NIGHTS = 30
RECENT = 5


@dataclass(frozen=True)
class FormFigure:
    form: float | None
    band: Band | None
    fitness: float | None


@dataclass(frozen=True)
class SleepFigure:
    day: date
    last_night: bool  # the night ending today; otherwise the latest the member has
    slept_s: int | None
    score: int | None
    need_minutes: int | None


@dataclass(frozen=True)
class HrvFigure:
    avg7: float | None
    position: Position | None


@dataclass(frozen=True)
class RestingFigure:
    latest: float | None
    avg7: float | None
    change: float | None


@dataclass(frozen=True)
class Figures:
    form: FormFigure
    sleep: SleepFigure | None  # None when the member has no night at all
    hrv: HrvFigure
    resting_hr: RestingFigure


@dataclass(frozen=True)
class WeekSummary:
    days: list[TrainingDay]  # oldest first, hours per sport; 0 on a rest day
    total_hours: float
    average_hours: float  # per day


@dataclass(frozen=True)
class LastNight:
    day: date
    last_night: bool
    started_at: datetime  # local wall-clock time, no zone
    ended_at: datetime
    bed_min: int
    wake_min: int
    slept_s: int | None
    score: int | None
    score_qualifier: str | None
    need_minutes: int | None
    in_bed_s: int
    stages: list[StageShare]  # no timeline: Garmin does not send one


@dataclass(frozen=True)
class HrvNights:
    points: list[HrvPoint]
    summary: HrvSummary


@dataclass(frozen=True)
class RecentActivity:
    id: int
    sport: str
    group: str
    name: str | None
    start: datetime
    distance_m: float | None
    duration_s: float | None
    load: float | None


@dataclass(frozen=True)
class Today:
    today: date
    figures: Figures
    fitness: list[TrainingPoint]  # the last 90 days; empty without activities
    week: WeekSummary
    night: LastNight | None
    hrv: HrvNights
    activities: list[RecentActivity]
    signals: Signals


async def _last_night(session: AsyncSession, principal: Principal, today: date) -> LastNight | None:
    """The latest night with time slept, found and shaped as the Sleep page does."""
    days = await sleep_insights.load_night_days(session, principal)
    if not days:
        return None
    day = days[-1]
    nights = await sleep_insights.load_nights(
        session, principal, day - timedelta(days=sleep_insights.SCORE_BASELINE_NIGHTS), day
    )
    row = next((r for r in nights if r.day == day), None)
    if row is None:
        return None
    heart_rate, hrv, spo2 = [
        await sleep_insights.load_samples(session, principal, kind, row.started_at, row.ended_at)
        for kind in (SampleKind.HEART_RATE, SampleKind.HRV, SampleKind.SPO2)
    ]
    hrv_nights = await sleep_insights.load_hrv_nights(session, principal, day, day)
    found = sleep_insights.night_detail(nights, day, heart_rate, hrv, spo2, hrv_nights.get(day))
    if found is None:
        return None
    return LastNight(
        day=day,
        last_night=day == today,
        started_at=found.started_at,
        ended_at=found.ended_at,
        bed_min=found.bed_min,
        wake_min=found.wake_min,
        slept_s=found.slept_s,
        score=found.score,
        score_qualifier=found.score_qualifier,
        need_minutes=found.need_minutes,
        in_bed_s=found.in_bed_s,
        stages=found.stages,
    )


@router.get("/today", operation_id="getToday")
async def get_today(session: DbSession, principal: CurrentPrincipal) -> Today:
    """The member's day at a glance, composed from what Training, Sleep and Recovery return."""
    connection = await own_connection(session, principal)
    today = today_in(connection.time_zone if connection else None)

    rows = await load_activity_rows(session, principal)
    series = load_series(rows, today)
    summary = summarize(series)
    first = today - timedelta(days=FITNESS_DAYS - 1)
    fitness = [
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
    ]
    week_days = daily_hours(rows, today - timedelta(days=WEEK_DAYS - 1), today)
    total = sum(d.swim + d.bike + d.run + d.strength + d.other for d in week_days)

    facts = await load_recovery_facts(session, principal, today, HRV_NIGHTS)
    recovered = recovery(facts, today, HRV_NIGHTS, summary.form)

    night = await _last_night(session, principal, today)
    listed = await list_activities(
        session, principal, sport=None, from_=None, to=None, q=None, cursor=None, limit=RECENT
    )
    return Today(
        today=today,
        figures=Figures(
            form=FormFigure(summary.form, summary.band, summary.fitness),
            sleep=(
                None
                if night is None
                else SleepFigure(
                    night.day, night.last_night, night.slept_s, night.score, night.need_minutes
                )
            ),
            hrv=HrvFigure(recovered.hrv.summary.avg7, recovered.hrv.summary.position),
            resting_hr=RestingFigure(
                recovered.resting_hr.summary.latest,
                recovered.resting_hr.summary.avg7,
                recovered.resting_hr.summary.change,
            ),
        ),
        fitness=fitness,
        week=WeekSummary(week_days, total, total / WEEK_DAYS),
        night=night,
        hrv=HrvNights(recovered.hrv.points, recovered.hrv.summary),
        activities=[
            RecentActivity(
                a.id, a.sport, a.group, a.name, a.start, a.distance_m, a.duration_s, a.load
            )
            for a in listed.items
        ],
        signals=recovered.signals,
    )
