"""Training: fitness, fatigue and form from the member's heart-rate load, hours per week by sport,
time in heart-rate zones, monthly totals (ADR-0009, "As built in H6"). Pure: rows in, figures out.

Fitness (CTL) and fatigue (ATL) are exponentially weighted averages of the daily load with time
constants of 42 and 7 days, `x = x_yesterday + (load - x_yesterday) / tc`, seeded at 0 on the
member's first activity and run over all history: the chosen period only crops what is shown.
Form is yesterday's fitness less yesterday's fatigue. A multisport parent is not a row: the
loader leaves it out, so its legs are not counted twice.
"""

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Literal

from hubnisio.health.insights.activity import Family, family

CTL_DAYS = 42
ATL_DAYS = 7
RAMP_DAYS = 28
CHANGE_DAYS = 42
RAMP_SAFE = 6.0  # fitness points a week; above it the ramp is steep

# Form bands: fresh above FRESH_ABOVE, neutral down to NEUTRAL_FLOOR, optimal down to
# OPTIMAL_FLOOR, high risk below.
FRESH_ABOVE = 5.0
NEUTRAL_FLOOR = -10.0
OPTIMAL_FLOOR = -30.0

Band = Literal["fresh", "neutral", "optimal", "high_risk"]
Sport = Literal["swim", "bike", "run", "strength", "other"]
SPORTS: tuple[Sport, ...] = ("swim", "bike", "run", "strength", "other")


def sport_of(type_key: str | None) -> Sport:
    """The sport group of a Garmin activity type key."""
    match family(type_key):
        case Family.RUN:
            return "run"
        case Family.RIDE:
            return "bike"
        case Family.SWIM:
            return "swim"
        case Family.OTHER:
            key = (type_key or "").lower()
            return "strength" if "strength" in key or key == "hiit" else "other"


def band_of(form: float) -> Band:
    if form > FRESH_ABOVE:
        return "fresh"
    if form >= NEUTRAL_FLOOR:
        return "neutral"
    if form >= OPTIMAL_FLOOR:
        return "optimal"
    return "high_risk"


@dataclass(frozen=True, slots=True)
class ActivityRow:
    """One activity (never a multisport parent), as the loader hands it over."""

    day: date  # the local day it started
    sport: str  # Garmin's type key
    duration_s: float
    distance_m: float | None = None
    climb_m: float | None = None
    load: float | None = None  # our heart-rate load; None when there was no heart rate
    # Seconds below zone 1, then in zones 1 to 5 (ours, from `activity_derived`).
    zone_s: Sequence[int] | None = None


@dataclass(frozen=True)
class DayLoad:
    day: date
    load: float  # 0 on a rest day
    fitness: float
    fatigue: float
    form: float  # yesterday's fitness less yesterday's fatigue
    band: Band


def daily_load(rows: Sequence[ActivityRow]) -> dict[date, float]:
    """The load per local day, from the first activity to the last; 0 on rest days."""
    if not rows:
        return {}
    totals: dict[date, float] = defaultdict(float)
    for row in rows:
        totals[row.day] += row.load or 0.0
    first, last = min(totals), max(totals)
    days = (first + timedelta(days=i) for i in range((last - first).days + 1))
    return {day: totals.get(day, 0.0) for day in days}


def ewma(loads: Sequence[float], time_constant: int) -> list[float]:
    """The exponentially weighted average per day, seeded at 0 before the first day."""
    value = 0.0
    out: list[float] = []
    for load in loads:
        value += (load - value) / time_constant
        out.append(value)
    return out


