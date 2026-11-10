"""An activity's samples on a regular one-second grid of moving time.

A watch records about once a second, less often when it saves battery ("smart recording"), and
not at all while paused. `moving` puts the samples on a one-second grid: a gap is filled between
its two ends (linearly where both have a value, else the earlier value held) when it lasts up to
`MAX_GAP` seconds, or when the distance shows the athlete kept moving through it (at least
`MIN_MOVING_SPEED`, for up to `MAX_FILL` seconds). Any other gap is a pause and is cut out, so
the grid is moving time. Every per-activity result is computed over this grid.
"""

import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

MAX_GAP = 5  # seconds: a longer gap between two samples is a pause, unless still moving
MIN_MOVING_SPEED = 0.5  # m/s over a longer gap: still moving (smart recording)
MAX_FILL = 300  # seconds: never fill a longer gap

Column = list[float | None]


@dataclass(frozen=True, slots=True)
class Series:
    """Samples as columns of the same length. `time` is seconds from the start; the others hold
    None where a sample has no value, or are empty when the activity has none at all.

    Units: distance m (cumulative), heart rate bpm, speed m/s, altitude m, cadence steps/min
    for runs (rpm for rides), power W."""

    time: Sequence[float]
    distance: Sequence[float | None] = ()
    heart_rate: Sequence[float | None] = ()
    speed: Sequence[float | None] = ()
    altitude: Sequence[float | None] = ()
    cadence: Sequence[float | None] = ()
    power: Sequence[float | None] = ()


@dataclass(frozen=True, slots=True)
class Grid:
    """One value per second of moving time; each column as long as `seconds`."""

    seconds: int
    distance: Column = field(default_factory=Column)
    heart_rate: Column = field(default_factory=Column)
    speed: Column = field(default_factory=Column)
    altitude: Column = field(default_factory=Column)
    cadence: Column = field(default_factory=Column)
    power: Column = field(default_factory=Column)


COLUMNS = ("distance", "heart_rate", "speed", "altitude", "cadence", "power")


def moving(series: Series) -> Grid:
    """The series on a one-second grid of moving time."""
    times = list(series.time)
    n = len(times)
    spans = _spans(times, series.distance)
    columns: dict[str, Column] = {}
    for name in COLUMNS:
        values: Sequence[float | None] = getattr(series, name)
        if len(values) != n or all(value is None for value in values):
            columns[name] = []
            continue
        out: Column = []
        held: float | None = None
        for i in range(n):
            value = values[i]
            if value is not None:
                held = value
            span = spans[i]
            nxt = values[i + 1] if i + 1 < n else None
            for step in range(span):
                if step == 0 or value is None or nxt is None:
                    out.append(value if step == 0 and value is not None else held)
                else:
                    out.append(value + (nxt - value) * step / span)
        columns[name] = out
    return Grid(seconds=sum(spans), **columns)


def _spans(times: Sequence[float], distance: Sequence[float | None]) -> list[int]:
    """How many grid seconds each sample stands for: the gap to the next one, or one second
    when the gap is a pause (and for the last sample)."""
    n = len(times)
    has_distance = len(distance) == n
    spans: list[int] = []
    for i in range(n):
        gap = round(times[i + 1] - times[i]) if i + 1 < n else 1
        kept_moving = (
            MAX_GAP < gap <= MAX_FILL and has_distance and _moved(distance[i], distance[i + 1], gap)
        )
        spans.append(gap if 1 <= gap <= MAX_GAP or kept_moving else 1)
    return spans


def _moved(start: float | None, end: float | None, seconds: int) -> bool:
    return start is not None and end is not None and (end - start) / seconds >= MIN_MOVING_SPEED


def mean(values: Sequence[float | None]) -> float | None:
    present = [value for value in values if value is not None]
    return sum(present) / len(present) if present else None


def rolling(values: Sequence[float | None], width: int) -> Column:
    """The mean of each `width`-second window ending at each second (None until the window
    is full, or when it holds a gap)."""
    out: Column = []
    total = 0.0
    missing = 0
    for i, value in enumerate(values):
        if value is None:
            missing += 1
        else:
            total += value
        if i >= width:
            old = values[i - width]
            if old is None:
                missing -= 1
            else:
                total -= old
        out.append(total / width if i >= width - 1 and missing == 0 else None)
    return out


def fourth_power_mean(values: Sequence[float | None], width: int = 30) -> float | None:
    """Normalized power's recipe: the `width`-second rolling mean, raised to the fourth power,
    averaged, and its fourth root taken. Also gives normalized graded pace from graded speed."""
    smoothed = [value for value in rolling(values, width) if value is not None]
    if not smoothed:
        return None
    return (sum(value**4 for value in smoothed) / len(smoothed)) ** 0.25


def forward_filled(values: Sequence[float | None]) -> Column:
    """Each gap takes the last value before it (the first values, the first one present)."""
    first = next((value for value in values if value is not None), None)
    out: Column = []
    held = first
    for value in values:
        if value is not None:
            held = value
        out.append(held)
    return out


def coefficient_of_variation(values: Sequence[float | None]) -> float | None:
    present = [value for value in values if value is not None]
    if len(present) < 2:
        return None
    average = sum(present) / len(present)
    if average <= 0:
        return None
    variance = sum((value - average) ** 2 for value in present) / len(present)
    return math.sqrt(variance) / average


def halves[T](values: Sequence[T]) -> tuple[Sequence[T], Sequence[T]]:
    middle = len(values) // 2
    return values[:middle], values[middle:]


def apply(values: Sequence[float | None], fn: Callable[[float], float]) -> Column:
    return [fn(value) if value is not None else None for value in values]
