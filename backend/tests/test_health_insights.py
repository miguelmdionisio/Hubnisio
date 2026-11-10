"""The per-activity results (health/insights), each on invented samples whose answer can be
worked out by hand."""

import math

import pytest

from hubnisio.health.insights import climbs, curves, durability, load, running
from hubnisio.health.insights.activity import Family, derive, family
from hubnisio.health.insights.series import Series, fourth_power_mean, moving, rolling

REFERENCE = load.HeartRateReference(threshold=170, max=190, rest=50, source="zones")


# The one-second grid


def test_short_gaps_are_filled_and_pauses_cut_out() -> None:
    # A 3 s gap (smart recording) is filled; a 20 s gap without moving is a pause.
    series = Series(
        time=[0, 1, 4, 24, 25],
        distance=[0, 3, 12, 12, 15],
        heart_rate=[100, 110, 140, None, 120],
    )
    grid = moving(series)
    assert grid.seconds == 1 + 3 + 1 + 1 + 1
    assert grid.distance == [0, 3, 6, 9, 12, 12, 15]
    assert grid.heart_rate == [100, 110, 120, 130, 140, 140, 120]
    assert grid.power == []  # no power at all


def test_a_long_gap_while_moving_is_filled() -> None:
    grid = moving(Series(time=[0, 10, 11], distance=[0, 30, 33]))
    assert grid.seconds == 12
    assert grid.distance[5] == pytest.approx(15)


def test_rolling_and_fourth_power_mean() -> None:
    assert rolling([1, 2, 3, None, 5], 2) == [None, 1.5, 2.5, None, None]
    assert fourth_power_mean([200.0] * 60) == pytest.approx(200)
    # Half at 100 W, half at 300 W: NP is above the 200 W average.
    surging = [100.0] * 600 + [300.0] * 600
    assert fourth_power_mean(surging) == pytest.approx((0.5 * 100**4 + 0.5 * 300**4) ** 0.25, 0.01)


# Curves and best efforts


def test_mean_max_skips_windows_with_a_gap() -> None:
    assert curves.mean_max([1, 2, 3, 4, None, 10], (1, 2, 3, 10)) == [10, 3.5, 3.0, None]


def test_best_efforts_at_a_steady_speed() -> None:
    distance = [4.0 * t for t in range(301)]  # 4 m/s for 300 s: 1200 m
    assert curves.best_efforts(distance) == {400: 100.0, 1000: 250.0}


def test_best_efforts_find_the_fast_part() -> None:
    # 100 s at 4 m/s, then 100 s at 5 m/s: the best 400 m is all at 5 m/s.
    distance = [4.0 * t for t in range(101)] + [400 + 5.0 * t for t in range(1, 101)]
    assert curves.best_efforts(distance, (400,)) == {400: 80.0}


def test_swim_best_efforts_stop_at_a_rest() -> None:
    lengths = [curves.Length(30, True), curves.Length(28, True), curves.Length(60, False)] + [
        curves.Length(25, True)
    ] * 8
    # 50 m before the rest; then 8 x 25 m at 25 s each.
    assert curves.swim_best_efforts(lengths, 25.0) == {100: 100.0, 200: 200.0}


# Load and zones


def test_an_hour_at_threshold_scores_100() -> None:
    assert load.hr_load([170.0] * 3600, REFERENCE) == pytest.approx(100)
    assert load.hr_load([170.0] * 1800, REFERENCE) == pytest.approx(50)
    easy = load.hr_load([120.0] * 3600, REFERENCE)
    assert easy is not None and easy < 40
    assert load.hr_load([None] * 60, REFERENCE) is None


def test_trimp_by_hand() -> None:
    # Reserve (152 - 50) / (190 - 50) = 0.7286 for 10 minutes.
    reserve = 102 / 140
    expected = 10 * reserve * 0.64 * math.exp(1.92 * reserve)
    assert load.trimp([152.0] * 600, REFERENCE) == pytest.approx(expected)


def test_the_reference_falls_back_from_zones_to_the_file_to_an_estimate() -> None:
    zones = load.heart_rate_reference(zones_threshold=170, zones_max=190, file_threshold=160)
    assert zones == load.HeartRateReference(170, 190, 60, "zones")
    from_file = load.heart_rate_reference(file_threshold=165, file_max=185, file_rest=45)
    assert from_file == load.HeartRateReference(165, 185, 45, "file")
    estimate = load.heart_rate_reference(zones_max=200, rest=48)
    assert estimate is not None and estimate.source == "estimate"
    assert estimate.threshold == pytest.approx(178) and estimate.rest == 48
    only_threshold = load.heart_rate_reference(zones_threshold=178)
    assert only_threshold is not None and only_threshold.max == pytest.approx(200)
    assert load.heart_rate_reference() is None


def test_time_in_zones() -> None:
    floors = [100.0, 120.0, 140.0, 160.0, 180.0]
    assert load.time_in_zones([90, 100, 150, None, 185, 179], floors) == [1, 1, 0, 1, 1, 1]
    assert load.zone_floors([100, 120, 140, 160, 180], None) == floors
    assert load.zone_floors([100, None, 140, 160, 180], REFERENCE) == pytest.approx(
        [119, 144.5, 153, 161.5, 170]
    )
    assert load.zone_floors(None, None) is None


# Graded pace and VO2max


def test_minetti_cost() -> None:
    assert running.running_cost(0) == pytest.approx(3.6)
    # 10 % up: 0.001554 - 0.00304 - 0.0433 + 0.463 + 1.95 + 3.6
    assert running.running_cost(0.1) == pytest.approx(5.968214)
    assert running.running_cost(0.9) == running.running_cost(0.45)


