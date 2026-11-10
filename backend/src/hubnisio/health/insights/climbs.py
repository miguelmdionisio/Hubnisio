"""Sustained climbs and their climbing speed (VAM), for rides: what stands in for power when a
ride has none.

A climb runs from a low point to the highest point after it, until the road drops more than
`DROP` metres below that peak (or goes below the low point, which starts a new one). It counts
when it gains at least `MIN_GAIN` metres over at least `MIN_SECONDS` at an average grade of at
least `MIN_GRADE`. VAM is metres climbed per hour: gain / seconds * 3600.
"""

from collections.abc import Sequence
from dataclasses import dataclass

from hubnisio.health.insights.series import forward_filled

DROP = 10.0  # metres
MIN_GAIN = 50.0
MIN_SECONDS = 300
MIN_GRADE = 0.03


@dataclass(frozen=True, slots=True)
class Climb:
    start_s: int  # second of moving time it starts
    duration_s: int
    distance_m: float
    gain_m: float
    grade: float  # a fraction
    vam: float  # metres per hour


def climbs(distance: Sequence[float | None], altitude: Sequence[float | None]) -> list[Climb]:
    """The sustained climbs on a one-second grid."""
    n = len(altitude)
    if n == 0 or len(distance) != n:
        return []
    alt = forward_filled(altitude)
    dist = forward_filled(distance)
    found: list[Climb] = []

    def close(low: int, peak: int) -> None:
        a_low, a_peak, d_low, d_peak = alt[low], alt[peak], dist[low], dist[peak]
        if a_low is None or a_peak is None or d_low is None or d_peak is None:
            return
        gain, seconds, run = a_peak - a_low, peak - low, d_peak - d_low
        if gain < MIN_GAIN or seconds < MIN_SECONDS or run <= 0 or gain / run < MIN_GRADE:
            return
        found.append(Climb(low, seconds, run, gain, gain / run, gain / seconds * 3600))

    low = peak = 0
    for i in range(n):
        value, a_low, a_peak = alt[i], alt[low], alt[peak]
        if value is None or a_low is None or a_peak is None:
            low = peak = i
            continue
        if value > a_peak:
            peak = i
        elif a_peak - value > DROP or value < a_low:
            close(low, peak)
            low = peak = i
    close(low, peak)
    return found


def best_vam(found: Sequence[Climb]) -> float | None:
    return max((climb.vam for climb in found), default=None)