def load_series(rows: Sequence[ActivityRow], until: date) -> list[DayLoad]:
    """Load, fitness, fatigue and form for every day from the first activity to `until`
    (days after the last activity are rest days). Empty without activities."""
    loads = daily_load([r for r in rows if r.day <= until])
    if not loads:
        return []
    first = min(loads)
    days = [first + timedelta(days=i) for i in range((until - first).days + 1)]
    values = [loads.get(day, 0.0) for day in days]
    fitness = ewma(values, CTL_DAYS)
    fatigue = ewma(values, ATL_DAYS)
    points: list[DayLoad] = []
    for i, day in enumerate(days):
        form = (fitness[i - 1] - fatigue[i - 1]) if i else 0.0
        points.append(DayLoad(day, values[i], fitness[i], fatigue[i], form, band_of(form)))
    return points


def current_form(rows: Sequence[ActivityRow], today: date) -> float | None:
    """Today's form (yesterday's fitness less yesterday's fatigue); None without activities."""
    series = load_series(rows, today)
    return series[-1].form if series else None


@dataclass(frozen=True)
class TrainingSummary:
    fitness: float | None
    fatigue: float | None
    form: float | None
    band: Band | None
    fitness_change: float | None  # over the last 42 days; None with a shorter history
    ramp_per_week: float | None  # fitness per week over the last 28 days; None likewise
    ramp_safe: bool | None  # ramp under RAMP_SAFE


def summarize(series: Sequence[DayLoad]) -> TrainingSummary:
    if not series:
        return TrainingSummary(None, None, None, None, None, None, None)
    last = series[-1]

    def change(days: int) -> float | None:
        return last.fitness - series[-1 - days].fitness if len(series) > days else None

    month = change(RAMP_DAYS)
    ramp = None if month is None else month / (RAMP_DAYS / 7)
    return TrainingSummary(
        fitness=last.fitness,
        fatigue=last.fatigue,
        form=last.form,
        band=last.band,
        fitness_change=change(CHANGE_DAYS),
        ramp_per_week=ramp,
        ramp_safe=None if ramp is None else ramp < RAMP_SAFE,
    )


@dataclass(frozen=True)
class TrainingWeek:
    week_start: date  # the Monday
    swim: float
    bike: float
    run: float
    strength: float
    other: float
    partial: bool  # the current week, still going


@dataclass(frozen=True)
class Weeks:
    weeks: list[TrainingWeek]
    average: float | None  # hours a week over the complete weeks, rest weeks included


def monday(day: date) -> date:
    return day - timedelta(days=day.weekday())


def first_monday(day: date) -> date:
    """The Monday on or after `day`: the first whole week of a window."""
    return day if day.weekday() == 0 else monday(day) + timedelta(days=7)


