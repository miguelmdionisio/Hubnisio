"""Performance over time (ADR-0009, "As built in H7"): curves across a season, the critical
power and speed models, critical swim speed, the VO2max trend, race predictions with marathon
shape, easy-run efficiency, the bike without power, and records. Pure: per-activity rows
(`ActivityFacts`, from `activity_derived` and `activities`) in, figures out.

- **Season curves:** for each duration of `curves.CURVE_DURATIONS`, the best value of the
  activities' own mean-maximal curves over the period, with its day and activity.
- **Critical power** (runs): P(t) = CP + W'/t, fitted by least squares as work against time,
  W = CP * t + W', on the season's bests from 3 to 20 minutes. It needs at least 3 durations,
  the longest 12 minutes or more, and a positive CP and W'.
- **Critical speed** (runs): the same on distance against time, D = CS * t + D', from the
  speed curve. **Critical swim speed:** (400 - 200) / (t400 - t200) m/s from the best 400 m
  and 200 m swims, shown as seconds per 100 m.
- **VO2max trend:** each run's estimate, and a line: at each day, the mean of the best half
  of the estimates in the trailing 42 days, so easy days (whose estimate reads low) don't drag
  it down. Its change is today's value against the value 90 days ago.
- **Race predictions:** Daniels' VDOT equations solved for time at the current VO2max, and a
  Riegel projection (T2 = T1 * (D2 / D1)^1.06) from the best effort of 5 km or more in the last
  90 days (the one with the highest VDOT). Marathon shape after Runalyze (`marathon_shape`).
- **Easy-run efficiency:** the efficiency factor of steady runs of 20 minutes or more with
  an average heart rate under zone 3, with a least-squares trend.
"""

import math
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Literal

from hubnisio.health.insights.activity import Family, family, is_pool
from hubnisio.health.insights.curves import CURVE_DURATIONS

Period = Literal["season", "90d", "all"]
CurveKind = Literal["power", "hr", "speed"]

MODEL_MIN_S = 180  # bests from 3 minutes…
MODEL_MAX_S = 1200  # …to 20 minutes
MODEL_MIN_POINTS = 3
MODEL_LONGEST_S = 720  # the longest point at least 12 minutes
MODEL_LINE = tuple(t for t in CURVE_DURATIONS if 120 <= t <= 3600)

VO2_WINDOW = 42  # days
VO2_CHANGE_DAYS = 90
RECENT_DAYS = 90  # the Riegel effort's age at most
RIEGEL = 1.06
RACES = (5000, 10000, 21097, 42195)
RIEGEL_FROM = (5000, 10000, 21097, 42195)

SHAPE_DAYS = 182  # 26 weeks
SHAPE_WEEKS = 26
LONG_RUN_MIN_KM = 13.0
LONG_RUNS_TARGET = 13.0  # one long run at target every two weeks
WEEKLY_SHARE = 2 / 3
SHAPE_SLOWING = 0.25  # VDOT lost at no shape at all, for a distance that needs it all

EASY_MIN_S = 1200
EASY_ZONE3_SHARE = 0.90  # zone 3's floor as a share of threshold, without the member's zones
EFFICIENCY_DAYS = 182
EFFICIENCY_MIN_POINTS = 3

TOP_CLIMBS = 5
TOP_TRIATHLONS = 5
RUN_RECORDS = (1000, 5000, 10000, 21097, 42195)
SWIM_RECORDS = (100, 400, 1500)


@dataclass(frozen=True)
class ClimbFacts:
    distance_m: float
    gain_m: float
    duration_s: float
    grade: float
    vam: float