def test_graded_speed_up_a_steady_hill() -> None:
    distance = [3.0 * t for t in range(120)]
    altitude = [0.3 * t for t in range(120)]  # 10 %
    grade = running.grades(distance, altitude)
    assert grade[60] == pytest.approx(0.1)
    graded = running.graded_speeds([3.0] * 120, grade)
    assert graded[60] == pytest.approx(3.0 * 5.968214 / 3.6)
    # Flat, or without altitude: graded speed is speed.
    assert running.graded_speeds([3.0], running.grades([0.0], [])) == [3.0]
    assert running.normalized_graded_speed([3.0] * 120) == pytest.approx(3.0)


def test_estimated_vo2max_by_hand() -> None:
    # 200 m/min: VO2 = -4.60 + 36.4516 + 4.16 = 36.0116; at 80 % of max heart rate,
    # (0.8 - 0.2812) / 0.7303 = 0.71039 of VO2max.
    speed = [200 / 60] * 600
    vo2max = running.estimated_vo2max(speed, [152.0] * 600, 190)
    assert vo2max == pytest.approx(36.0116 / ((0.8 - 0.2812) / 0.7303))
    assert running.estimated_vo2max(speed[:599], [152.0] * 599, 190) is None  # under 10 min
    assert running.estimated_vo2max(speed, [100.0] * 600, 190) is None  # too easy to tell


# Durability


def test_efficiency_and_decoupling() -> None:
    output = [200.0] * 1200
    hr = [150.0] * 600 + [160.0] * 600
    result = durability.durability(output, hr)
    assert result is not None
    assert result.efficiency_factor == pytest.approx(200 / 155)
    assert result.decoupling_pct == pytest.approx((200 / 150 - 200 / 160) / (200 / 150) * 100)
    assert result.decoupling_pct == pytest.approx(6.25)
    assert result.steady
    assert durability.durability(output[:1199], hr[:1199]) is None  # under 20 minutes


def test_intervals_are_not_steady() -> None:
    output = ([100.0] * 60 + [300.0] * 60) * 10
    result = durability.durability(output, [150.0] * 1200)
    assert result is not None and not result.steady


# Climbs


def test_a_sustained_climb_and_its_vam() -> None:
    # 600 s at 5 m/s gaining 0.2 m/s (4 %), then down again; then a 30 m bump.
    distance = [5.0 * t for t in range(1500)]
    altitude = (
        [100 + 0.2 * t for t in range(600)]
        + [220 - 0.2 * t for t in range(600)]
        + [100 + 0.1 * t for t in range(300)]
    )
    found = climbs.climbs(distance, altitude)
    assert len(found) == 1
    climb = found[0]
    assert climb.start_s == 0 and climb.duration_s == 600
    assert climb.gain_m == pytest.approx(120)
    assert climb.grade == pytest.approx(0.04)
    assert climb.vam == pytest.approx(720)
    assert climbs.best_vam(found) == pytest.approx(720)
    assert climbs.best_vam([]) is None


# All together


def test_family() -> None:
    assert family("running") is Family.RUN
    assert family("trail_running") is Family.RUN
    assert family("indoor_cycling") is Family.RIDE
    assert family("lap_swimming") is Family.SWIM
    assert family("open_water_swimming") is Family.SWIM
    assert family("strength_training") is Family.OTHER
    assert family(None) is Family.OTHER


def test_derive_a_flat_run_at_threshold() -> None:
    seconds = 1200
    series = Series(
        time=list(range(seconds)),
        distance=[t * 200 / 60 for t in range(seconds)],
        heart_rate=[170.0] * seconds,
        speed=[200 / 60] * seconds,
        altitude=[50.0] * seconds,
        power=[250.0] * seconds,
    )
    derived = derive(series, type_key="running", reference=REFERENCE)

    assert derived.moving_s == seconds
    assert derived.hr_load == pytest.approx(100 / 3)
    assert derived.hr_zone_s == [0, 0, 0, 0, 0, seconds]  # at threshold: zone 5's floor
    assert derived.best_efforts == {400: 120.0, 1000: 300.0, 1609: 482.7}
    assert derived.gap_speed == pytest.approx(200 / 60)
    assert derived.ngp_speed == pytest.approx(200 / 60)
    assert derived.efficiency_factor == pytest.approx(200 / 170)
    assert derived.decoupling_pct == pytest.approx(0)
    assert derived.steady is True
    assert derived.vo2max == pytest.approx(36.0116 / ((170 / 190 - 0.2812) / 0.7303))
    assert derived.power_curve is not None and derived.power_curve[0] == 250
    assert derived.power_curve[-1] is None  # no 2-hour window
    assert derived.climbs == [] and derived.best_vam is None


def test_derive_a_ride_without_power_or_heart_rate() -> None:
    seconds = 700
    series = Series(
        time=list(range(seconds)),
        distance=[5.0 * t for t in range(seconds)],
        speed=[5.0] * seconds,
        altitude=[0.2 * t for t in range(seconds)],
    )
    derived = derive(series, type_key="cycling", reference=None)
    assert derived.hr_load is None and derived.hr_zone_s is None and derived.power_curve is None
    assert derived.best_efforts == {}
    assert derived.efficiency_factor is None
    assert derived.best_vam == pytest.approx(720)


def test_derive_a_pool_swim_from_its_lengths() -> None:
    lengths = [curves.Length(25, True)] * 4
    derived = derive(
        Series(time=[]),
        type_key="lap_swimming",
        reference=REFERENCE,
        lengths=lengths,
        pool_length_m=25,
    )
    assert derived.best_efforts == {100: 100.0}
    assert derived.moving_s == 0 and derived.hr_load is None
