"""Sleep: one night, trends over many, debt, schedule, and sleep against the next morning's HRV.

Pure functions over rows (`NightRow`, `SampleRow`, `HrvRow`); the `load_*` functions at the
bottom read them through `health/scoping.py`. Garmin sends only seconds per stage, no timeline:
a night's shape is the split by stage plus the overnight readings. A night the watch wasn't
worn is a gap (`None`), never a zero.
"""

import statistics
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from hubnisio.core.auth import Principal
from hubnisio.health.models import HrvNight, Sample, SampleKind, Sleep
from hubnisio.health.scoping import mine

DEBT_NIGHTS = 7
SCORE_BASELINE_NIGHTS = 30
MIN_CORRELATION_PAIRS = 20
# Typical shares of a night, by stage, as (low, high) of the time in bed.
TYPICAL_SHARE = {"deep": (0.15, 0.20), "light": (0.45, 0.55), "rem": (0.20, 0.25)}
STAGES = ("deep", "light", "rem", "awake")


@dataclass(frozen=True)
class NightRow:
    day: date  # the day the night ends (Garmin's calendar date)
    started_at: datetime  # aware
    ended_at: datetime
    utc_offset_minutes: int
    sleep_s: int | None
    deep_s: int | None
    light_s: int | None
    rem_s: int | None
    awake_s: int | None
    awake_count: int | None
    score: int | None
    score_qualifier: str | None
    need_minutes: int | None
    avg_hr: float | None
    avg_respiration: float | None
    min_respiration: float | None
    max_respiration: float | None
    avg_spo2: float | None
    min_spo2: int | None


@dataclass(frozen=True)
class SampleRow:
    at: datetime  # aware
    value: float


@dataclass(frozen=True)
class HrvRow:
    day: date
    last_night_avg: int | None
    last_night_5min_high: int | None


# --- One night ------------------------------------------------------------------------------


@dataclass(frozen=True)
class StageShare:
    stage: str
    seconds: int
    share: float  # of the stages' total, 0 to 1
    typical_low: float | None  # a typical night's share; none for awake
    typical_high: float | None


@dataclass(frozen=True)
class SeriesPoint:
    t: int  # minutes since the night began
    v: float


@dataclass(frozen=True)
class Reading:
    """A measure overnight: its average, its low and high, and the readings through the night."""

    avg: float | None = None
    low: float | None = None
    low_at: int | None = None  # minutes since the night began
    high: float | None = None
    high_at: int | None = None
    series: list[SeriesPoint] = field(default_factory=list)


@dataclass(frozen=True)
class Debt:
    nights: int  # nights counted: those with both a need and time slept
    missing: int  # of the nights asked for, those without
    need_minutes: int
    slept_minutes: int
    debt_minutes: int  # need less slept: negative when ahead


@dataclass(frozen=True)
class Night:
    day: date
    started_at: datetime  # local wall-clock time, naive
    ended_at: datetime
    bed_min: int  # minutes since midnight starting `day`: negative before it
    wake_min: int
    score: int | None
    score_qualifier: str | None
    score_vs_baseline: float | None  # against the average of the 30 nights before
    slept_s: int | None
    need_minutes: int | None
    in_bed_s: int
    awake_count: int | None
    stages: list[StageShare]
    average_slept_minutes: float | None  # the 7 nights up to this one
    debt: Debt
    heart_rate: Reading
    hrv: Reading
    respiration: Reading
    spo2: Reading


def local(moment: datetime, offset_minutes: int) -> datetime:
    """The wall-clock time at the member's place, without a zone."""
    return (moment + timedelta(minutes=offset_minutes)).replace(tzinfo=None)


def _minutes_from_midnight(moment: datetime, day: date) -> int:
    return round((moment - datetime(day.year, day.month, day.day)).total_seconds() / 60)


def stage_shares(row: NightRow) -> list[StageShare]:
    seconds = {"deep": row.deep_s, "light": row.light_s, "rem": row.rem_s, "awake": row.awake_s}
    total = sum(value or 0 for value in seconds.values())
    if total == 0:
        return []
    shares = []
    for stage in STAGES:
        value = seconds[stage] or 0
        low, high = TYPICAL_SHARE.get(stage, (None, None))
        shares.append(StageShare(stage, value, value / total, low, high))
    return shares