@dataclass(frozen=True)
class ActivityFacts:
    """One activity as performance reads it; curves are aligned with `CURVE_DURATIONS`."""

    activity_id: int
    day: date
    sport: str  # Garmin's type key
    name: str | None = None
    distance_m: float | None = None
    duration_s: float | None = None
    elevation_gain_m: float | None = None
    avg_hr: float | None = None
    is_parent: bool = False
    parent_id: int | None = None
    moving_s: int | None = None
    hr_threshold: float | None = None
    power_curve: Sequence[float | None] | None = None
    hr_curve: Sequence[float | None] | None = None
    speed_curve: Sequence[float | None] | None = None
    best_efforts: dict[int, float] | None = None  # seconds by metres
    efficiency_factor: float | None = None
    steady: bool | None = None
    vo2max: float | None = None
    climbs: Sequence[ClimbFacts] = ()

    @property
    def family(self) -> Family:
        return Family.OTHER if self.is_parent else family(self.sport)


# What the API returns


@dataclass(frozen=True)
class BestPoint:
    duration_s: int
    value: float | None
    day: date | None = None
    activity_id: int | None = None


@dataclass(frozen=True)
class ModelPoint:
    duration_s: int
    value: float


@dataclass(frozen=True)
class CriticalPower:
    cp: float  # W
    w_prime: float  # J
    cp_per_kg: float | None
    points: int  # durations fitted
    line: list[ModelPoint]


@dataclass(frozen=True)
class CriticalSpeed:
    speed: float  # m/s
    d_prime: float  # m
    pace_per_km_s: float
    points: int
    line: list[ModelPoint]


@dataclass(frozen=True)
class SwimThreshold:
    speed: float  # m/s
    pace_per_100_s: float
    t200_s: float
    t400_s: float


@dataclass(frozen=True)
class SeasonCurves:
    current: list[BestPoint]
    last_season: list[BestPoint]


@dataclass(frozen=True)
class RunPower(SeasonCurves):
    model: CriticalPower | None


@dataclass(frozen=True)
class RunPace(SeasonCurves):
    model: CriticalSpeed | None


@dataclass(frozen=True)
class Vo2Point:
    day: date
    activity_id: int
    value: float
    line: float | None


@dataclass(frozen=True)
class Vo2maxTrend:
    points: list[Vo2Point]
    latest: float | None
    change_90d: float | None


@dataclass(frozen=True)
class MarathonShape:
    score: float  # a share: 1.0 is 100 %
    weekly_km: float
    weekly_target_km: float
    weekly_share: float
    long_runs: int
    long_target_km: float
    long_share: float


@dataclass(frozen=True)
class RacePrediction:
    distance_m: int
    needs: float  # the shape this distance needs, a share
    vdot_s: float | None  # from VO2max, slowed when shape falls short of `needs`
    slowed: bool
    riegel_s: float | None


@dataclass(frozen=True)
class RiegelSource:
    distance_m: int
    seconds: float
    day: date
    activity_id: int


@dataclass(frozen=True)
class RacePredictions:
    vo2max: float | None
    shape: MarathonShape | None
    items: list[RacePrediction]
    riegel_from: RiegelSource | None


@dataclass(frozen=True)
class EasyEfficiencyPoint:
    day: date
    activity_id: int
    value: float  # m/min per bpm


@dataclass(frozen=True)
class TrendLine:
    start_day: date
    start: float
    end_day: date
    end: float


@dataclass(frozen=True)
class EasyEfficiency:
    points: list[EasyEfficiencyPoint]
    trend: TrendLine | None
    change_6m_pct: float | None


@dataclass(frozen=True)
class BestClimb:
    day: date
    activity_id: int
    distance_m: float
    gain_m: float
    duration_s: float
    grade: float
    vam: float


@dataclass(frozen=True)
class BikePerformance:
    hr_curve: SeasonCurves
    power_curve: SeasonCurves | None  # only when rides carry power
    climbs: list[BestClimb]


@dataclass(frozen=True)
class PerformanceRecord:
    key: str
    value: float | None  # in the period: seconds, metres or m/s by key
    day: date | None
    activity_id: int | None
    venue: Literal["pool", "open_water"] | None = None
    all_time: float | None = None  # only when another activity holds it
    all_time_day: date | None = None


