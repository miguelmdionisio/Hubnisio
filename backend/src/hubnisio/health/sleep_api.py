"""Sleep HTTP endpoints: one night, and the trends over 30, 90 or 365 nights.

Member-only: every query goes through `health/scoping.py`, so another member sees nothing.
The numbers come from `health/insights/sleep.py`.
"""

import enum
from datetime import date, datetime, timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from hubnisio.core.auth import Principal, get_principal
from hubnisio.core.db import get_session
from hubnisio.health.insights import sleep as insights
from hubnisio.health.models import SampleKind

router = APIRouter(prefix="/health/sleep", tags=["health"])

DbSession = Annotated[AsyncSession, Depends(get_session)]
CurrentPrincipal = Annotated[Principal, Depends(get_principal)]

NIGHT_WINDOW = insights.SCORE_BASELINE_NIGHTS


class Nights(enum.IntEnum):
    MONTH = 30
    QUARTER = 90
    YEAR = 365


class _Out(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class StageShareOut(_Out):
    stage: Literal["deep", "light", "rem", "awake"]
    seconds: int
    share: float
    typical_low: float | None
    typical_high: float | None


class SeriesPointOut(_Out):
    t: int  # minutes since the night began
    v: float


class ReadingOut(_Out):
    avg: float | None
    low: float | None
    low_at: int | None
    high: float | None
    high_at: int | None
    series: list[SeriesPointOut]


class DebtOut(_Out):
    nights: int
    missing: int
    need_minutes: int
    slept_minutes: int
    debt_minutes: int


class NightOut(_Out):
    day: date
    started_at: datetime  # local wall-clock time, no zone
    ended_at: datetime
    bed_min: int
    wake_min: int
    score: int | None
    score_qualifier: str | None
    score_vs_baseline: float | None
    slept_s: int | None
    need_minutes: int | None
    in_bed_s: int
    awake_count: int | None
    stages: list[StageShareOut]
    average_slept_minutes: float | None
    debt: DebtOut
    heart_rate: ReadingOut
    hrv: ReadingOut
    respiration: ReadingOut
    spo2: ReadingOut


class SleepNight(BaseModel):
    """A night and the nearest nights either side of it. `night` is none when the member has no
    night on that day (or none at all)."""

    day: date | None
    night: NightOut | None
    previous_day: date | None
    next_day: date | None


class NightPointOut(_Out):
    day: date
    worn: bool
    slept_s: int | None
    deep_s: int | None
    light_s: int | None
    rem_s: int | None
    awake_s: int | None
    need_minutes: int | None
    score: int | None
    bed_min: int | None
    wake_min: int | None


class SpreadOut(_Out):
    nights: int
    bed_avg: float | None
    bed_sd: float | None
    wake_avg: float | None
    wake_sd: float | None
    weekday_bed_avg: float | None
    weekday_wake_avg: float | None
    weekend_bed_avg: float | None
    weekend_wake_avg: float | None


class HrvPairOut(_Out):
    day: date
    hours: float
    hrv: int


class CorrelationOut(_Out):
    pairs: list[HrvPairOut]
    slope: float | None
    intercept: float | None
    r: float | None


class WeekdayScoreOut(_Out):
    weekday: int
    nights: int
    score: float | None


class SleepTrends(_Out):
    nights: int
    start: date
    end: date
    points: list[NightPointOut]
    nights_worn: int
    average_slept_minutes: float | None
    average_need_minutes: float | None
    schedule: SpreadOut
    correlation: CorrelationOut
    weekday_scores: list[WeekdayScoreOut]


@router.get("/night", operation_id="getSleepNight")
async def get_sleep_night(
    session: DbSession,
    principal: CurrentPrincipal,
    date_: Annotated[date | None, Query(alias="date")] = None,
) -> SleepNight:
    """The night ending on `date` (default: the latest), with the nights before and after it."""
    days = await insights.load_night_days(session, principal)
    day = date_ or (days[-1] if days else None)
    if day is None:
        return SleepNight(day=None, night=None, previous_day=None, next_day=None)
    previous_day, next_day = insights.neighbours(days, day)
    rows = await insights.load_nights(session, principal, day - timedelta(days=NIGHT_WINDOW), day)
    row = next((r for r in rows if r.day == day), None)
    night = None
    if row is not None:
        heart_rate, hrv, spo2 = [
            await insights.load_samples(session, principal, kind, row.started_at, row.ended_at)
            for kind in (SampleKind.HEART_RATE, SampleKind.HRV, SampleKind.SPO2)
        ]
        hrv_nights = await insights.load_hrv_nights(session, principal, day, day)
        found = insights.night_detail(rows, day, heart_rate, hrv, spo2, hrv_nights.get(day))
        night = NightOut.model_validate(found) if found else None
    return SleepNight(day=day, night=night, previous_day=previous_day, next_day=next_day)


@router.get("/trends", operation_id="getSleepTrends")
async def get_sleep_trends(
    session: DbSession, principal: CurrentPrincipal, nights: Nights = Nights.MONTH
) -> SleepTrends:
    """The last `nights` days up to the latest night: stages and need per night, the schedule,
    sleep against the next morning's HRV, and the score by weekday. Gaps are nights the watch
    wasn't worn."""
    count = int(nights)
    days = await insights.load_night_days(session, principal)
    end = days[-1] if days else date.today()
    start = end - timedelta(days=count - 1)
    rows = await insights.load_nights(session, principal, start, end)
    hrv_nights = await insights.load_hrv_nights(
        session, principal, start + timedelta(days=1), end + timedelta(days=1)
    )
    hrv = {day: row.last_night_avg for day, row in hrv_nights.items()}
    return SleepTrends.model_validate(insights.trends(rows, end, count, hrv))
