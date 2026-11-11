"""Shaping one activity for its page and the list (ADR-0009, "As built in H5"). Pure: stored
rows in, figures out. Nothing here reads the database.

Streams are cut to a few hundred points by averaging buckets along the chart's axis (distance
for runs and rides, time otherwise); pace comes from the averaged speed, never the other way
round. Splits and sets are rebuilt from the samples; the route is simplified, never resampled.
"""

import itertools
import math
from bisect import bisect_left, bisect_right
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from hubnisio.health.insights import durability as dur
from hubnisio.health.insights import running
from hubnisio.health.insights.activity import Family, family
from hubnisio.health.insights.series import Series, mean, moving

SERIES_POINTS = 600
ROUTE_POINTS = 500
MIN_PACE_SPEED = 0.5  # m/s: slower than this is standing still, not a pace
MIN_PARTIAL_KM = 100.0  # metres: a shorter last stretch is left out of the splits

Group = Literal["swim", "bike", "run", "strength", "other"]
GROUPS: tuple[Group, ...] = ("swim", "bike", "run", "strength", "other")
Column = Sequence[float | None]


def sport_group(type_key: str | None) -> Group:
    """The list's sport pill an activity type key belongs to."""
    match family(type_key):
        case Family.RUN:
            return "run"
        case Family.RIDE:
            return "bike"
        case Family.SWIM:
            return "swim"
        case Family.OTHER:
            return "strength" if "strength" in (type_key or "").lower() else "other"


FigureKind = Literal["pace_km", "pace_100m", "speed_kmh"]


def key_figure(
    group: Group, distance_m: float | None, duration_s: float | None
) -> tuple[FigureKind | None, float | None]:
    """The figure a sport is read by: pace per km for runs, per 100 m for swims, speed in km/h
    for rides. None under 100 m or without a time."""
    if not distance_m or not duration_s or distance_m < 100 or duration_s <= 0:
        return None, None
    if group == "run":
        return "pace_km", duration_s / distance_m * 1000
    if group == "swim":
        return "pace_100m", duration_s / distance_m * 100
    if group == "bike":
        return "speed_kmh", distance_m / duration_s * 3.6
    return None, None


# -- Streams ------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class StreamData:
    """The stored arrays of one activity (all as long as `time`); None where it has none."""

    time: Sequence[int]
    distance: Column | None = None
    heart_rate: Column | None = None
    speed: Column | None = None
    altitude: Column | None = None
    cadence: Column | None = None
    power: Column | None = None
    lat: Column | None = None
    lon: Column | None = None


@dataclass(frozen=True, slots=True)
class ActivityStreams:
    """What the charts draw: `x` along `axis` (metres or seconds), each series as long as `x`
    with None where a bucket has no value. Keys: `pace` (s/km), `pace100` (s/100 m), `speed`
    (km/h), `heart_rate`, `altitude` (m), `cadence`, `power` (W)."""

    axis: Literal["distance", "time"]
    x: list[float]
    series: dict[str, list[float | None]]


def _has(values: Column | None) -> bool:
    return values is not None and any(v is not None for v in values)


def downsample(
    axis: Column, columns: dict[str, Column], points: int = SERIES_POINTS
) -> tuple[list[float], dict[str, list[float | None]]]:
    """Each column's mean in `points` equal slices of the axis' range (empty slices dropped).
    At most `points` samples come back unchanged. A column with no value at all is left out."""
    index = [i for i, a in enumerate(axis) if a is not None]
    if not index:
        return [], {}
    values = [float(axis[i] or 0.0) for i in index]
    lo, hi = min(values), max(values)
    if len(index) <= points:
        xs = values
        out = {k: [_value(c, i) for i in index] for k, c in columns.items() if _has(c)}
    else:
        span = hi - lo
        slots: dict[int, list[int]] = {}
        for i, a in zip(index, values, strict=True):
            slot = min(points - 1, int((a - lo) / span * points)) if span > 0 else 0
            slots.setdefault(slot, []).append(i)
        ordered = [slots[s] for s in sorted(slots)]
        xs = [sum(float(axis[i] or 0.0) for i in chunk) / len(chunk) for chunk in ordered]
        out = {k: [_mean_of(c, chunk) for chunk in ordered] for k, c in columns.items() if _has(c)}
    return [round(x, 2) for x in xs], out


def _value(column: Column, i: int) -> float | None:
    v = column[i]
    return None if v is None else round(float(v), 3)


def _mean_of(column: Column, chunk: Sequence[int]) -> float | None:
    present = [float(v) for i in chunk if (v := column[i]) is not None]
    return round(sum(present) / len(present), 3) if present else None