@dataclass(frozen=True)
class TriathlonResult:
    activity_id: int
    name: str | None
    day: date
    duration_s: float | None
    distance_m: float | None


@dataclass(frozen=True)
class PerformanceRecords:
    run: list[PerformanceRecord]
    swim: list[PerformanceRecord]
    bike: list[PerformanceRecord]
    triathlon: list[TriathlonResult]


@dataclass(frozen=True)
class Performance:
    period: Period
    first_day: date | None
    last_day: date
    season: int
    weight_kg: float | None
    run_power: RunPower
    run_pace: RunPace
    swim_threshold: SwimThreshold | None
    vo2max: Vo2maxTrend
    predictions: RacePredictions
    efficiency: EasyEfficiency
    bike: BikePerformance
    records: PerformanceRecords


# Periods and curves


def period_start(period: Period, today: date) -> date | None:
    if period == "season":
        return date(today.year, 1, 1)
    if period == "90d":
        return today - timedelta(days=89)
    return None


def within(rows: Iterable[ActivityFacts], start: date | None, end: date) -> list[ActivityFacts]:
    return [r for r in rows if (start is None or r.day >= start) and r.day <= end]


def season_curve(rows: Iterable[ActivityFacts], kind: CurveKind) -> list[BestPoint]:
    """The best value per duration over the rows' own curves (the earliest on a tie)."""
    best: list[BestPoint] = [BestPoint(t, None) for t in CURVE_DURATIONS]
    for row in sorted(rows, key=lambda r: (r.day, r.activity_id)):
        curve = {"power": row.power_curve, "hr": row.hr_curve, "speed": row.speed_curve}[kind]
        if not curve:
            continue
        for i, value in enumerate(curve[: len(CURVE_DURATIONS)]):
            current = best[i].value
            if value is not None and (current is None or value > current):
                best[i] = BestPoint(CURVE_DURATIONS[i], value, row.day, row.activity_id)
    return best


def least_squares(xs: Sequence[float], ys: Sequence[float]) -> tuple[float, float]:
    """Slope and intercept of the ordinary least-squares line."""
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys, strict=True))
    slope = sxy / sxx
    return slope, my - slope * mx


def _model_points(curve: Sequence[BestPoint]) -> list[tuple[int, float]] | None:
    points = [
        (p.duration_s, p.value)
        for p in curve
        if p.value is not None and MODEL_MIN_S <= p.duration_s <= MODEL_MAX_S
    ]
    if len(points) < MODEL_MIN_POINTS or max(t for t, _ in points) < MODEL_LONGEST_S:
        return None
    return points


def two_parameter_fit(curve: Sequence[BestPoint]) -> tuple[float, float, int] | None:
    """(rate, reserve, points) of `rate * t + reserve` fitted to `value * t` against t: CP and
    W' from power, CS and D' from speed. None without enough points or with a non-positive
    parameter."""
    points = _model_points(curve)
    if points is None:
        return None
    rate, reserve = least_squares([t for t, _ in points], [v * t for t, v in points])
    if rate <= 0 or reserve <= 0:
        return None
    return rate, reserve, len(points)


def critical_power(
    curve: Sequence[BestPoint], weight_kg: float | None = None
) -> CriticalPower | None:
    fit = two_parameter_fit(curve)
    if fit is None:
        return None
    cp, w_prime, n = fit
    return CriticalPower(
        cp=cp,
        w_prime=w_prime,
        cp_per_kg=cp / weight_kg if weight_kg else None,
        points=n,
        line=[ModelPoint(t, cp + w_prime / t) for t in MODEL_LINE],
    )


def critical_speed(curve: Sequence[BestPoint]) -> CriticalSpeed | None:
    fit = two_parameter_fit(curve)
    if fit is None:
        return None
    cs, d_prime, n = fit
    return CriticalSpeed(
        speed=cs,
        d_prime=d_prime,
        pace_per_km_s=1000 / cs,
        points=n,
        line=[ModelPoint(t, cs + d_prime / t) for t in MODEL_LINE],
    )


