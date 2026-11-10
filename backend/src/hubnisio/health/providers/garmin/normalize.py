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
    # Activities from the search: a value given replaces what's stored.
    activities: list[Row] = field(default_factory=list[Row])
    # Activities from their detail: only fill what the search left empty.
    activity_fill: list[Row] = field(default_factory=list[Row])


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


# Activities

# Each column: the keys holding it in a search item, then in a detail's summaryDTO.
_ACTIVITY_NUMBERS: tuple[tuple[str, tuple[str, ...], int | None], ...] = (
    # (column, keys, decimal places; None: an integer)
    ("duration_s", ("duration",), 1),
    ("elapsed_s", ("elapsedDuration",), 1),
    ("moving_s", ("movingDuration",), 1),
    ("distance_m", ("distance",), 1),
    ("elevation_gain_m", ("elevationGain",), 1),
    ("elevation_loss_m", ("elevationLoss",), 1),
    ("min_elevation_m", ("minElevation",), 1),
    ("max_elevation_m", ("maxElevation",), 1),
    ("avg_hr", ("averageHR",), None),
    ("max_hr", ("maxHR",), None),
    ("avg_speed", ("averageSpeed",), 3),
    ("max_speed", ("maxSpeed",), 3),
    ("avg_gap_speed", ("avgGradeAdjustedSpeed",), 3),
    ("avg_power", ("avgPower", "averagePower"), None),
    ("max_power", ("maxPower",), None),
    ("norm_power", ("normPower", "normalizedPower"), None),
    (
        "avg_cadence",
        (
            "averageRunningCadenceInStepsPerMinute",
            "averageRunCadence",
            "averageBikingCadenceInRevPerMinute",
            "averageBikeCadence",
            "averageSwimCadenceInStrokesPerMinute",
            "averageSwimCadence",
        ),
        1,
    ),
    (
        "max_cadence",
        (
            "maxRunningCadenceInStepsPerMinute",
            "maxRunCadence",
            "maxBikingCadenceInRevPerMinute",
            "maxBikeCadence",
            "maxSwimCadenceInStrokesPerMinute",
            "maxSwimCadence",
        ),
        1,
    ),
    ("calories", ("calories",), None),
    ("steps", ("steps",), None),
    ("garmin_load", ("activityTrainingLoad",), 1),
    ("aerobic_te", ("aerobicTrainingEffect", "trainingEffect"), 1),
    ("anaerobic_te", ("anaerobicTrainingEffect",), 1),
    ("moderate_minutes", ("moderateIntensityMinutes",), None),
    ("vigorous_minutes", ("vigorousIntensityMinutes",), None),
    ("body_battery_change", ("differenceBodyBattery",), None),
    ("ground_contact_ms", ("avgGroundContactTime", "groundContactTime"), 1),
    ("vertical_oscillation_cm", ("avgVerticalOscillation", "verticalOscillation"), 1),
    ("vertical_ratio_pct", ("avgVerticalRatio", "verticalRatio"), 1),
    ("stride_length_cm", ("avgStrideLength", "strideLength"), 1),
    ("active_lengths", ("activeLengths",), None),
    ("strokes", ("strokes",), None),
    ("avg_strokes", ("avgStrokes",), 1),
    ("avg_swolf", ("averageSwolf",), 1),
    ("avg_stroke_distance_m", ("avgStrokeDistance",), 2),
    ("lap_count", ("lapCount",), None),
)
_ZONES = 5
# No stroke covers 10 m: a stroke distance at or above this is in centimetres.
_STROKE_CM_FROM = 10


def _activities(raw: Any, _day: date | None) -> Records:
    """A page of the activity search: a list of summaries."""
    rows = [
        row for item in _dicts(raw) if (row := _activity_row(item, item, None, item)) is not None
    ]
    return Records(activities=rows)


def _activity_detail(raw: Any, _day: date | None) -> Records:
    """One activity's detail: fills what the search left out, and creates the activity when
    the search never listed it (a multisport leg)."""
    if not isinstance(raw, dict):
        return Records()
    detail = cast(dict[str, Any], raw)
    summary = detail.get("summaryDTO")
    metadata = detail.get("metadataDTO")
    if not isinstance(summary, dict):
        return Records()
    meta = cast(dict[str, Any], metadata) if isinstance(metadata, dict) else {}
    row = _activity_row(detail, cast(dict[str, Any], summary), meta, detail)
    return Records(activity_fill=[row] if row is not None else [])