def _reading(
    rows: Sequence[SampleRow], start: datetime, end: datetime, average: float | None = None
) -> Reading:
    points = sorted(
        (
            SeriesPoint(round((row.at - start).total_seconds() / 60), row.value)
            for row in rows
            if start <= row.at <= end
        ),
        key=lambda point: point.t,
    )
    if not points:
        return Reading(avg=average)
    low = min(points, key=lambda point: point.v)
    high = max(points, key=lambda point: point.v)
    return Reading(
        avg=average if average is not None else round(statistics.fmean(p.v for p in points), 1),
        low=low.v,
        low_at=low.t,
        high=high.v,
        high_at=high.t,
        series=points,
    )


def _mean(values: Iterable[float]) -> float | None:
    items = list(values)
    return statistics.fmean(items) if items else None


def _worn(row: NightRow) -> bool:
    return row.sleep_s is not None and row.sleep_s > 0


def sleep_debt(rows: Sequence[NightRow], end: date, nights: int = DEBT_NIGHTS) -> Debt:
    """Need less time slept over the `nights` days up to `end`. Only nights with both count; the
    others are `missing`, not zero hours."""
    window = {end - timedelta(days=n) for n in range(nights)}
    counted = [
        row for row in rows if row.day in window and _worn(row) and row.need_minutes is not None
    ]
    need = sum(row.need_minutes or 0 for row in counted)
    slept = round(sum(row.sleep_s or 0 for row in counted) / 60)
    return Debt(
        nights=len(counted),
        missing=nights - len(counted),
        need_minutes=need,
        slept_minutes=slept,
        debt_minutes=need - slept,
    )


def night_detail(
    rows: Sequence[NightRow],
    day: date,
    heart_rate: Sequence[SampleRow] = (),
    hrv: Sequence[SampleRow] = (),
    spo2: Sequence[SampleRow] = (),
    hrv_night: HrvRow | None = None,
) -> Night | None:
    """The night ending on `day`, with `rows` the nights around it (for its 7-night average,
    its debt and the 30-night score baseline). None when the watch wasn't worn."""
    row = next((r for r in rows if r.day == day), None)
    if row is None or not _worn(row):
        return None
    start, end = row.started_at, row.ended_at
    offset = row.utc_offset_minutes
    started, ended = local(start, offset), local(end, offset)
    week = {day - timedelta(days=n) for n in range(DEBT_NIGHTS)}
    before = {day - timedelta(days=n) for n in range(1, SCORE_BASELINE_NIGHTS + 1)}
    baseline = _mean(r.score for r in rows if r.day in before and r.score is not None)
    hrv_reading = _reading(hrv, start, end, hrv_night.last_night_avg if hrv_night else None)
    if hrv_night and hrv_night.last_night_5min_high is not None and hrv_reading.high is None:
        hrv_reading = Reading(avg=hrv_reading.avg, high=float(hrv_night.last_night_5min_high))
    score_delta = (
        round(row.score - baseline, 1) if row.score is not None and baseline is not None else None
    )
    return Night(
        day=day,
        started_at=started,
        ended_at=ended,
        bed_min=_minutes_from_midnight(started, day),
        wake_min=_minutes_from_midnight(ended, day),
        score=row.score,
        score_qualifier=row.score_qualifier,
        score_vs_baseline=score_delta,
        slept_s=row.sleep_s,
        need_minutes=row.need_minutes,
        in_bed_s=round((end - start).total_seconds()),
        awake_count=row.awake_count,
        stages=stage_shares(row),
        average_slept_minutes=_mean(
            (r.sleep_s or 0) / 60 for r in rows if r.day in week and _worn(r)
        ),
        debt=sleep_debt(rows, day),
        heart_rate=_reading(heart_rate, start, end, row.avg_hr),
        hrv=hrv_reading,
        respiration=Reading(
            avg=row.avg_respiration, low=row.min_respiration, high=row.max_respiration
        ),
        spo2=(
            _reading(spo2, start, end, row.avg_spo2)
            if spo2
            else Reading(avg=row.avg_spo2, low=row.min_spo2)
        ),
    )


def neighbours(days: Iterable[date], day: date) -> tuple[date | None, date | None]:
    """The nearest night before and after `day` among `days`."""
    ordered = sorted(set(days))
    before = [d for d in ordered if d < day]
    after = [d for d in ordered if d > day]
    return (before[-1] if before else None, after[0] if after else None)


# --- Trends ---------------------------------------------------------------------------------