def swim_threshold(t200: float | None, t400: float | None) -> SwimThreshold | None:
    """Critical swim speed from the best 200 m and 400 m."""
    if t200 is None or t400 is None or t400 <= t200:
        return None
    speed = 200 / (t400 - t200)
    return SwimThreshold(speed, 100 / speed, t200, t400)


# VO2max


def smoothed_vo2max(rows: Iterable[ActivityFacts], day: date) -> float | None:
    """The mean of the best half of the run estimates in the 42 days to `day`."""
    start = day - timedelta(days=VO2_WINDOW - 1)
    values = sorted(
        (r.vo2max for r in rows if r.vo2max is not None and start <= r.day <= day),
        reverse=True,
    )
    if not values:
        return None
    top = values[: math.ceil(len(values) / 2)]
    return sum(top) / len(top)


def vo2max_trend(runs: Sequence[ActivityFacts], start: date | None, today: date) -> Vo2maxTrend:
    shown = sorted(
        (r for r in within(runs, start, today) if r.vo2max is not None),
        key=lambda r: (r.day, r.activity_id),
    )
    points = [
        Vo2Point(r.day, r.activity_id, r.vo2max, smoothed_vo2max(runs, r.day))
        for r in shown
        if r.vo2max is not None
    ]
    latest = smoothed_vo2max(runs, today)
    before = smoothed_vo2max(runs, today - timedelta(days=VO2_CHANGE_DAYS))
    change = latest - before if latest is not None and before is not None else None
    return Vo2maxTrend(points, latest, change)


# Race predictions (Daniels and Gilbert's VDOT)


def vo2_cost(metres_per_minute: float) -> float:
    v = metres_per_minute
    return -4.60 + 0.182258 * v + 0.000104 * v * v


def vo2max_share(minutes: float) -> float:
    """The share of VO2max a race lasting `minutes` can be run at (Daniels and Gilbert)."""
    return (
        0.8 + 0.1894393 * math.exp(-0.012778 * minutes) + 0.2989558 * math.exp(-0.1932605 * minutes)
    )


def vdot_of(distance_m: float, seconds: float) -> float:
    minutes = seconds / 60
    return vo2_cost(distance_m / minutes) / vo2max_share(minutes)


def vdot_time(vdot: float, distance_m: float) -> float:
    """Seconds to race `distance_m` at `vdot`: `vdot_of` solved for time by bisection."""
    lo, hi = 1.0, 2000.0  # minutes; vdot_of falls as time grows
    for _ in range(100):
        mid = (lo + hi) / 2
        if vdot_of(distance_m, mid * 60) > vdot:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2 * 60


def riegel(seconds: float, from_m: float, to_m: float) -> float:
    return seconds * (to_m / from_m) ** RIEGEL


def shape_needed(distance_m: float) -> float:
    """The marathon shape a race needs: none to 5 km, rising linearly to all of it for the
    marathon."""
    return min(max((distance_m / 1000 - 5) / (42.195 - 5), 0.0), 1.0)


def marathon_shape(
    runs: Iterable[ActivityFacts], today: date, vo2max: float
) -> MarathonShape | None:
    """After Runalyze's marathon shape ("Marathonform"), from the last 26 weeks:

    - weekly target km = VO2max^1.135; weekly share = (km run / 26) / target;
    - long-run target km = 12 * ln(VO2max / 4); each run of 13 km or more scores
      ((km - 13) / (target - 13))^2, and the long-run share is their sum over 13 (one run at
      target every two weeks);
    - shape = 2/3 * weekly share + 1/3 * long-run share, uncapped."""
    if vo2max <= 0:
        return None
    weekly_target = vo2max**1.135
    long_target = 12 * math.log(vo2max / 4)
    if long_target <= LONG_RUN_MIN_KM:
        return None
    start = today - timedelta(days=SHAPE_DAYS - 1)
    km = [r.distance_m / 1000 for r in runs if r.distance_m is not None and start <= r.day <= today]
    weekly = sum(km) / SHAPE_WEEKS
    long_runs = [k for k in km if k >= LONG_RUN_MIN_KM]
    points = sum(((k - LONG_RUN_MIN_KM) / (long_target - LONG_RUN_MIN_KM)) ** 2 for k in long_runs)
    weekly_share = weekly / weekly_target
    long_share = points / LONG_RUNS_TARGET
    return MarathonShape(
        score=WEEKLY_SHARE * weekly_share + (1 - WEEKLY_SHARE) * long_share,
        weekly_km=weekly,
        weekly_target_km=weekly_target,
        weekly_share=weekly_share,
        long_runs=len(long_runs),
        long_target_km=long_target,
        long_share=long_share,
    )


