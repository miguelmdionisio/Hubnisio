"""Garmin replies to rows (ADR-0009): pure functions, one per payload kind.

Each returns `Records`, the rows for each fact table without `user_id`; `health/ingest.py`
writes them. A reply that isn't the expected shape gives no rows rather than failing: the raw
reply is stored, so a fix here and a `renormalize` recover it.
"""

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any, cast

from pydantic import BaseModel, ValidationError

from hubnisio.health.models import SampleKind
from hubnisio.health.providers.garmin.schemas import (
    BodyBatteryDay,
    DailySummaries,
    FitnessAgeReply,
    HeartRateDay,
    HrvDay,
    HrvRange,
    HrvSummary,
    Profile,
    SleepSummary,
    Spo2Day,
    StepsDay,
    StressDay,
    Zones,
)

Row = dict[str, Any]


@dataclass
class Records:
    # Days from the daily summary: a value it gives replaces what's stored.
    daily: list[Row] = field(default_factory=list[Row])
    # Days from the stress, steps and Body Battery replies: they only fill what's missing.
    daily_fill: list[Row] = field(default_factory=list[Row])
    sleeps: list[Row] = field(default_factory=list[Row])
    hrv: list[Row] = field(default_factory=list[Row])
    samples: list[Row] = field(default_factory=list[Row])
    zones: list[Row] | None = None  # None: untouched; a list replaces them all
    fitness: list[Row] = field(default_factory=list[Row])
    weights: list[Row] = field(default_factory=list[Row])
    weight_goal: Row | None = None
    clear_weight_goal: bool = False
    time_zone: str | None = None


def normalize(kind: str, raw: Any, day_from: date | None) -> Records:
    """The rows in one reply of `kind`. `day_from` is the first day the request asked for."""
    if raw is None:
        return Records()
    normalizer = NORMALIZERS.get(kind)
    return normalizer(raw, day_from) if normalizer is not None else Records()


# Days


def _daily_summaries(raw: Any, _day: date | None) -> Records:
    reply = _parse(DailySummaries, raw)
    if reply is None:
        return Records()
    rows: list[Row] = []
    for item in reply.data:
        day = _day_of(item.calendar_date)
        if day is None:
            continue
        movement, calories, hr = item.movement, item.calories, item.heart_rate
        steps = movement.steps if movement else None
        stress, battery = item.stress, item.body_battery
        rows.append(
            {
                "day": day,
                "steps": _int(steps.value if steps else None),
                "step_goal": _int(steps.goal if steps else None),
                "distance_m": _dec(steps.distance_in_meters if steps else None, 1),
                "floors_ascended": _int(
                    movement.floors_ascended.value
                    if movement and movement.floors_ascended
                    else None
                ),
                "active_kcal": _int(calories.burned_active if calories else None),
                "resting_kcal": _int(calories.burned_resting if calories else None),
                "total_kcal": _int(calories.burned_total if calories else None),
                "resting_hr": _int(hr.resting_value if hr else None),
                "min_hr": _int(hr.min_value if hr else None),
                "max_hr": _int(hr.max_value if hr else None),
                "moderate_minutes": _int(
                    item.intensity_minutes.moderate if item.intensity_minutes else None
                ),
                "vigorous_minutes": _int(
                    item.intensity_minutes.vigorous if item.intensity_minutes else None
                ),
                "stress_avg": _stress_level(stress.avg_level if stress else None),
                "stress_max": _stress_level(stress.max_level if stress else None),
                "rest_stress_s": _seconds(stress.rest_ms if stress else None),
                "low_stress_s": _seconds(stress.low_ms if stress else None),
                "medium_stress_s": _seconds(stress.medium_ms if stress else None),
                "high_stress_s": _seconds(stress.high_ms if stress else None),
                "body_battery_charged": _int(battery.charged if battery else None),
                "body_battery_drained": _int(battery.drained if battery else None),
                "body_battery_min": _int(battery.min_value if battery else None),
                "body_battery_max": _int(battery.max_value if battery else None),
                "spo2_avg": _int(item.pulse_ox.avg_value if item.pulse_ox else None),
                "spo2_min": _int(item.pulse_ox.min_value if item.pulse_ox else None),
                "respiration_avg": _int(item.respiration.avg_value if item.respiration else None),
                "respiration_min": _int(item.respiration.min_value if item.respiration else None),
                "respiration_max": _int(item.respiration.max_value if item.respiration else None),
                "includes_wellness": item.includes_wellness_data,
            }
        )
    return Records(daily=rows)