@dataclass(frozen=True)
class NightPoint:
    """One day of a trend: its night, or a gap (`worn` false, everything else none)."""

    day: date
    worn: bool
    slept_s: int | None = None
    deep_s: int | None = None
    light_s: int | None = None
    rem_s: int | None = None
    awake_s: int | None = None
    need_minutes: int | None = None
    score: int | None = None
    bed_min: int | None = None
    wake_min: int | None = None


@dataclass(frozen=True)
class Spread:
    """Bedtime and wake time over the nights: the average and the spread (population standard
    deviation), in minutes since midnight starting the wake day. Weekend is a night ending on a
    Saturday or Sunday."""

    nights: int
    bed_avg: float | None
    bed_sd: float | None
    wake_avg: float | None
    wake_sd: float | None
    weekday_bed_avg: float | None
    weekday_wake_avg: float | None
    weekend_bed_avg: float | None
    weekend_wake_avg: float | None


@dataclass(frozen=True)
class HrvPair:
    day: date  # the night's day; the HRV is the next morning's
    hours: float
    hrv: int


@dataclass(frozen=True)
class Correlation:
    pairs: list[HrvPair]
    # Present only with MIN_CORRELATION_PAIRS or more pairs.
    slope: float | None  # ms of HRV per hour slept
    intercept: float | None
    r: float | None


@dataclass(frozen=True)
class WeekdayScore:
    weekday: int  # 0 Monday to 6 Sunday, of the day the night ends
    nights: int
    score: float | None


@dataclass(frozen=True)
class Trends:
    nights: int  # days in the window
    start: date
    end: date
    points: list[NightPoint]
    nights_worn: int
    average_slept_minutes: float | None
    average_need_minutes: float | None
    schedule: Spread
    correlation: Correlation
    weekday_scores: list[WeekdayScore]


def window_days(end: date, nights: int) -> list[date]:
    return [end - timedelta(days=nights - 1 - n) for n in range(nights)]


def _sd(values: Sequence[float]) -> float | None:
    return statistics.pstdev(values) if len(values) >= 2 else None


def schedule(points: Sequence[NightPoint]) -> Spread:
    worn = [p for p in points if p.bed_min is not None and p.wake_min is not None]
    bed = [float(p.bed_min or 0) for p in worn]
    wake = [float(p.wake_min or 0) for p in worn]
    weekend = [p for p in worn if p.day.weekday() >= 5]
    weekday = [p for p in worn if p.day.weekday() < 5]
    return Spread(
        nights=len(worn),
        bed_avg=_mean(bed),
        bed_sd=_sd(bed),
        wake_avg=_mean(wake),
        wake_sd=_sd(wake),
        weekday_bed_avg=_mean(p.bed_min or 0 for p in weekday),
        weekday_wake_avg=_mean(p.wake_min or 0 for p in weekday),
        weekend_bed_avg=_mean(p.bed_min or 0 for p in weekend),
        weekend_wake_avg=_mean(p.wake_min or 0 for p in weekend),
    )


def sleep_vs_hrv(
    points: Sequence[NightPoint], hrv_by_day: Mapping[date, int | None]
) -> Correlation:
    """Hours slept on each night against the HRV of the morning after (the next day's reading),
    a least-squares line and Pearson's r once there are enough pairs."""
    pairs = []
    for p in points:
        hrv = hrv_by_day.get(p.day + timedelta(days=1))
        if p.slept_s and hrv is not None:
            pairs.append(HrvPair(p.day, p.slept_s / 3600, hrv))
    if len(pairs) < MIN_CORRELATION_PAIRS:
        return Correlation(pairs, None, None, None)
    xs = [pair.hours for pair in pairs]
    ys = [float(pair.hrv) for pair in pairs]
    mean_x, mean_y = statistics.fmean(xs), statistics.fmean(ys)
    sxx = sum((x - mean_x) ** 2 for x in xs)
    syy = sum((y - mean_y) ** 2 for y in ys)
    sxy = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys, strict=True))
    if sxx == 0:
        return Correlation(pairs, None, None, None)
    slope = sxy / sxx
    r = sxy / (sxx * syy) ** 0.5 if syy > 0 else None
    return Correlation(pairs, slope, mean_y - slope * mean_x, r)


