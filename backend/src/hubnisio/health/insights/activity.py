"""Everything derived from one activity's samples, in one call (ADR-0009): what the sync and
`renormalize` store in `activity_derived`.

`derive` takes the samples (`Series`), the sport, the heart-rate reference and zones, and for a
pool swim its lengths. Each result is None (or empty) when the activity can't give it: no heart
rate, no power, too short, not that sport.
"""

import enum
from collections.abc import Sequence
from dataclasses import dataclass, field

from hubnisio.health.insights import climbs as climbing
from hubnisio.health.insights import curves, durability, load, running
from hubnisio.health.insights.series import Series, fourth_power_mean, mean, moving


class Family(enum.StrEnum):
    RUN = "run"
    RIDE = "ride"
    SWIM = "swim"
    OTHER = "other"


_RUN_KEYS = ("running", "trail_running", "track_running", "treadmill_running", "street_running")
_POOL_KEYS = ("lap_swimming",)


def family(type_key: str | None) -> Family:
    """The sport family of a Garmin activity type key (running, indoor_cycling, …)."""
    key = (type_key or "").lower()
    if key in _RUN_KEYS or key.endswith("_running"):
        return Family.RUN
    if "cycling" in key or "biking" in key or key in ("virtual_ride", "bmx"):
        return Family.RIDE
    if "swimming" in key:
        return Family.SWIM
    return Family.OTHER


def is_pool(type_key: str | None) -> bool:
    return (type_key or "").lower() in _POOL_KEYS


@dataclass(frozen=True, slots=True)
class Derived:
    moving_s: int
    hr_threshold: float | None = None
    hr_max: float | None = None
    hr_rest: float | None = None
    hr_reference_source: str | None = None
    hr_load: float | None = None
    # Seconds below zone 1, then in zones 1 to 5.
    hr_zone_s: list[int] | None = None
    # Aligned with curves.CURVE_DURATIONS.
    power_curve: list[float | None] | None = None
    hr_curve: list[float | None] | None = None
    speed_curve: list[float | None] | None = None
    # Seconds by distance in metres.
    best_efforts: dict[int, float] = field(default_factory=dict[int, float])
    gap_speed: float | None = None  # m/s
    ngp_speed: float | None = None  # m/s
    efficiency_factor: float | None = None
    decoupling_pct: float | None = None
    steady: bool | None = None
    vo2max: float | None = None
    climbs: list[climbing.Climb] = field(default_factory=list[climbing.Climb])
    best_vam: float | None = None


def derive(
    series: Series,
    *,
    type_key: str | None,
    reference: load.HeartRateReference | None,
    zone_floors: Sequence[float | None] | None = None,
    lengths: Sequence[curves.Length] = (),
    pool_length_m: float | None = None,
) -> Derived:
    sport = family(type_key)
    grid = moving(series)
    hr = grid.heart_rate
    floors = load.zone_floors(zone_floors, reference)

    graded = None
    gap_speed = ngp_speed = vo2max = None
    if sport is Family.RUN and grid.speed:
        graded = running.graded_speeds(grid.speed, running.grades(grid.distance, grid.altitude))
        gap_speed = mean(graded)
        ngp_speed = running.normalized_graded_speed(graded)
        if reference is not None and hr:
            vo2max = running.estimated_vo2max(graded, hr, reference.max)

    efforts: dict[int, float] = {}
    if sport is Family.RUN and grid.distance:
        efforts = curves.best_efforts(grid.distance, curves.RUN_DISTANCES)
    elif sport is Family.SWIM:
        if is_pool(type_key) and lengths and pool_length_m:
            efforts = curves.swim_best_efforts(lengths, pool_length_m)
        elif grid.distance:
            efforts = curves.best_efforts(grid.distance, curves.SWIM_DISTANCES)

    steady = _durability(sport, grid.speed, grid.power, hr, graded, ngp_speed)

    found: list[climbing.Climb] = []
    if sport is Family.RIDE and grid.altitude and grid.distance:
        found = climbing.climbs(grid.distance, grid.altitude)

    return Derived(
        moving_s=grid.seconds,
        hr_threshold=reference.threshold if reference else None,
        hr_max=reference.max if reference else None,
        hr_rest=reference.rest if reference else None,
        hr_reference_source=reference.source if reference else None,
        hr_load=load.hr_load(hr, reference) if reference and hr else None,
        hr_zone_s=load.time_in_zones(hr, floors) if floors and hr else None,
        power_curve=curves.mean_max(grid.power) if grid.power else None,
        hr_curve=curves.mean_max(hr) if hr else None,
        speed_curve=curves.mean_max(grid.speed) if grid.speed else None,
        best_efforts=efforts,
        gap_speed=gap_speed,
        ngp_speed=ngp_speed,
        efficiency_factor=steady.efficiency_factor if steady else None,
        decoupling_pct=steady.decoupling_pct if steady else None,
        steady=steady.steady if steady else None,
        vo2max=vo2max,
        climbs=found,
        best_vam=climbing.best_vam(found),
    )


def _durability(
    sport: Family,
    speed: Sequence[float | None],
    power: Sequence[float | None],
    hr: Sequence[float | None],
    graded: Sequence[float | None] | None,
    ngp_speed: float | None,
) -> durability.Durability | None:
    """Runs: graded speed (m/min). Rides: power when they have it, else speed (m/min)."""
    if not hr:
        return None
    if sport is Family.RUN and graded is not None:
        per_minute = [value * 60 if value is not None else None for value in graded]
        overall = ngp_speed * 60 if ngp_speed is not None else None
        return durability.durability(per_minute, hr, overall_output=overall)
    if sport is Family.RIDE and power and any(value for value in power):
        return durability.durability(power, hr, overall_output=fourth_power_mean(power))
    if sport is Family.RIDE and speed:
        per_minute = [value * 60 if value is not None else None for value in speed]
        return durability.durability(per_minute, hr)
    return None