def _scaled(values: list[float | None], numerator: float) -> list[float | None]:
    """`numerator / v` for each speed that isn't standing still."""
    return [None if v is None or v < MIN_PACE_SPEED else round(numerator / v, 2) for v in values]


def shape_streams(type_key: str | None, data: StreamData) -> ActivityStreams | None:
    """The charts' series for one activity: a run and a ride along the distance, the rest
    along time. None when there is nothing to draw."""
    sport = family(type_key)
    by_distance = sport in (Family.RUN, Family.RIDE) and _has(data.distance)
    axis: Column = data.distance if by_distance and data.distance is not None else data.time
    columns: dict[str, Column] = {}
    if sport in (Family.RUN, Family.RIDE, Family.SWIM) and data.speed is not None:
        columns["speed"] = data.speed
    if data.heart_rate is not None:
        columns["heart_rate"] = data.heart_rate
    if sport in (Family.RUN, Family.RIDE) and data.altitude is not None:
        columns["altitude"] = data.altitude
    if sport in (Family.RUN, Family.RIDE) and data.cadence is not None:
        columns["cadence"] = data.cadence
    if sport in (Family.RUN, Family.RIDE) and data.power is not None and _has(data.power):
        columns["power"] = data.power
    x, series = downsample(axis, columns)
    if not x or not series:
        return None
    speed = series.pop("speed", None)
    if speed is not None:
        if sport is Family.RUN:
            series = {"pace": _scaled(speed, 1000), **series}
        elif sport is Family.SWIM:
            series = {"pace100": _scaled(speed, 100), **series}
        else:
            series = {"speed": [None if v is None else round(v * 3.6, 2) for v in speed], **series}
    series = {k: v for k, v in series.items() if any(p is not None for p in v)}
    if not series:
        return None
    return ActivityStreams(axis="distance" if by_distance else "time", x=x, series=series)


# -- Splits -------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ActivitySplit:
    """A kilometre or a lap. Pace is `duration_s / distance_m`; the page works it out."""

    index: int
    distance_m: float
    duration_s: float
    avg_hr: float | None
    avg_speed: float | None  # m/s
    avg_power: float | None
    elevation_change_m: float | None


def _interpolate(xs: Sequence[float], ys: Sequence[float], at: float) -> float:
    """`ys` at `at` along ascending `xs`, held at the ends."""
    i = bisect_left(xs, at)
    if i <= 0:
        return ys[0]
    if i >= len(xs):
        return ys[-1]
    x0, x1 = xs[i - 1], xs[i]
    if x1 <= x0:
        return ys[i]
    return ys[i - 1] + (ys[i] - ys[i - 1]) * (at - x0) / (x1 - x0)


