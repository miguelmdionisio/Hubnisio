"""Efficiency factor and aerobic decoupling, for steady efforts of 20 minutes or more.

- **Efficiency factor (EF):** output per heartbeat: average output over average heart rate.
  Output is normalized graded speed in m/min for runs, normalized power for rides with power,
  else average speed in m/min.
- **Aerobic decoupling (Pa:HR):** EF of the first half of moving time against the second,
  (EF₁ - EF₂) / EF₁ * 100 %. Under 5 % is usually read as aerobically durable.
- **Steady:** the 30-second rolling output varies little (coefficient of variation at most
  `STEADY_CV`). Intervals still get EF and decoupling; `steady` says whether to trust them.
"""

from collections.abc import Sequence
from dataclasses import dataclass

from hubnisio.health.insights.series import coefficient_of_variation, halves, mean, rolling

MIN_SECONDS = 1200
STEADY_CV = 0.15


@dataclass(frozen=True, slots=True)
class Durability:
    efficiency_factor: float
    decoupling_pct: float
    steady: bool


def efficiency(output: Sequence[float | None], heart_rate: Sequence[float | None]) -> float | None:
    """Average output over average heart rate, over the seconds that have both."""
    pairs = [
        (o, h) for o, h in zip(output, heart_rate, strict=True) if o is not None and h is not None
    ]
    if not pairs:
        return None
    hr = sum(h for _, h in pairs) / len(pairs)
    return (sum(o for o, _ in pairs) / len(pairs)) / hr if hr > 0 else None


def durability(
    output: Sequence[float | None],
    heart_rate: Sequence[float | None],
    *,
    overall_output: float | None = None,
) -> Durability | None:
    """EF and decoupling over a one-second grid; None under 20 minutes or without heart
    rate. `overall_output` (normalized power or graded speed) replaces the average output in
    the overall EF."""
    if len(output) < MIN_SECONDS or len(heart_rate) != len(output):
        return None
    overall = efficiency(output, heart_rate)
    first_output, second_output = halves(output)
    first_hr, second_hr = halves(heart_rate)
    first = efficiency(first_output, first_hr)
    second = efficiency(second_output, second_hr)
    if overall is None or first is None or second is None or first <= 0:
        return None
    if overall_output is not None and (hr := mean(heart_rate)):
        overall = overall_output / hr
    variation = coefficient_of_variation(rolling(output, 30))
    return Durability(
        efficiency_factor=overall,
        decoupling_pct=(first - second) / first * 100,
        steady=variation is not None and variation <= STEADY_CV,
    )