def shaped_vdot(vdot: float, shape: float, needs: float) -> float:
    """VDOT slowed when the shape falls short of what the distance needs: by up to
    `SHAPE_SLOWING` of it, in proportion to the shortfall."""
    if needs <= 0 or shape >= needs:
        return vdot
    return vdot * (1 - SHAPE_SLOWING * (1 - max(shape, 0.0) / needs))


def riegel_source(runs: Iterable[ActivityFacts], today: date) -> RiegelSource | None:
    """The best effort of 5 km or more in the last 90 days, by its VDOT."""
    start = today - timedelta(days=RECENT_DAYS - 1)
    best: tuple[float, RiegelSource] | None = None
    for r in runs:
        if not (start <= r.day <= today) or not r.best_efforts:
            continue
        for metres in RIEGEL_FROM:
            seconds = r.best_efforts.get(metres)
            if seconds is None or seconds <= 0:
                continue
            score = vdot_of(metres, seconds)
            if best is None or score > best[0]:
                best = (score, RiegelSource(metres, seconds, r.day, r.activity_id))
    return best[1] if best else None


def predictions(
    runs: Sequence[ActivityFacts], today: date, vo2max: float | None
) -> RacePredictions:
    shape = marathon_shape(runs, today, vo2max) if vo2max else None
    source = riegel_source(runs, today)
    items: list[RacePrediction] = []
    for metres in RACES:
        needs = shape_needed(metres)
        vdot_s = None
        slowed = False
        if vo2max:
            used = shaped_vdot(vo2max, shape.score, needs) if shape else vo2max
            slowed = used < vo2max
            vdot_s = vdot_time(used, metres)
        riegel_s = riegel(source.seconds, source.distance_m, metres) if source else None
        items.append(RacePrediction(metres, needs, vdot_s, slowed, riegel_s))
    return RacePredictions(vo2max, shape, items, source)


# Easy-run efficiency


def easy_runs(runs: Iterable[ActivityFacts], zone3_floor: float | None) -> list[ActivityFacts]:
    """Steady runs of 20 minutes or more, average heart rate under zone 3's floor (the
    member's, else 90 % of the run's threshold)."""
    out: list[ActivityFacts] = []
    for r in runs:
        ceiling = zone3_floor or (r.hr_threshold * EASY_ZONE3_SHARE if r.hr_threshold else None)
        if (
            r.steady
            and r.efficiency_factor is not None
            and (r.moving_s or 0) >= EASY_MIN_S
            and r.avg_hr is not None
            and ceiling is not None
            and r.avg_hr < ceiling
        ):
            out.append(r)
    return sorted(out, key=lambda r: (r.day, r.activity_id))


def trend_line(points: Sequence[tuple[date, float]]) -> TrendLine | None:
    """The least-squares line through the points, from the first day to the last."""
    if len(points) < EFFICIENCY_MIN_POINTS:
        return None
    first, last = points[0][0], points[-1][0]
    if first == last:
        return None
    xs = [float((d - first).days) for d, _ in points]
    slope, intercept = least_squares(xs, [v for _, v in points])
    return TrendLine(first, intercept, last, intercept + slope * (last - first).days)


