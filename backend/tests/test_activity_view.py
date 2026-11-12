"""Shaping an activity for its page: the pure functions on hand-checkable activities."""

import itertools
import math

from hubnisio.health.insights import activity_view as v
from hubnisio.health.insights.series import Series


def run_stream(seconds: int = 1000, speed: float = 4.0, hr: float = 150.0) -> v.StreamData:
    time = list(range(seconds))
    return v.StreamData(
        time=time,
        distance=[speed * t for t in time],
        heart_rate=[hr + (t // 500) * 10 for t in time],
        speed=[speed] * seconds,
        altitude=[100.0 + t * 0.01 for t in time],
        cadence=[170.0] * seconds,
    )


def test_sport_group_follows_the_type_key() -> None:
    keys = {
        "running": "run",
        "trail_running": "run",
        "treadmill_running": "run",
        "cycling": "bike",
        "indoor_cycling": "bike",
        "mountain_biking": "bike",
        "lap_swimming": "swim",
        "open_water_swimming": "swim",
        "strength_training": "strength",
        "hiking": "other",
        "multi_sport": "other",
        None: "other",
    }
    assert {key: v.sport_group(key) for key in keys} == keys


def test_key_figure_is_pace_for_runs_and_swims_and_speed_for_rides() -> None:
    assert v.key_figure("run", 10000, 3000) == ("pace_km", 300)
    assert v.key_figure("swim", 1000, 1800) == ("pace_100m", 180)
    kind, speed = v.key_figure("bike", 36000, 3600)
    assert kind == "speed_kmh" and speed == 36
    assert v.key_figure("strength", 1000, 1000) == (None, None)
    assert v.key_figure("run", 50, 100) == (None, None)
    assert v.key_figure("run", None, 100) == (None, None)


def test_downsample_keeps_short_series_and_averages_buckets_of_long_ones() -> None:
    xs, out = v.downsample([0, 1, 2], {"a": [1, None, 3], "empty": [None, None, None]})
    assert xs == [0, 1, 2] and out == {"a": [1, None, 3]}

    axis: list[float | None] = [float(i) for i in range(1200)]
    xs, out = v.downsample(axis, {"a": [float(i) for i in range(1200)]}, points=600)
    assert len(xs) == len(out["a"]) == 600
    assert xs[0] == 0.5 and out["a"][0] == 0.5  # mean of 0 and 1
    assert xs == sorted(xs)


def test_downsample_drops_empty_slices_and_samples_without_an_axis() -> None:
    axis: list[float | None] = [0.0, None, 1.0, 1000.0]
    xs, _ = v.downsample(axis, {"a": [1.0, 2.0, 3.0, 4.0]}, points=2)
    assert xs == [0.5, 1000.0]


def test_a_run_is_drawn_over_distance_with_pace_from_the_mean_speed() -> None:
    shaped = v.shape_streams("running", run_stream())
    assert shaped is not None and shaped.axis == "distance"
    assert len(shaped.x) <= v.SERIES_POINTS
    assert set(shaped.series) == {"pace", "heart_rate", "altitude", "cadence"}
    pace = [p for p in shaped.series["pace"] if p is not None]
    assert pace and all(p == 250 for p in pace)  # 4 m/s is 4:10 per km


def test_standing_still_is_no_pace_and_a_ride_gets_kmh() -> None:
    data = v.StreamData(time=[0, 1, 2], distance=[0, 0, 0], speed=[0.0, 0.0, 0.0])
    assert v.shape_streams("running", data) is None
    ride = v.StreamData(time=[0, 1], distance=[0, 10], speed=[10.0, 10.0], power=[200, 220])
    shaped = v.shape_streams("cycling", ride)
    assert shaped is not None
    assert shaped.series["speed"] == [36, 36] and shaped.series["power"] == [200, 220]


def test_a_runs_stops_are_gaps_in_pace_and_cadence_not_spikes() -> None:
    # 2000 samples at 4 m/s with a 400-sample stop in the middle (walking off at 0.6 m/s, then
    # standing with cadence 0), bucketed into 10 slices of the distance.
    speed = [4.0] * 800 + [0.6] * 200 + [0.0] * 200 + [4.0] * 800
    cadence = [170.0] * 800 + [60.0] * 200 + [0.0] * 200 + [170.0] * 800
    distance = list(itertools.accumulate(speed))
    data = v.StreamData(
        time=list(range(len(speed))),
        distance=distance,
        speed=speed,
        cadence=cadence,
        heart_rate=[150.0] * len(speed),
    )
    shaped = v.shape_streams("running", data)
    assert shaped is not None
    pace = [p for p in shaped.series["pace"] if p is not None]
    assert pace and all(p == 250 for p in pace)  # never the stop's 16+ minutes per km
    steps = [c for c in shaped.series["cadence"] if c is not None]
    assert steps and all(c == 170 for c in steps)
    assert all(h is not None for h in shaped.series["heart_rate"])  # heart rate is untouched


def test_a_swim_and_a_strength_session_go_over_time() -> None:
    swim = v.StreamData(time=[0, 10], distance=[0, 15], speed=[1.5, 1.5], heart_rate=[120, 130])
    shaped = v.shape_streams("lap_swimming", swim)
    assert shaped is not None and shaped.axis == "time"
    assert shaped.series["pace100"] == [66.67, 66.67]
    gym = v.StreamData(time=[0, 60], heart_rate=[90, 110], altitude=[1, 2], speed=[1, 1])
    shaped = v.shape_streams("strength_training", gym)
    assert shaped is not None and list(shaped.series) == ["heart_rate"]
    assert v.shape_streams("strength_training", v.StreamData(time=[0, 1])) is None


def test_km_splits_cut_at_each_kilometre_with_the_last_one_partial() -> None:
    splits = v.km_splits(run_stream(seconds=626))  # 2500 m at 4 m/s
    assert [s.distance_m for s in splits] == [1000, 1000, 500]
    assert [s.duration_s for s in splits] == [250, 250, 125]
    assert splits[0].avg_speed == 4
    # heart rate rises by 10 at t = 500 s, the end of split 2
    assert splits[0].avg_hr == 150 and splits[2].avg_hr == 160
    assert splits[0].elevation_change_m == 2.5


def test_a_stub_under_100_m_folds_into_the_last_kilometre() -> None:
    splits = v.km_splits(run_stream(seconds=511))  # 2040 m
    assert [s.distance_m for s in splits] == [1000, 1040]
    assert v.km_splits(run_stream(seconds=20)) == []
    assert v.km_splits(v.StreamData(time=[0, 1])) == []


def test_laps_become_splits_and_a_lap_without_time_is_left_out() -> None:
    laps = [
        v.LapIn(1, 1000, 300, 140, 3.3, None, 10, 4),
        v.LapIn(2, 500, None, None, None, None, None, None),
        v.LapIn(3, 800, 200, None, 4.0, 210, None, None),
    ]
    out = v.lap_splits(laps)
    assert [s.index for s in out] == [1, 3]
    assert out[0].elevation_change_m == 6 and out[1].elevation_change_m is None
    assert out[1].avg_power == 210


def swum(i: int, stroke: str = "freestyle", swolf: int = 40) -> v.LengthIn:
    return v.LengthIn(i, True, stroke, 18, 30.0, swolf)


def rest(i: int) -> v.LengthIn:
    return v.LengthIn(i, False, None, None, 20.0, None)


def test_swim_sets_are_runs_of_swum_lengths_with_the_rest_after_them() -> None:
    lengths = [swum(0), swum(1, swolf=42), rest(2), rest(3), swum(4, "backstroke", 50)]
    sets, lengths_out = v.swim_sets(lengths, 25.0)
    assert [(s.lengths, s.distance_m, s.duration_s, s.rest_s) for s in sets] == [
        (2, 50, 60, 40),
        (1, 25, 30, 0),
    ]
    assert sets[0].swolf == 41 and sets[0].strokes == 36 and sets[0].stroke == "freestyle"
    assert sets[1].stroke == "backstroke"
    assert [x.set_index for x in lengths_out] == [1, 1, 2]
    assert v.swim_sets([], 25.0) == ([], [])
    assert v.swim_sets([rest(0)], 25.0) == ([], [])


def test_zones_prefer_ours_then_garmins() -> None:
    ours = v.heart_rate_zones([60, 600, 1200, 300, 0, 0], [1, 1, 1, 1, 1], 171)
    assert ours == v.ActivityZones("ours", 60, [600, 1200, 300, 0, 0], 171)
    garmin = v.heart_rate_zones(None, [0, None, 30, 10, 0], None)
    assert garmin == v.ActivityZones("garmin", 0, [0, 0, 30, 10, 0], None)
    assert v.heart_rate_zones([0] * 6, [0, 0, 0, 0, 0], None) is None


def test_half_figures_compare_the_two_halves_of_a_run() -> None:
    n = 1500  # 25 minutes
    series = Series(
        time=list(range(n)),
        distance=[4.0 * t for t in range(n)],
        heart_rate=[150.0] * 750 + [160.0] * 750,
        speed=[4.0] * n,
        altitude=[100.0] * n,
    )
    halves = v.half_figures("running", series)
    assert halves is not None
    first, second = halves
    assert first.speed == second.speed == 4
    assert (first.heart_rate, second.heart_rate) == (150, 160)
    assert first.efficiency is not None and second.efficiency is not None
    assert first.efficiency > second.efficiency
    # too short, or not a run or a ride: nothing
    short = Series(
        time=list(range(600)),
        distance=[4.0 * t for t in range(600)],
        heart_rate=[150.0] * 600,
        speed=[4.0] * 600,
    )
    assert v.half_figures("running", short) is None
    assert v.half_figures("lap_swimming", series) is None


def circle(n: int) -> tuple[list[float | None], list[float | None]]:
    return (
        [38.7 + 0.01 * math.sin(2 * math.pi * i / n) for i in range(n)],
        [-9.1 + 0.01 * math.cos(2 * math.pi * i / n) for i in range(n)],
    )


def test_a_long_route_is_simplified_to_the_limit_and_keeps_its_ends() -> None:
    lat, lon = circle(3000)
    route = v.simplified_route(lat, lon)
    assert route is not None and 20 < len(route) <= v.ROUTE_POINTS
    assert route[0] == (round(lat[0] or 0, 5), round(lon[0] or 0, 5))
    assert route[-1] == (round(lat[-1] or 0, 5), round(lon[-1] or 0, 5))
    assert len(v.simplified_route(*circle(100)) or []) == 100


def test_no_position_or_no_movement_is_no_route() -> None:
    assert v.simplified_route(None, None) is None
    assert v.simplified_route([None, None], [None, None]) is None
    assert v.simplified_route([38.7] * 50, [-9.1] * 50) is None