def _stress(raw: Any, _day: date | None) -> Records:
    rows: list[Row] = []
    for item in _parse_list(StressDay, raw):
        day = _day_of(item.calendar_date)
        if day is None or item.values is None:
            continue
        values = item.values
        rows.append(
            {
                "day": day,
                "stress_avg": _stress_level(values.overall_stress_level),
                "rest_stress_s": _int(values.rest_seconds),
                "low_stress_s": _int(values.low_seconds),
                "medium_stress_s": _int(values.medium_seconds),
                "high_stress_s": _int(values.high_seconds),
            }
        )
    return Records(daily_fill=rows)


def _steps(raw: Any, _day: date | None) -> Records:
    rows: list[Row] = []
    for item in _parse_list(StepsDay, raw):
        day = _day_of(item.calendar_date)
        if day is None:
            continue
        rows.append(
            {
                "day": day,
                "steps": _int(item.total_steps),
                "step_goal": _int(item.step_goal),
                "distance_m": _dec(item.total_distance, 1),
            }
        )
    return Records(daily_fill=rows)


def _body_battery(raw: Any, _day: date | None) -> Records:
    records = Records()
    for item in _parse_list(BodyBatteryDay, raw):
        day = _day_of(item.date)
        if day is None:
            continue
        records.daily_fill.append(
            {
                "day": day,
                "body_battery_charged": _int(item.charged),
                "body_battery_drained": _int(item.drained),
            }
        )
        keys = {d.index: d.key for d in item.descriptors or [] if d.index is not None}
        records.samples += _series(SampleKind.BODY_BATTERY, day, keys, item.values, "level")
    return records


# Nights


def _sleep(raw: Any, _day: date | None) -> Records:
    rows: list[Row] = []
    items = [raw] if isinstance(raw, dict) else raw
    for item in _parse_list(SleepSummary, items):
        day = _day_of(item.calendar_date)
        if day is None or item.start_gmt is None or item.end_gmt is None:
            continue  # no night recorded
        if not item.sleep_seconds:
            continue
        offset = (
            round((item.start_local - item.start_gmt) / 60_000)
            if item.start_local is not None
            else None
        )
        score = item.sleep_scores.overall if item.sleep_scores else None
        rows.append(
            {
                "day": day,
                "garmin_id": item.id,
                "started_at": _from_ms(item.start_gmt),
                "ended_at": _from_ms(item.end_gmt),
                "utc_offset_minutes": offset,
                "sleep_s": _int(item.sleep_seconds),
                "deep_s": _int(item.deep_seconds),
                "light_s": _int(item.light_seconds),
                "rem_s": _int(item.rem_seconds),
                "awake_s": _int(item.awake_seconds),
                "unmeasurable_s": _int(item.unmeasurable_seconds),
                "nap_s": _int(item.nap_seconds),
                "awake_count": _int(item.awake_count),
                "score": _int(score.value if score else None),
                "score_qualifier": score.qualifier_key if score else None,
                "need_minutes": _int(item.sleep_need.actual if item.sleep_need else None),
                "avg_hr": _dec(item.avg_heart_rate, 1),
                "avg_respiration": _dec(item.average_respiration, 1),
                "min_respiration": _dec(item.lowest_respiration, 1),
                "max_respiration": _dec(item.highest_respiration, 1),
                "avg_spo2": _dec(item.average_spo2, 1),
                "min_spo2": _int(item.lowest_spo2),
                "avg_sleep_stress": _dec(item.avg_sleep_stress, 1),
                "from_device": item.sleep_from_device,
            }
        )
    return Records(sleeps=rows)


def _hrv_row(summary: HrvSummary) -> Row | None:
    day = _day_of(summary.calendar_date)
    if day is None:
        return None
    baseline = summary.baseline
    return {
        "day": day,
        "last_night_avg": _int(summary.last_night_avg),
        "last_night_5min_high": _int(summary.last_night_5min_high),
        "weekly_avg": _int(summary.weekly_avg),
        "status": summary.status,
        "baseline_low_upper": _int(baseline.low_upper if baseline else None),
        "baseline_balanced_low": _int(baseline.balanced_low if baseline else None),
        "baseline_balanced_upper": _int(baseline.balanced_upper if baseline else None),
    }


def _hrv(raw: Any, _day: date | None) -> Records:
    reply = _parse(HrvRange, raw)
    if reply is None:
        return Records()
    return Records(hrv=[row for s in reply.hrv_summaries if (row := _hrv_row(s)) is not None])


def _hrv_readings(raw: Any, day: date | None) -> Records:
    reply = _parse(HrvDay, raw)
    if reply is None:
        return Records()
    records = Records()
    if reply.hrv_summary is not None and (row := _hrv_row(reply.hrv_summary)) is not None:
        records.hrv.append(row)
        day = row["day"]
    if day is None:
        return records
    for reading in reply.hrv_readings or []:
        at = _from_iso(reading.reading_time_gmt)
        value = _dec(reading.hrv_value, 1)
        if at is not None and value is not None:
            records.samples.append({"kind": SampleKind.HRV, "at": at, "day": day, "value": value})
    return records


