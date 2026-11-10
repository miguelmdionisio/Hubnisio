"""Graded pace and an estimated VO2max for runs.

**Grade-adjusted speed** is the flat speed costing the same energy: speed * C(grade) / C(0),
with Minetti's cost of running (J/kg/m, grade as a fraction held to ±0.45):

    C(i) = 155.4 i⁵ - 30.4 i⁴ - 43.3 i³ + 46.3 i² + 19.5 i + 3.6

The grade at each second is the climb over the distance run between `GRADE_WINDOW` seconds
before and after it (0 when that's under `MIN_GRADE_RUN` metres, or without altitude).
**Normalized graded pace** applies normalized power's recipe to graded speed: the 30-second
rolling mean to the fourth power, averaged, fourth root.

**Estimated VO2max** (Runalyze's "effective VO2max"): the oxygen cost of the run's average
graded speed v (m/min) by Daniels and Gilbert, VO2 = -4.60 + 0.182258 v + 0.000104 v²,
over the share of VO2max the run's average heart rate implies by Swain's relation,
%VO2max = (%HRmax - 0.2812) / 0.7303. Graded speed stands in for Runalyze's correction per
metre climbed. Only for runs of `MIN_VO2_SECONDS` or more, between 60 and 100 % of max.
"""

from collections.abc import Sequence

from hubnisio.health.insights.series import Column, forward_filled, fourth_power_mean, mean

GRADE_WINDOW = 10  # seconds either side
MIN_GRADE_RUN = 10.0  # metres
MAX_GRADE = 0.45
MIN_VO2_SECONDS = 600
MIN_HR_SHARE = 0.6


def running_cost(grade: float) -> float:
    """Minetti's energy cost of running at a grade (fraction), J/kg/m."""
    i = min(max(grade, -MAX_GRADE), MAX_GRADE)
    return 155.4 * i**5 - 30.4 * i**4 - 43.3 * i**3 + 46.3 * i**2 + 19.5 * i + 3.6


FLAT_COST = running_cost(0.0)


def grades(distance: Sequence[float | None], altitude: Sequence[float | None]) -> list[float]:
    """The grade at each second of a one-second grid (0 without altitude)."""
    n = len(distance)
    if not n or len(altitude) != n:
        return [0.0] * n
    d = forward_filled(distance)
    a = forward_filled(altitude)
    out: list[float] = []
    for i in range(n):
        lo, hi = max(i - GRADE_WINDOW, 0), min(i + GRADE_WINDOW, n - 1)
        d_lo, d_hi, a_lo, a_hi = d[lo], d[hi], a[lo], a[hi]
        if d_lo is None or d_hi is None or a_lo is None or a_hi is None:
            out.append(0.0)
            continue
        run = d_hi - d_lo
        out.append((a_hi - a_lo) / run if run >= MIN_GRADE_RUN else 0.0)
    return out


def graded_speeds(speed: Sequence[float | None], grade: Sequence[float]) -> Column:
    """Each second's grade-adjusted speed (m/s)."""
    return [
        value * running_cost(grade[i]) / FLAT_COST if value is not None else None
        for i, value in enumerate(speed)
    ]


def normalized_graded_speed(graded: Sequence[float | None]) -> float | None:
    return fourth_power_mean(graded)


def vo2_cost(speed_m_per_min: float) -> float:
    """Daniels and Gilbert's oxygen cost of running at a speed, ml/kg/min."""
    v = speed_m_per_min
    return -4.60 + 0.182258 * v + 0.000104 * v * v


def vo2max_share(hr_share: float) -> float:
    """Swain's share of VO2max at a share of maximum heart rate."""
    return (hr_share - 0.2812) / 0.7303


def estimated_vo2max(
    graded: Sequence[float | None], heart_rate: Sequence[float | None], max_hr: float
) -> float | None:
    """VO2max from a run's average graded speed and average heart rate (one-second columns)."""
    if len(graded) < MIN_VO2_SECONDS or max_hr <= 0:
        return None
    speed = mean(graded)
    hr = mean(heart_rate)
    if speed is None or hr is None or speed <= 0:
        return None
    share = hr / max_hr
    if not MIN_HR_SHARE <= share <= 1.0:
        return None
    return vo2_cost(speed * 60) / vo2max_share(share)
