"""Mean-maximal curves and best efforts.

- **Mean-maximal:** for each standard duration, the highest average of a one-second column
  (power, heart rate, speed) over any window that long. A window must hold a value every
  second; the grid is moving time, so pauses are already cut out.
- **Best efforts:** for each standard distance, the shortest time over any stretch covering
  it. The stretch's start is interpolated between two samples, so a steady 4 m/s covers
  400 m in exactly 100 s.
"""

from collections.abc import Sequence
from dataclasses import dataclass

# Seconds: 1 s to 2 h.
CURVE_DURATIONS: tuple[int, ...] = (
    1,
    5,
    10,
    15,
    30,
    60,
    120,
    300,
    600,
    1200,
    1800,
    3600,
    5400,
    7200,
)
# Metres. 1609 is the mile, 21097 and 42195 the half and the marathon.
RUN_DISTANCES: tuple[int, ...] = (400, 1000, 1609, 5000, 10000, 21097, 42195)
SWIM_DISTANCES: tuple[int, ...] = (100, 200, 400, 800, 1500)


def mean_max(
    values: Sequence[float | None], durations: Sequence[int] = CURVE_DURATIONS
) -> list[float | None]:
    """The best average over each duration, None where the column is too short or has no
    gap-free window that long. Aligned with `durations`."""
    n = len(values)
    sums = [0.0] * (n + 1)
    gaps = [0] * (n + 1)
    for i, value in enumerate(values):
        sums[i + 1] = sums[i] + (value or 0.0)
        gaps[i + 1] = gaps[i] + (value is None)
    curve: list[float | None] = []
    for duration in durations:
        best: float | None = None
        for end in range(duration, n + 1):
            if gaps[end] - gaps[end - duration]:
                continue
            total = sums[end] - sums[end - duration]
            if best is None or total > best:
                best = total
        curve.append(best / duration if best is not None else None)
    return curve


def fastest(times: Sequence[float], distances: Sequence[float], target: float) -> float | None:
    """The shortest time to cover `target` metres. `times` rise, `distances` (cumulative)
    never fall; both the same length. None when the whole is shorter than the target."""
    best: float | None = None
    j = 0
    for i in range(len(times)):
        if distances[i] - distances[0] < target:
            continue
        # The latest sample j still at least `target` before i.
        while j + 1 < i and distances[i] - distances[j + 1] >= target:
            j += 1
        at = distances[i] - target  # where the stretch starts
        start = times[j]
        covered = distances[j + 1] - distances[j] if j + 1 <= i else 0.0
        if covered > 0 and at > distances[j]:
            start += (times[j + 1] - times[j]) * (at - distances[j]) / covered
        elapsed = times[i] - start
        if best is None or elapsed < best:
            best = elapsed
    return best


def best_efforts(
    distance: Sequence[float | None], targets: Sequence[int] = RUN_DISTANCES
) -> dict[int, float]:
    """Best efforts from a one-second grid's cumulative distance, by target distance (only
    those covered)."""
    points = [(float(t), d) for t, d in enumerate(distance) if d is not None]
    if len(points) < 2:
        return {}
    times = [t for t, _ in points]
    distances = _non_decreasing([d for _, d in points])
    return {
        target: round(elapsed, 1)
        for target in targets
        if (elapsed := fastest(times, distances, target)) is not None
    }


@dataclass(frozen=True, slots=True)
class Length:
    """One pool length: its time, and whether it was swum (False: a rest)."""

    elapsed_s: float
    active: bool


def swim_best_efforts(
    lengths: Sequence[Length], pool_length_m: float, targets: Sequence[int] = SWIM_DISTANCES
) -> dict[int, float]:
    """Best efforts in a pool, over unbroken runs of swum lengths (a rest ends a run)."""
    best: dict[int, float] = {}
    runs: list[list[Length]] = [[]]
    for length in lengths:
        if length.active:
            runs[-1].append(length)
        elif runs[-1]:
            runs.append([])
    for run in runs:
        times = [0.0]
        distances = [0.0]
        for length in run:
            times.append(times[-1] + length.elapsed_s)
            distances.append(distances[-1] + pool_length_m)
        for target in targets:
            elapsed = fastest(times, distances, target)
            if elapsed is not None and (target not in best or elapsed < best[target]):
                best[target] = round(elapsed, 1)
    return dict(sorted(best.items()))


def _non_decreasing(values: Sequence[float]) -> list[float]:
    """A GPS distance can step back a little; keep it from falling."""
    out: list[float] = []
    for value in values:
        out.append(max(value, out[-1]) if out else value)
    return out