def score_by_weekday(points: Sequence[NightPoint]) -> list[WeekdayScore]:
    out = []
    for weekday in range(7):
        scores = [p.score for p in points if p.score is not None and p.day.weekday() == weekday]
        out.append(WeekdayScore(weekday, len(scores), _mean(scores)))
    return out


def trends(
    rows: Sequence[NightRow], end: date, nights: int, hrv_by_day: Mapping[date, int | None]
) -> Trends:
    """The `nights` days ending on `end`: a point per day, gaps where the watch wasn't worn."""
    by_day = {row.day: row for row in rows if _worn(row)}
    points: list[NightPoint] = []
    for day in window_days(end, nights):
        row = by_day.get(day)
        if row is None:
            points.append(NightPoint(day, worn=False))
            continue
        started = local(row.started_at, row.utc_offset_minutes)
        ended = local(row.ended_at, row.utc_offset_minutes)
        points.append(
            NightPoint(
                day,
                worn=True,
                slept_s=row.sleep_s,
                deep_s=row.deep_s,
                light_s=row.light_s,
                rem_s=row.rem_s,
                awake_s=row.awake_s,
                need_minutes=row.need_minutes,
                score=row.score,
                bed_min=_minutes_from_midnight(started, day),
                wake_min=_minutes_from_midnight(ended, day),
            )
        )
    worn = [p for p in points if p.worn]
    return Trends(
        nights=nights,
        start=points[0].day,
        end=end,
        points=points,
        nights_worn=len(worn),
        average_slept_minutes=_mean((p.slept_s or 0) / 60 for p in worn),
        average_need_minutes=_mean(p.need_minutes for p in worn if p.need_minutes is not None),
        schedule=schedule(points),
        correlation=sleep_vs_hrv(points, hrv_by_day),
        weekday_scores=score_by_weekday(points),
    )


# --- Loading --------------------------------------------------------------------------------


def _float(value: Decimal | None) -> float | None:
    return float(value) if value is not None else None


def _row(sleep: Sleep) -> NightRow:
    return NightRow(
        day=sleep.day,
        started_at=sleep.started_at,
        ended_at=sleep.ended_at,
        utc_offset_minutes=sleep.utc_offset_minutes or 0,
        sleep_s=sleep.sleep_s,
        deep_s=sleep.deep_s,
        light_s=sleep.light_s,
        rem_s=sleep.rem_s,
        awake_s=sleep.awake_s,
        awake_count=sleep.awake_count,
        score=sleep.score,
        score_qualifier=sleep.score_qualifier,
        need_minutes=sleep.need_minutes,
        avg_hr=_float(sleep.avg_hr),
        avg_respiration=_float(sleep.avg_respiration),
        min_respiration=_float(sleep.min_respiration),
        max_respiration=_float(sleep.max_respiration),
        avg_spo2=_float(sleep.avg_spo2),
        min_spo2=sleep.min_spo2,
    )


async def load_nights(
    session: AsyncSession, principal: Principal, start: date | None = None, end: date | None = None
) -> list[NightRow]:
    """The principal's own nights between two days (inclusive), oldest first."""
    query = select(Sleep).where(mine(Sleep, principal)).order_by(Sleep.day)
    if start is not None:
        query = query.where(Sleep.day >= start)
    if end is not None:
        query = query.where(Sleep.day <= end)
    return [_row(sleep) for sleep in await session.scalars(query)]


async def load_night_days(session: AsyncSession, principal: Principal) -> list[date]:
    """The days the principal has a night with time slept, oldest first."""
    return list(
        await session.scalars(
            select(Sleep.day).where(mine(Sleep, principal), Sleep.sleep_s > 0).order_by(Sleep.day)
        )
    )


async def load_samples(
    session: AsyncSession, principal: Principal, kind: SampleKind, start: datetime, end: datetime
) -> list[SampleRow]:
    rows = await session.execute(
        select(Sample.at, Sample.value)
        .where(mine(Sample, principal), Sample.kind == kind, Sample.at.between(start, end))
        .order_by(Sample.at)
    )
    return [SampleRow(at, float(value)) for at, value in rows]


async def load_hrv_nights(
    session: AsyncSession, principal: Principal, start: date, end: date
) -> dict[date, HrvRow]:
    rows = await session.scalars(
        select(HrvNight).where(mine(HrvNight, principal), HrvNight.day.between(start, end))
    )
    return {row.day: HrvRow(row.day, row.last_night_avg, row.last_night_5min_high) for row in rows}
