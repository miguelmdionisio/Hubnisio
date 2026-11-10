"""Load from heart rate, and time in heart-rate zones (ADR-0009, "Derived per activity").

**Load** is an hrTSS-style score: the activity's TRIMP over the TRIMP of one hour at the
lactate-threshold heart rate, times 100. So one hour at threshold scores 100, half an hour
50, whatever the sport. TRIMP (Banister) sums, over each second of moving time,

    minutes * r * 0.64 * e^(1.92 * r),  r = (HR - rest) / (max - rest), held to 0…1

The weighting makes time near threshold count far more than easy time.

**The reference** (threshold, maximum and resting heart rate) comes from the member's
heart-rate zones for the sport, else their default zones; a value missing there comes from the
activity's file (the watch records the zones it used), then: threshold ≈ 0.89 * max, max ≈
threshold / 0.89, rest = 60 bpm. Without a threshold or a maximum there's no load.
"""

import math
from collections.abc import Sequence
from dataclasses import dataclass

THRESHOLD_OF_MAX = 0.89  # lactate threshold as a share of maximum heart rate
DEFAULT_REST = 60
# Zone floors as shares of threshold, when the member has no zones (Friel's five zones).
THRESHOLD_ZONE_FLOORS = (0.70, 0.85, 0.90, 0.95, 1.00)


@dataclass(frozen=True, slots=True)
class HeartRateReference:
    threshold: float
    max: float
    rest: float
    # Where the threshold came from: zones (the member's), file (the watch's), estimate.
    source: str


def heart_rate_reference(
    *,
    zones_threshold: float | None = None,
    zones_max: float | None = None,
    zones_rest: float | None = None,
    file_threshold: float | None = None,
    file_max: float | None = None,
    file_rest: float | None = None,
    rest: float | None = None,
) -> HeartRateReference | None:
    """The reference for one activity, from the member's zones first, then the file. `rest`
    is the member's resting heart rate that day, when the zones don't say."""
    threshold, source = zones_threshold, "zones"
    if threshold is None and file_threshold is not None:
        threshold, source = file_threshold, "file"
    maximum = zones_max or file_max
    if threshold is None and maximum is not None:
        threshold, source = maximum * THRESHOLD_OF_MAX, "estimate"
    if threshold is None:
        return None
    if maximum is None or maximum <= threshold:
        maximum = threshold / THRESHOLD_OF_MAX
    resting = zones_rest or rest or file_rest or DEFAULT_REST
    if resting >= threshold:
        resting = DEFAULT_REST if threshold > DEFAULT_REST else threshold / 2
    return HeartRateReference(threshold, maximum, resting, source)


def trimp(heart_rate: Sequence[float | None], reference: HeartRateReference) -> float:
    """Banister's TRIMP over a one-second column (gaps count nothing)."""
    total = 0.0
    for value in heart_rate:
        if value is not None:
            total += _weight(value, reference) / 60
    return total


def hr_load(heart_rate: Sequence[float | None], reference: HeartRateReference) -> float | None:
    """The hrTSS-style load: 100 for one hour at threshold. None without heart rate."""
    if all(value is None for value in heart_rate):
        return None
    hour = 60 * _weight(reference.threshold, reference)
    return 100 * trimp(heart_rate, reference) / hour if hour > 0 else None


def _weight(value: float, reference: HeartRateReference) -> float:
    reserve = (value - reference.rest) / (reference.max - reference.rest)
    reserve = min(max(reserve, 0.0), 1.0)
    return reserve * 0.64 * math.exp(1.92 * reserve)


def zone_floors(
    floors: Sequence[float | None] | None, reference: HeartRateReference | None
) -> list[float] | None:
    """The five zones' floors (bpm): the member's own when all five are known, else shares of
    the threshold."""
    if floors is not None and len(floors) == 5 and all(floor is not None for floor in floors):
        return [float(floor) for floor in floors if floor is not None]
    if reference is None:
        return None
    return [share * reference.threshold for share in THRESHOLD_ZONE_FLOORS]


def time_in_zones(heart_rate: Sequence[float | None], floors: Sequence[float]) -> list[int]:
    """Seconds below zone 1, then in zones 1 to 5, over a one-second column."""
    seconds = [0] * (len(floors) + 1)
    for value in heart_rate:
        if value is None:
            continue
        zone = sum(1 for floor in floors if value >= floor)
        seconds[zone] += 1
    return seconds