def _activity_row(
    top: dict[str, Any],
    numbers: dict[str, Any],
    meta: dict[str, Any] | None,
    raw: dict[str, Any],
) -> Row | None:
    """A row for `activities` from a search item (`top`, `numbers` and `raw` the item, no
    `meta`) or a detail (`numbers` its summaryDTO, `meta` its metadataDTO)."""
    activity_id = _number(top.get("activityId"))
    activity_type = _dict(top.get("activityType")) or _dict(top.get("activityTypeDTO"))
    sport = activity_type.get("typeKey")
    started_at = _from_iso(_str(numbers.get("startTimeGMT")) or _str(top.get("startTimeGMT")))
    if activity_id is None or not isinstance(sport, str) or started_at is None:
        return None
    event_type = _dict(top.get("eventType")) or _dict(top.get("eventTypeDTO"))
    meta = meta or {}
    local = _str(numbers.get("startTimeLocal")) or _str(top.get("startTimeLocal"))
    local_at = _from_iso(local)
    child_ids = [int(child) for child in meta.get("childIds") or [] if _number(child) is not None]
    row: Row = {
        "activity_id": int(activity_id),
        "name": _str(top.get("activityName"), 200),
        "sport": sport[:48],
        "event_type": _str(event_type.get("typeKey"), 32),
        "started_at": started_at,
        "start_local": local_at.replace(tzinfo=None) if local_at else None,
        "time_zone": _str(_dict(top.get("timeZoneUnitDTO")).get("timeZone"), 64),
        "te_label": _str(numbers.get("trainingEffectLabel"), 32),
        "hr_zone_s": _zone_seconds(numbers, "hrTimeInZone_"),
        "power_zone_s": _zone_seconds(numbers, "powerTimeInZone_"),
        "pool_length_m": _pool_length(numbers),
        "fastest_splits": {
            key.removeprefix("fastestSplit_"): value
            for key, item in numbers.items()
            if key.startswith("fastestSplit_") and (value := _number(item)) is not None
        }
        or None,
        "manual": _bool(top.get("manualActivity"), meta.get("manualActivity")),
        "is_parent": bool(
            _bool(top.get("isParent"), top.get("parent"), top.get("isMultiSportParent"))
        ),
        "parent_id": _int(_number(top.get("parentId"))),
        "child_ids": child_ids or None,
        "raw": raw,
    }
    for column, keys, places in _ACTIVITY_NUMBERS:
        value = next((v for key in keys if (v := _number(numbers.get(key))) is not None), None)
        if column == "lap_count" and value is None:
            value = _number(meta.get("lapCount"))
        if column == "avg_stroke_distance_m" and value is not None and value >= _STROKE_CM_FROM:
            value = value / 100  # open-water swims arrive in centimetres, pool swims in metres
        row[column] = _int(value) if places is None else _dec(value, places)
    return row


def _zone_seconds(item: dict[str, Any], prefix: str) -> list[int | None] | None:
    seconds = [_int(_number(item.get(f"{prefix}{zone}"))) for zone in range(1, _ZONES + 1)]
    return seconds if any(value is not None for value in seconds) else None


def _pool_length(item: dict[str, Any]) -> Decimal | None:
    """Garmin's pool length, in metres: some replies give it in centimetres, some in yards."""
    length = _number(item.get("poolLength"))
    if length is None or length <= 0:
        return None
    unit = _dict(item.get("unitOfPoolLength")).get("unitKey")
    if length > 100:
        length /= 100  # centimetres
    if unit == "yard":
        length *= 0.9144
    return _dec(length, 1)


def _dict(value: Any) -> dict[str, Any]:
    return cast(dict[str, Any], value) if isinstance(value, dict) else {}


def _str(value: Any, limit: int | None = None) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    return value[:limit] if limit else value


def _bool(*values: Any) -> bool | None:
    return next((value for value in values if isinstance(value, bool)), None)


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
    "activities": _activities,
    "activity_detail": _activity_detail,
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
