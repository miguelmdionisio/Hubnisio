"""Garmin replies to rows, with invented values in the shapes the probe recorded."""

from datetime import UTC, date, datetime
from decimal import Decimal

import garmin_data as g

from hubnisio.health.models import SampleKind
from hubnisio.health.providers.garmin.normalize import normalize

DAY = date(2026, 3, 4)


def test_daily_summaries() -> None:
    records = normalize("daily_summaries", {"data": [g.daily_summary(DAY)]}, DAY)
    (row,) = records.daily
    n = DAY.toordinal() % 7
    assert row["day"] == DAY
    assert row["steps"] == 8000 + n
    assert row["distance_m"] == Decimal("6100.5") + n
    assert row["resting_hr"] == 48 + n
    assert row["vigorous_minutes"] == 15 + n
    assert row["rest_stress_s"] == 36_000  # milliseconds to seconds
    assert row["body_battery_drained"] == 55 + n
    assert row["spo2_min"] == 89
    assert row["respiration_max"] == 20
    assert row["includes_wellness"] is True


def test_a_negative_stress_level_means_none() -> None:
    summary = g.daily_summary(DAY)
    summary["stress"]["avgLevel"] = -1
    (row,) = normalize("daily_summaries", {"data": [summary]}, DAY).daily
    assert row["stress_avg"] is None


def test_stress_steps_and_body_battery_only_fill() -> None:
    stress = normalize("stress", [g.stress_day(DAY)], DAY)
    steps = normalize("steps", [g.steps_day(DAY)], DAY)
    battery = normalize("body_battery", [g.body_battery(DAY)], DAY)

    assert stress.daily == [] and stress.daily_fill[0]["rest_stress_s"] == 30_000
    assert steps.daily_fill == [
        {"day": DAY, "steps": 9999, "step_goal": 9000, "distance_m": Decimal("7000.0")}
    ]
    assert battery.daily_fill[0]["body_battery_charged"] == 61
    assert [(s["kind"], s["value"]) for s in battery.samples] == [
        (SampleKind.BODY_BATTERY, Decimal(40 + h)) for h in range(3)
    ]


def test_sleep() -> None:
    (row,) = normalize("sleep", [g.sleep_summary(DAY)], DAY).sleeps
    start, end = g.night(DAY)
    assert row["day"] == DAY
    assert (row["started_at"], row["ended_at"]) == (start, end)
    assert row["utc_offset_minutes"] == 60
    assert row["deep_s"] == 5_400
    assert row["score"] == 80 + DAY.toordinal() % 7
    assert row["score_qualifier"] == "GOOD"
    assert row["need_minutes"] == 480
    assert row["avg_spo2"] == Decimal("94.5")
    assert row["avg_sleep_stress"] == Decimal("12.5")


def test_a_day_without_a_night_gives_no_sleep() -> None:
    empty = g.sleep_summary(DAY) | {"sleepTimeSeconds": 0}
    no_times = g.sleep_summary(DAY) | {"sleepStartTimestampGMT": None}
    assert normalize("sleep", [empty, no_times], DAY).sleeps == []


def test_hrv_range_and_night() -> None:
    (summary,) = normalize("hrv", {"hrvSummaries": [g.hrv_summary(DAY)]}, DAY).hrv
    assert summary["weekly_avg"] == 62
    assert summary["baseline_balanced_upper"] == 70

    night = normalize("hrv_readings", g.hrv_day(DAY), DAY)
    assert night.hrv[0]["weekly_avg"] is None  # left to the range's value when stored
    assert [s["value"] for s in night.samples] == [Decimal(55 + i) for i in range(4)]
    assert night.samples[0]["at"] == g.night(DAY)[0]
    assert {s["day"] for s in night.samples} == {DAY}


def test_heart_rate_skips_gaps() -> None:
    samples = normalize("heart_rate", g.heart_rate_day(DAY), DAY).samples
    assert [s["value"] for s in samples] == [Decimal(v) for v in (50, 51, 53, 54)]
    assert samples[0]["at"] == datetime(2026, 3, 4, tzinfo=UTC)


def test_spo2_hourly_averages() -> None:
    samples = normalize("spo2", g.spo2_day(DAY), DAY).samples
    assert [(s["kind"], s["value"]) for s in samples] == [
        (SampleKind.SPO2, Decimal(93 + h)) for h in range(3)
    ]