def km_splits(data: StreamData, size: float = 1000.0) -> list[ActivitySplit]:
    """One split per `size` metres of a run, the last one partial when it is 100 m or more.
    Time at a boundary is interpolated between the samples around it, so a pause inside a
    split counts in it."""
    if data.distance is None:
        return []
    ds: list[float] = []
    idx: list[int] = []
    for i, d in enumerate(data.distance):
        if d is None:
            continue
        if ds and d < ds[-1]:
            d = ds[-1]
        ds.append(float(d))
        idx.append(i)
    if len(ds) < 2 or ds[-1] < MIN_PARTIAL_KM:
        return []
    times = [float(data.time[i]) for i in idx]
    alts = [
        (d, float(a))
        for d, i in zip(ds, idx, strict=True)
        if (a := _at(data.altitude, i)) is not None
    ]
    total = ds[-1]
    edges = [k * size for k in range(int(total // size) + 1)]
    if total - edges[-1] >= MIN_PARTIAL_KM:
        edges.append(total)
    elif len(edges) > 1:
        edges[-1] = total  # a stub shorter than 100 m is folded into the last kilometre
    out: list[ActivitySplit] = []
    for n, (a, b) in enumerate(itertools.pairwise(edges), start=1):
        seconds = _interpolate(ds, times, b) - _interpolate(ds, times, a)
        inside = idx[bisect_right(ds, a) : bisect_right(ds, b)]
        hr = _mean_at(data.heart_rate, inside)
        power = _mean_at(data.power, inside)
        change = None
        if len(alts) >= 2:
            axs = [x for x, _ in alts]
            ays = [y for _, y in alts]
            change = round(_interpolate(axs, ays, b) - _interpolate(axs, ays, a), 1)
        out.append(
            ActivitySplit(
                index=n,
                distance_m=round(b - a, 1),
                duration_s=round(seconds, 1),
                avg_hr=None if hr is None else round(hr, 1),
                avg_speed=round((b - a) / seconds, 3) if seconds > 0 else None,
                avg_power=None if power is None else round(power, 1),
                elevation_change_m=change,
            )
        )
    return out


def _at(column: Column | None, i: int) -> float | None:
    return None if column is None else column[i]


def _mean_at(column: Column | None, indexes: Sequence[int]) -> float | None:
    if column is None:
        return None
    return mean([column[i] for i in indexes])


@dataclass(frozen=True, slots=True)
class LapIn:
    index: int
    distance_m: float | None
    duration_s: float | None
    avg_hr: int | None
    avg_speed: float | None
    avg_power: int | None
    ascent_m: int | None
    descent_m: int | None


def lap_splits(laps: Sequence[LapIn]) -> list[ActivitySplit]:
    """The file's laps as splits; a lap with no time is left out."""
    out: list[ActivitySplit] = []
    for lap in laps:
        if not lap.duration_s or lap.duration_s <= 0:
            continue
        change = (
            None
            if lap.ascent_m is None and lap.descent_m is None
            else float((lap.ascent_m or 0) - (lap.descent_m or 0))
        )
        out.append(
            ActivitySplit(
                index=lap.index,
                distance_m=round(lap.distance_m or 0.0, 1),
                duration_s=round(lap.duration_s, 1),
                avg_hr=None if lap.avg_hr is None else float(lap.avg_hr),
                avg_speed=lap.avg_speed,
                avg_power=None if lap.avg_power is None else float(lap.avg_power),
                elevation_change_m=change,
            )
        )
    return out


# -- Pool swims ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class LengthIn:
    index: int
    active: bool
    stroke: str | None
    strokes: int | None
    duration_s: float | None
    swolf: int | None


@dataclass(frozen=True, slots=True)
class SwimLength:
    index: int
    stroke: str | None
    strokes: int | None
    duration_s: float | None
    swolf: int | None
    set_index: int


@dataclass(frozen=True, slots=True)
class SwimSet:
    """Consecutive swum lengths; `rest_s` is the rest that follows them."""

    index: int
    lengths: int
    distance_m: float
    duration_s: float
    rest_s: float
    strokes: int | None
    swolf: float | None  # mean of the set's lengths
    stroke: str | None  # the commonest


def swim_sets(
    lengths: Sequence[LengthIn], pool_length_m: float
) -> tuple[list[SwimSet], list[SwimLength]]:
    """Sets (runs of swum lengths between rests) and the swum lengths with the set each is in."""
    runs: list[list[LengthIn]] = []
    rests: list[float] = []
    resting = False
    for length in sorted(lengths, key=lambda x: x.index):
        if length.active:
            if resting or not runs:
                runs.append([])
                rests.append(0.0)
            runs[-1].append(length)
            resting = False
        else:
            resting = True
            if runs:
                rests[-1] += length.duration_s or 0.0
    sets: list[SwimSet] = []
    swum: list[SwimLength] = []
    for n, (run, rest) in enumerate(zip(runs, rests, strict=True), start=1):
        strokes = [x.strokes for x in run if x.strokes is not None]
        swolfs = [float(x.swolf) for x in run if x.swolf is not None]
        names = Counter(x.stroke for x in run if x.stroke)
        sets.append(
            SwimSet(
                index=n,
                lengths=len(run),
                distance_m=round(len(run) * pool_length_m, 1),
                duration_s=round(sum(x.duration_s or 0.0 for x in run), 1),
                rest_s=round(rest, 1),
                strokes=sum(strokes) if strokes else None,
                swolf=round(sum(swolfs) / len(swolfs), 1) if swolfs else None,
                stroke=names.most_common(1)[0][0] if names else None,
            )
        )
        swum.extend(
            SwimLength(
                index=x.index,
                stroke=x.stroke,
                strokes=x.strokes,
                duration_s=x.duration_s,
                swolf=x.swolf,
                set_index=n,
            )
            for x in run
        )
    return sets, swum


# -- Zones --------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ActivityZones:
    """Seconds in heart-rate zones 1 to 5 (`below_s` under zone 1). `source` is whose zones:
    ours (the member's reference) or Garmin's own."""

    source: Literal["ours", "garmin"]
    below_s: int
    seconds: list[int]
    threshold: float | None


def heart_rate_zones(
    ours: Sequence[int] | None, garmin: Sequence[int | None] | None, threshold: float | None
) -> ActivityZones | None:
    if ours is not None and len(ours) == 6 and sum(ours) > 0:
        return ActivityZones("ours", ours[0], list(ours[1:]), threshold)
    if garmin is not None and len(garmin) == 5 and sum(s or 0 for s in garmin) > 0:
        return ActivityZones("garmin", 0, [s or 0 for s in garmin], None)
    return None


# -- Durability ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ActivityHalf:
    speed: float | None  # m/s
    heart_rate: float | None
    efficiency: float | None


def half_figures(type_key: str | None, series: Series) -> tuple[ActivityHalf, ActivityHalf] | None:
    """Speed, heart rate and efficiency over the first and second half of the moving time of a
    run or a ride of 20 minutes or more with heart rate, with the output `durability` uses."""
    sport = family(type_key)
    if sport not in (Family.RUN, Family.RIDE):
        return None
    grid = moving(series)
    if not grid.heart_rate or grid.seconds < dur.MIN_SECONDS or not grid.speed:
        return None
    output: Sequence[float | None]
    if sport is Family.RUN:
        graded = running.graded_speeds(grid.speed, running.grades(grid.distance, grid.altitude))
        output = [None if v is None else v * 60 for v in graded]
    elif grid.power and any(grid.power):
        output = grid.power
    else:
        output = [None if v is None else v * 60 for v in grid.speed]
    half = grid.seconds // 2
    figures: list[ActivityHalf] = []
    for lo, hi in ((0, half), (half, grid.seconds)):
        hr = grid.heart_rate[lo:hi]
        figures.append(
            ActivityHalf(
                speed=mean(grid.speed[lo:hi]),
                heart_rate=mean(hr),
                efficiency=dur.efficiency(output[lo:hi], hr),
            )
        )
    return figures[0], figures[1]


# -- Route --------------------------------------------------------------------------------


def _simplify(points: Sequence[tuple[float, float]], epsilon: float) -> list[int]:
    """Ramer-Douglas-Peucker: the indexes of the points that stay."""
    keep = [False] * len(points)
    keep[0] = keep[-1] = True
    stack = [(0, len(points) - 1)]
    while stack:
        a, b = stack.pop()
        if b <= a + 1:
            continue
        (ax, ay), (bx, by) = points[a], points[b]
        dx, dy = bx - ax, by - ay
        length = math.hypot(dx, dy)
        far, far_distance = a, -1.0
        for i in range(a + 1, b):
            px, py = points[i]
            d = (
                math.hypot(px - ax, py - ay)
                if length == 0
                else abs(dx * (ay - py) - (ax - px) * dy) / length
            )
            if d > far_distance:
                far, far_distance = i, d
        if far_distance > epsilon:
            keep[far] = True
            stack.extend([(a, far), (far, b)])
    return [i for i, k in enumerate(keep) if k]


def simplified_route(
    lat: Column | None, lon: Column | None, limit: int = ROUTE_POINTS
) -> list[tuple[float, float]] | None:
    """The route as at most `limit` (lat, lon) pairs in degrees that keep its shape; None when
    there is no position or the activity never left one spot."""
    if lat is None or lon is None:
        return None
    pairs = [
        (float(a), float(b))
        for a, b in zip(lat, lon, strict=True)
        if a is not None and b is not None
    ]
    if len(pairs) < 2:
        return None
    scale = math.cos(math.radians(sum(a for a, _ in pairs) / len(pairs)))
    flat = [(b * scale, a) for a, b in pairs]
    extent = max(
        max(x for x, _ in flat) - min(x for x, _ in flat),
        max(y for _, y in flat) - min(y for _, y in flat),
    )
    if extent < 1e-5:
        return None
    if len(pairs) > 4000:  # thin very long recordings first, to keep the search quick
        step = math.ceil(len(pairs) / 4000)
        pairs = pairs[::step] + ([pairs[-1]] if (len(pairs) - 1) % step else [])
        flat = [(b * scale, a) for a, b in pairs]
    if len(pairs) <= limit:
        keep = list(range(len(pairs)))
    else:
        low, high = 0.0, extent
        keep = _simplify(flat, high)
        for _ in range(24):
            middle = (low + high) / 2
            kept = _simplify(flat, middle)
            if len(kept) <= limit:
                high, keep = middle, kept
            else:
                low = middle
    return [(round(pairs[i][0], 5), round(pairs[i][1], 5)) for i in keep]


def local_start(started_at: datetime, start_local: datetime | None) -> datetime:
    """The wall-clock start, naive: the watch's own when stored, else UTC."""
    return start_local if start_local is not None else started_at.replace(tzinfo=None)