def efficiency(
    runs: Sequence[ActivityFacts], zone3_floor: float | None, start: date | None, today: date
) -> EasyEfficiency:
    easy = easy_runs(runs, zone3_floor)
    shown = within(easy, start, today)
    points = [
        EasyEfficiencyPoint(r.day, r.activity_id, r.efficiency_factor)
        for r in shown
        if r.efficiency_factor is not None
    ]
    recent = within(easy, today - timedelta(days=EFFICIENCY_DAYS - 1), today)
    line = trend_line([(r.day, r.efficiency_factor) for r in recent if r.efficiency_factor])
    change = (line.end - line.start) / line.start * 100 if line and line.start > 0 else None
    return EasyEfficiency(points, trend_line([(p.day, p.value) for p in points]), change)


# BikePerformance


def bike(rides: Sequence[ActivityFacts], last_season: Sequence[ActivityFacts]) -> BikePerformance:
    has_power = any(v is not None for r in rides for v in (r.power_curve or ()))
    climbs = sorted(
        (
            BestClimb(r.day, r.activity_id, c.distance_m, c.gain_m, c.duration_s, c.grade, c.vam)
            for r in rides
            for c in r.climbs
        ),
        key=lambda c: -c.vam,
    )[:TOP_CLIMBS]
    return BikePerformance(
        hr_curve=SeasonCurves(season_curve(rides, "hr"), season_curve(last_season, "hr")),
        power_curve=SeasonCurves(season_curve(rides, "power"), season_curve(last_season, "power"))
        if has_power
        else None,
        climbs=climbs,
    )


# PerformanceRecords


Candidate = tuple[float, date, int, Literal["pool", "open_water"] | None]


def _record(
    key: str,
    shown: Iterable[Candidate],
    everything: Iterable[Candidate],
    lower_is_better: bool,
    compare: bool,
) -> PerformanceRecord:
    def best(items: Iterable[Candidate]) -> Candidate | None:
        ordered = sorted(items, key=lambda c: (c[0] if lower_is_better else -c[0], c[1]))
        return ordered[0] if ordered else None

    here = best(shown)
    ever = best(everything) if compare else None
    if ever is not None and here is not None and ever[2] == here[2]:
        ever = None
    return PerformanceRecord(
        key=key,
        value=here[0] if here else None,
        day=here[1] if here else None,
        activity_id=here[2] if here else None,
        venue=here[3] if here else (ever[3] if ever else None),
        all_time=ever[0] if ever else None,
        all_time_day=ever[1] if ever else None,
    )


def _efforts(rows: Iterable[ActivityFacts], metres: int, swim: bool) -> list[Candidate]:
    out: list[Candidate] = []
    for r in rows:
        seconds = (r.best_efforts or {}).get(metres)
        if seconds is not None:
            venue: Literal["pool", "open_water"] | None = None
            if swim:
                venue = "pool" if is_pool(r.sport) else "open_water"
            out.append((seconds, r.day, r.activity_id, venue))
    return out


def _bike_values(rows: Iterable[ActivityFacts], pick: Callable[[ActivityFacts], float | None]):
    return [(v, r.day, r.activity_id, None) for r in rows if (v := pick(r)) is not None]


def _curve_at(duration: int) -> Callable[[ActivityFacts], float | None]:
    index = CURVE_DURATIONS.index(duration)

    def pick(r: ActivityFacts) -> float | None:
        curve = r.speed_curve
        return curve[index] if curve and len(curve) > index else None

    return pick