def test_zones_fitness_age_and_profile() -> None:
    zones = normalize("hr_zones", g.zones(), DAY).zones
    assert zones is not None and [z["sport"] for z in zones] == ["DEFAULT", "RUNNING"]
    assert zones[1]["lactate_threshold_hr"] == 170

    (fitness,) = normalize("fitness_age", g.fitness_age(), DAY).fitness
    assert fitness == {
        "day": DAY,
        "fitness_age": Decimal("33.5"),
        "previous_fitness_age": Decimal("34.0"),
        "chronological_age": 40,
        "resting_hr": 48,
        "bmi": Decimal("22.4"),
        "vigorous_days_avg": Decimal("3.5"),
        "vigorous_minutes_avg": Decimal("150.0"),
    }
    assert normalize("profile", g.profile(), None).time_zone == g.TIME_ZONE


def test_weight_from_the_range_and_the_all_replies() -> None:
    reply = g.weight_range(DAY, DAY, [DAY])
    (row,) = normalize("weight", reply, DAY).weights
    assert row["weight_kg"] == Decimal("70.500")
    assert row["muscle_mass_kg"] == Decimal("32.000")
    assert row["measured_at"] == datetime(2026, 3, 4, 7, tzinfo=UTC)
    assert row["source"] == "INDEX_SCALE"

    entries = reply["dailyWeightSummaries"][0]["allWeightMetrics"]
    assert normalize("weight", entries, DAY).weights == [row]
    assert normalize("weight", g.weight_range(DAY, DAY, []), DAY).weights == []
    assert normalize("weight", [], DAY).weights == []


def test_weight_goal() -> None:
    goal = {"userGoals": [{"goalValue": 68_000, "startDate": "2026-01-01"}]}
    assert normalize("weight_goal", goal, DAY).weight_goal == {
        "target_kg": Decimal("68.000"),
        "starts_on": date(2026, 1, 1),
    }
    cleared = normalize("weight_goal", {"userGoals": [], "userGoalRanges": None}, DAY)
    assert cleared.weight_goal is None and cleared.clear_weight_goal


def test_unexpected_replies_give_nothing() -> None:
    for kind in ("daily_summaries", "sleep", "hrv", "heart_rate", "weight", "hr_zones"):
        for raw in (None, "text", 42, {"unexpected": True}):
            records = normalize(kind, raw, DAY)
            assert not (records.daily or records.sleeps or records.hrv or records.samples)
            assert not (records.weights or records.zones)
    assert normalize("unknown_kind", {"a": 1}, DAY).daily == []


# Activities

RUN = g.FakeActivity(9001, "running", datetime(2026, 3, 4, 7, 30, tzinfo=UTC), 1800, 6000.0)


def test_an_activity_summary() -> None:
    (row,) = normalize("activities", [g.activity_summary(RUN)], None).activities
    assert row["activity_id"] == 9001 and row["sport"] == "running"
    assert row["started_at"] == datetime(2026, 3, 4, 7, 30, tzinfo=UTC)
    assert row["start_local"] == datetime(2026, 3, 4, 7, 30)
    assert row["duration_s"] == Decimal("1800.0") and row["moving_s"] == Decimal("1795.0")
    assert row["distance_m"] == Decimal("6000.0")
    assert row["avg_hr"] == 150 and row["norm_power"] == 255
    assert row["avg_cadence"] == Decimal("171.0")
    assert row["garmin_load"] == Decimal("61.5") and row["te_label"] == "TEMPO"
    assert row["hr_zone_s"] == [10, 20, 30, 40, 0] and row["power_zone_s"] is None
    assert row["fastest_splits"] == {"1000": 300.0, "400": 120.0}
    assert row["is_parent"] is False and row["child_ids"] is None
    assert row["pool_length_m"] is None
    assert row["raw"]["activityId"] == 9001


def test_a_pool_length_in_centimetres() -> None:
    swim = g.FakeActivity(9002, "lap_swimming", RUN.start, 1800, 1500.0)
    (row,) = normalize("activities", [g.activity_summary(swim)], None).activities
    assert row["pool_length_m"] == Decimal("25.0")


def test_an_activity_detail_fills_and_names_the_legs() -> None:
    parent = g.FakeActivity(9100, "multi_sport", RUN.start, 7200, is_parent=True)
    parent.child_ids = [9101, 9102]
    (row,) = normalize("activity_detail", g.activity_detail(parent), None).activity_fill
    assert row["activity_id"] == 9100 and row["is_parent"] is True
    assert row["child_ids"] == [9101, 9102]
    assert row["time_zone"] == g.TIME_ZONE
    assert row["avg_hr"] == 149 and row["lap_count"] == 1
    # The same columns as a search row, so both upsert alike.
    (search,) = normalize("activities", [g.activity_summary(RUN)], None).activities
    assert row.keys() == search.keys()


def test_an_activity_without_an_id_or_type_is_skipped() -> None:
    item = g.activity_summary(RUN)
    del item["activityType"]
    assert normalize("activities", [item, "nonsense"], None).activities == []
    assert normalize("activity_detail", {"activityId": 1}, None).activity_fill == []