def _heart_rate(raw: Any, day: date | None) -> Records:
    reply = _parse(HeartRateDay, raw)
    if reply is None:
        return Records()
    day = _day_of(reply.calendar_date) or day
    if day is None:
        return Records()
    keys = {d.index: d.key for d in reply.descriptors or [] if d.index is not None}
    return Records(samples=_series(SampleKind.HEART_RATE, day, keys, reply.values, "heartrate"))


def _spo2(raw: Any, day: date | None) -> Records:
    reply = _parse(Spo2Day, raw)
    if reply is None:
        return Records()
    day = _day_of(reply.calendar_date) or day
    if day is None:
        return Records()
    keys = {d.index: d.key for d in reply.descriptors or [] if d.index is not None}
    return Records(samples=_series(SampleKind.SPO2, day, keys, reply.hourly, "spo2"))


# Profile, zones, fitness age, weight


def _profile(raw: Any, _day: date | None) -> Records:
    reply = _parse(Profile, raw)
    return Records(time_zone=reply.time_zone if reply else None)


def _hr_zones(raw: Any, _day: date | None) -> Records:
    if not isinstance(raw, list):
        return Records()
    rows: dict[str, Row] = {}
    for item in _parse_list(Zones, raw):
        if not item.sport:
            continue
        rows[item.sport] = {
            "sport": item.sport,
            "training_method": item.training_method,
            "max_hr": _int(item.max_hr),
            "lactate_threshold_hr": _int(item.lactate_threshold_hr),
            "resting_hr": _int(item.resting_hr),
            "zone1_floor": _int(item.zone1_floor),
            "zone2_floor": _int(item.zone2_floor),
            "zone3_floor": _int(item.zone3_floor),
            "zone4_floor": _int(item.zone4_floor),
            "zone5_floor": _int(item.zone5_floor),
        }
    return Records(zones=list(rows.values()))


def _fitness_age(raw: Any, day: date | None) -> Records:
    reply = _parse(FitnessAgeReply, raw)
    if reply is None or day is None or reply.fitness_age is None:
        return Records()
    parts = reply.components

    def part(name: str) -> float | None:
        component = getattr(parts, name, None) if parts else None
        return component.value if component is not None else None

    return Records(
        fitness=[
            {
                "day": day,
                "fitness_age": _dec(reply.fitness_age, 1),
                "previous_fitness_age": _dec(reply.previous_fitness_age, 1),
                "chronological_age": _int(reply.chronological_age),
                "resting_hr": _int(part("rhr")),
                "bmi": _dec(part("bmi"), 1),
                "vigorous_days_avg": _dec(part("vigorous_days_avg"), 1),
                "vigorous_minutes_avg": _dec(part("vigorous_minutes_avg"), 1),
            }
        ]
    )


def _weight(raw: Any, _day: date | None) -> Records:
    """Read defensively: the probe never saw a weigh-in. The range reply holds
    `dailyWeightSummaries`, each with `allWeightMetrics` or a `latestWeight`; the `all` reply is a
    list. An entry needs a weight (grams) and a time."""
    entries: list[dict[str, Any]] = []
    summaries: Iterable[Any] = []
    if isinstance(raw, dict):
        summaries = _dicts(cast(dict[str, Any], raw).get("dailyWeightSummaries"))
    elif isinstance(raw, list):
        summaries = _dicts(raw)
    for summary in summaries:
        metrics = _dicts(summary.get("allWeightMetrics"))
        if metrics:
            entries += metrics
        elif isinstance(latest := summary.get("latestWeight"), dict):
            entries.append(cast(dict[str, Any], latest))
        elif "weight" in summary:
            entries.append(summary)
    rows: dict[datetime, Row] = {}
    for entry in entries:
        weight = _kg(entry.get("weight"))
        at = _moment(entry.get("timestampGMT")) or _moment(entry.get("date"))
        day = _day_of(entry.get("calendarDate"))
        if at is None and day is not None:
            at = datetime(day.year, day.month, day.day, tzinfo=UTC)
        if weight is None or at is None:
            continue
        source = entry.get("sourceType")
        rows[at] = {
            "measured_at": at,
            "day": day or at.date(),
            "weight_kg": weight,
            "bmi": _dec(_number(entry.get("bmi")), 1),
            "body_fat_pct": _dec(_number(entry.get("bodyFat")), 1),
            "body_water_pct": _dec(_number(entry.get("bodyWater")), 1),
            "muscle_mass_kg": _kg(entry.get("muscleMass")),
            "bone_mass_kg": _kg(entry.get("boneMass")),
            "source": source[:32] if isinstance(source, str) else None,
        }
    return Records(weights=list(rows.values()))