def records(
    rows: Sequence[ActivityFacts], everything: Sequence[ActivityFacts], compare: bool
) -> PerformanceRecords:
    def of(sport: Family, source: Sequence[ActivityFacts]) -> list[ActivityFacts]:
        return [r for r in source if r.family is sport]

    runs, all_runs = of(Family.RUN, rows), of(Family.RUN, everything)
    swims, all_swims = of(Family.SWIM, rows), of(Family.SWIM, everything)
    rides, all_rides = of(Family.RIDE, rows), of(Family.RIDE, everything)
    run = [
        _record(str(m), _efforts(runs, m, False), _efforts(all_runs, m, False), True, compare)
        for m in RUN_RECORDS
    ]
    swim = [
        _record(str(m), _efforts(swims, m, True), _efforts(all_swims, m, True), True, compare)
        for m in SWIM_RECORDS
    ]
    picks: list[tuple[str, Callable[[ActivityFacts], float | None]]] = [
        ("longest", lambda r: r.distance_m),
        ("climbing", lambda r: r.elevation_gain_m),
        ("speed_1200", _curve_at(1200)),
        ("speed_3600", _curve_at(3600)),
    ]
    ride = [
        _record(key, _bike_values(rides, pick), _bike_values(all_rides, pick), False, compare)
        for key, pick in picks
    ]
    return PerformanceRecords(run, swim, ride, triathlons(rows, everything))


def triathlons(
    rows: Sequence[ActivityFacts], everything: Sequence[ActivityFacts]
) -> list[TriathlonResult]:
    """Multisport results in the period, the newest first: the parent's own totals, else its
    legs' sums."""
    legs: dict[int, list[ActivityFacts]] = {}
    for r in everything:
        if r.parent_id is not None:
            legs.setdefault(r.parent_id, []).append(r)
    out: list[TriathlonResult] = []
    for r in sorted((r for r in rows if r.is_parent), key=lambda r: r.day, reverse=True):
        mine = legs.get(r.activity_id, [])
        duration = r.duration_s
        if duration is None and mine and all(leg.duration_s is not None for leg in mine):
            duration = sum(leg.duration_s or 0 for leg in mine)
        distance = r.distance_m
        if distance is None and mine:
            distance = sum(leg.distance_m or 0 for leg in mine) or None
        out.append(TriathlonResult(r.activity_id, r.name, r.day, duration, distance))
    return out[:TOP_TRIATHLONS]


# All of it


def performance(
    rows: Sequence[ActivityFacts],
    today: date,
    period: Period,
    *,
    zone3_floor: float | None = None,
    weight_kg: float | None = None,
) -> Performance:
    rows = [r for r in rows if r.day <= today]
    start = period_start(period, today)
    last_start, last_end = date(today.year - 1, 1, 1), date(today.year - 1, 12, 31)
    shown = within(rows, start, today)
    previous = within(rows, last_start, last_end)

    def runs(source: Sequence[ActivityFacts]) -> list[ActivityFacts]:
        return [r for r in source if r.family is Family.RUN]

    def rides(source: Sequence[ActivityFacts]) -> list[ActivityFacts]:
        return [r for r in source if r.family is Family.RIDE]

    all_runs = runs(rows)
    power = season_curve(runs(shown), "power")
    pace = season_curve(runs(shown), "speed")
    swims = [r for r in shown if r.family is Family.SWIM]
    t200 = min(_efforts_seconds(swims, 200), default=None)
    t400 = min(_efforts_seconds(swims, 400), default=None)
    trend = vo2max_trend(all_runs, start, today)
    return Performance(
        period=period,
        first_day=start,
        last_day=today,
        season=today.year,
        weight_kg=weight_kg,
        run_power=RunPower(
            power, season_curve(runs(previous), "power"), critical_power(power, weight_kg)
        ),
        run_pace=RunPace(pace, season_curve(runs(previous), "speed"), critical_speed(pace)),
        swim_threshold=swim_threshold(t200, t400),
        vo2max=trend,
        predictions=predictions(all_runs, today, trend.latest),
        efficiency=efficiency(all_runs, zone3_floor, start, today),
        bike=bike(rides(shown), rides(previous)),
        records=records(shown, rows, compare=period != "all"),
    )


def _efforts_seconds(rows: Iterable[ActivityFacts], metres: int) -> list[float]:
    return [s for r in rows if (s := (r.best_efforts or {}).get(metres)) is not None]