def weekly_hours(rows: Sequence[ActivityRow], start: date, today: date) -> Weeks:
    """Hours per ISO week by sport, from the week starting `start` (a Monday) to the current
    week, which is marked partial and left out of the average."""
    this_week = monday(today)
    if start > this_week:
        return Weeks([], None)
    hours: dict[date, dict[Sport, float]] = defaultdict(lambda: defaultdict(float))
    for row in rows:
        if start <= row.day <= today:
            hours[monday(row.day)][sport_of(row.sport)] += row.duration_s / 3600
    weeks = []
    for i in range((this_week - start).days // 7 + 1):
        week = start + timedelta(days=7 * i)
        h = hours.get(week, {})
        weeks.append(
            TrainingWeek(
                week,
                h.get("swim", 0.0),
                h.get("bike", 0.0),
                h.get("run", 0.0),
                h.get("strength", 0.0),
                h.get("other", 0.0),
                partial=week == this_week,
            )
        )
    complete = [w for w in weeks if not w.partial]
    average = (
        sum(w.swim + w.bike + w.run + w.strength + w.other for w in complete) / len(complete)
        if complete
        else None
    )
    return Weeks(weeks, average)


@dataclass(frozen=True)
class TrainingDay:
    day: date
    swim: float  # hours
    bike: float
    run: float
    strength: float
    other: float


def daily_hours(rows: Sequence[ActivityRow], first: date, last: date) -> list[TrainingDay]:
    """Hours per day by sport, every day from `first` to `last`; 0 on a day without activity."""
    hours: dict[date, dict[Sport, float]] = defaultdict(lambda: defaultdict(float))
    for row in rows:
        if first <= row.day <= last:
            hours[row.day][sport_of(row.sport)] += row.duration_s / 3600
    out: list[TrainingDay] = []
    for i in range((last - first).days + 1):
        day = first + timedelta(days=i)
        h = hours.get(day, {})
        out.append(
            TrainingDay(
                day,
                h.get("swim", 0.0),
                h.get("bike", 0.0),
                h.get("run", 0.0),
                h.get("strength", 0.0),
                h.get("other", 0.0),
            )
        )
    return out


@dataclass(frozen=True)
class TrainingIntensity:
    """Seconds in heart-rate zones for one sport, grouped; shares of `total_s`."""

    sport: Sport | Literal["all"]
    z12_s: int
    z3_s: int
    z45_s: int
    z12_share: float | None
    z3_share: float | None
    z45_share: float | None


def _intensity(sport: Sport | Literal["all"], z12: int, z3: int, z45: int) -> TrainingIntensity:
    total = z12 + z3 + z45
    if total == 0:
        return TrainingIntensity(sport, 0, 0, 0, None, None, None)
    return TrainingIntensity(sport, z12, z3, z45, z12 / total, z3 / total, z45 / total)


def intensity(rows: Sequence[ActivityRow], first: date, last: date) -> list[TrainingIntensity]:
    """Time in zones Z1-2 (with the time below zone 1), Z3 and Z4-5 per sport, for activities
    from `first` to `last`, then all of them. Only sports with zone time appear."""
    sums: dict[Sport, list[int]] = defaultdict(lambda: [0, 0, 0])
    for row in rows:
        if not row.zone_s or len(row.zone_s) < 6 or not first <= row.day <= last:
            continue
        z = [s or 0 for s in row.zone_s]
        group = sums[sport_of(row.sport)]
        group[0] += z[0] + z[1] + z[2]
        group[1] += z[3]
        group[2] += z[4] + z[5]
    out = [_intensity(s, *sums[s]) for s in SPORTS if s in sums and sum(sums[s]) > 0]
    if out:
        out.append(_intensity("all", *(sum(v[i] for v in sums.values()) for i in range(3))))
    return out


@dataclass(frozen=True)
class TrainingMonth:
    month: date  # the first of the month
    swim_m: float
    bike_m: float
    run_m: float
    hours: float
    load: float
    climb_m: float
    sessions: int
    partial: bool  # the current month


def monthly_totals(rows: Sequence[ActivityRow], first: date, today: date) -> list[TrainingMonth]:
    """Totals for each month from `first`'s to `today`'s, newest first. Distance is per
    swim, bike and run; hours, load, climb and sessions count every sport."""
    start = first.replace(day=1)
    this_month = today.replace(day=1)
    acc: dict[date, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for row in rows:
        month = row.day.replace(day=1)
        if not start <= month <= this_month or row.day > today:
            continue
        a = acc[month]
        sport = sport_of(row.sport)
        if sport in ("swim", "bike", "run"):
            a[sport] += row.distance_m or 0.0
        a["hours"] += row.duration_s / 3600
        a["load"] += row.load or 0.0
        a["climb"] += row.climb_m or 0.0
        a["sessions"] += 1
    months: list[TrainingMonth] = []
    month = this_month
    while month >= start:
        a = acc.get(month, {})
        months.append(
            TrainingMonth(
                month,
                a.get("swim", 0.0),
                a.get("bike", 0.0),
                a.get("run", 0.0),
                a.get("hours", 0.0),
                a.get("load", 0.0),
                a.get("climb", 0.0),
                int(a.get("sessions", 0)),
                partial=month == this_month,
            )
        )
        month = (month - timedelta(days=1)).replace(day=1)
    return months