def _weight_goal(raw: Any, _day: date | None) -> Records:
    """`userGoals` is a list (empty when there's no goal); its fields weren't seen in the probe,
    so the target is the first of `goalValue`, `targetValue` or `value` (grams)."""
    if not isinstance(raw, dict):
        return Records()
    for goal in _dicts(cast(dict[str, Any], raw).get("userGoals")):
        target = next(
            (
                kg
                for name in ("goalValue", "targetValue", "value")
                if (kg := _kg(goal.get(name))) is not None
            ),
            None,
        )
        starts = goal.get("startDate")
        starts_on = _day_of(starts) or (moment.date() if (moment := _moment(starts)) else None)
        if target is not None:
            return Records(weight_goal={"target_kg": target, "starts_on": starts_on})
    return Records(clear_weight_goal=True)


NORMALIZERS: dict[str, Callable[[Any, date | None], Records]] = {
    "profile": _profile,
    "hr_zones": _hr_zones,
    "daily_summaries": _daily_summaries,
    "hrv": _hrv,
    "sleep": _sleep,
    "body_battery": _body_battery,
    "stress": _stress,
    "steps": _steps,
    "weight": _weight,
    "hrv_readings": _hrv_readings,
    "heart_rate": _heart_rate,
    "spo2": _spo2,
    "fitness_age": _fitness_age,
    "weight_goal": _weight_goal,
}


# Helpers


def _parse[M: BaseModel](model: type[M], raw: Any) -> M | None:
    if not isinstance(raw, dict):
        return None
    try:
        return model.model_validate(raw)
    except ValidationError:
        return None


def _parse_list[M: BaseModel](model: type[M], raw: Any) -> list[M]:
    """The items of a list reply that parse; the others are skipped."""
    if not isinstance(raw, list):
        return []
    return [parsed for item in cast(list[Any], raw) if (parsed := _parse(model, item))]


def _dicts(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [cast(dict[str, Any], item) for item in cast(list[Any], value) if isinstance(item, dict)]


def _series(
    kind: SampleKind,
    day: date,
    keys: dict[int, str | None],
    values: list[list[Any]] | None,
    value_key: str,
) -> list[Row]:
    """Samples from Garmin's `[[timestamp, value, …], …]` arrays, whose columns a descriptor
    list names. Without descriptors: the timestamp first, the value second."""
    names = {index: (key or "").lower() for index, key in keys.items()}
    at_index = next((i for i, name in names.items() if name == "timestamp"), 0)
    value_index = next((i for i, name in names.items() if value_key in name), 1)
    rows: dict[datetime, Row] = {}
    for item in values or []:
        if not isinstance(item, list) or len(item) <= max(at_index, value_index):
            continue
        at = _moment(item[at_index])
        value = _dec(_number(item[value_index]), 1)
        if at is None or value is None or value < 0:
            continue  # Garmin marks gaps with null or a negative value
        rows[at] = {"kind": kind, "at": at, "day": day, "value": value}
    return list(rows.values())


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value)


def _int(value: float | None) -> int | None:
    return round(value) if value is not None else None


def _seconds(milliseconds: float | None) -> int | None:
    return round(milliseconds / 1000) if milliseconds is not None else None


def _stress_level(value: float | None) -> int | None:
    """Garmin's stress levels run 0 to 100; negative values mean too little data."""
    return round(value) if value is not None and value >= 0 else None


def _dec(value: float | None, places: int) -> Decimal | None:
    if value is None:
        return None
    return round(Decimal(str(value)), places)


def _kg(value: Any) -> Decimal | None:
    """Garmin's weights are in grams."""
    grams = _number(value)
    if grams is None or grams <= 0:
        return None
    return round(Decimal(str(grams)) / 1000, 3)


def _day_of(value: Any) -> date | None:
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def _from_ms(milliseconds: int) -> datetime:
    return datetime(1970, 1, 1, tzinfo=UTC) + timedelta(milliseconds=milliseconds)


def _moment(value: Any) -> datetime | None:
    """A time as Unix milliseconds or an ISO string in UTC."""
    if isinstance(value, int | float) and not isinstance(value, bool):
        return _from_ms(int(value))
    return _from_iso(value) if isinstance(value, str) else None


def _from_iso(value: str | None) -> datetime | None:
    """Garmin's GMT times come without a zone, e.g. 2025-02-01T03:12:34.0."""
    if not value:
        return None
    try:
        moment = datetime.fromisoformat(value)
    except ValueError:
        return None
    return moment.replace(tzinfo=UTC) if moment.tzinfo is None else moment.astimezone(UTC)
