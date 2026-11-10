"""Performance (ADR-0009, H7): the pure functions on hand-checkable inputs, and the endpoint
against a real Postgres with invented values."""

import math
from datetime import UTC, date, datetime, timedelta

import pytest
from households import Home, api

from hubnisio.core.db import get_sessionmaker
from hubnisio.health.insights import performance as p
from hubnisio.health.insights.curves import CURVE_DURATIONS
from hubnisio.health.models import Activity, ActivityDerived, HeartRateZones, Weight
from hubnisio.health.sync import today_in

pytestmark = pytest.mark.anyio

TODAY = date(2026, 11, 10)


def curve(fn) -> list[float | None]:
    return [fn(t) for t in CURVE_DURATIONS]


def run(activity_id: int, day: date, **values) -> p.ActivityFacts:
    return p.ActivityFacts(activity_id=activity_id, day=day, sport="running", **values)


# Season curves


def test_season_curve_keeps_the_best_per_duration_with_its_day() -> None:
    a = run(1, date(2026, 3, 1), power_curve=curve(lambda t: 300.0 if t <= 60 else 200.0))
    b = run(2, date(2026, 5, 1), power_curve=curve(lambda t: 250.0))
    best = p.season_curve([a, b], "power")
    assert best[0] == p.BestPoint(1, 300.0, date(2026, 3, 1), 1)
    assert best[CURVE_DURATIONS.index(600)] == p.BestPoint(600, 250.0, date(2026, 5, 1), 2)


def test_a_duration_nobody_reached_stays_empty() -> None:
    a = run(1, TODAY, speed_curve=[3.0] * 5 + [None] * (len(CURVE_DURATIONS) - 5))
    best = p.season_curve([a], "speed")
    assert best[4].value == 3.0
    assert best[-1].value is None


# Critical power and speed


def exact(cp: float, w_prime: float) -> list[p.BestPoint]:
    return [p.BestPoint(t, cp + w_prime / t) for t in CURVE_DURATIONS]


def test_critical_power_recovers_cp_and_w_prime_from_an_exact_curve() -> None:
    model = p.critical_power(exact(250, 20000), weight_kg=62.5)
    assert model is not None
    assert model.cp == pytest.approx(250)
    assert model.w_prime == pytest.approx(20000)
    assert model.cp_per_kg == pytest.approx(4.0)
    assert model.points == 3  # 5, 10 and 20 minutes
    assert model.line[0].duration_s == 120
    assert model.line[0].value == pytest.approx(250 + 20000 / 120)


def test_critical_power_by_hand_on_scattered_points() -> None:
    # Work 90 kJ at 300 s, 160 kJ at 600 s, 300 kJ at 1200 s: mean t 700, mean W 183333.3;
    # Sxx = 400² + 100² + 500² = 420000; Sxy = 400 · 93333.3 + 100 · 23333.3 + 500 · 116666.7
    #     = 98,000,000; CP = 233.33 W, W' = 183333.3 - 233.33 · 700 = 20000 J.
    points = [p.BestPoint(300, 300.0), p.BestPoint(600, 160000 / 600)]
    points.append(p.BestPoint(1200, 250.0))
    model = p.critical_power(points)
    assert model is not None
    assert model.cp == pytest.approx(98_000_000 / 420_000)
    assert model.w_prime == pytest.approx(20000)
    assert model.cp_per_kg is None


def test_no_model_without_three_durations_reaching_twelve_minutes() -> None:
    two = [p.BestPoint(300, 300.0), p.BestPoint(600, 270.0), p.BestPoint(1200, None)]
    assert p.critical_power(two) is None
    short = [p.BestPoint(t, 300.0 - t / 10) for t in (180, 300, 600)]
    assert p.critical_power(short) is None
    rising = [p.BestPoint(t, 250.0 - 5000 / t) for t in (300, 600, 1200)]  # W' < 0
    assert p.critical_power(rising) is None


def test_critical_speed_and_threshold_pace() -> None:
    model = p.critical_speed(exact(4.0, 200))
    assert model is not None
    assert model.speed == pytest.approx(4.0)
    assert model.d_prime == pytest.approx(200)
    assert model.pace_per_km_s == pytest.approx(250)  # 4:10 /km


def test_critical_swim_speed_from_400_and_200() -> None:
    css = p.swim_threshold(t200=150, t400=330)
    assert css is not None
    assert css.speed == pytest.approx(200 / 180)
    assert css.pace_per_100_s == pytest.approx(90)  # 1:30 /100 m
    assert p.swim_threshold(None, 330) is None
    assert p.swim_threshold(150, None) is None
    assert p.swim_threshold(150, 140) is None


# VO2max


def test_vo2max_line_is_the_mean_of_the_best_half_in_42_days() -> None:
    runs = [
        run(1, TODAY - timedelta(days=50), vo2max=60.0),  # outside the window
        run(2, TODAY - timedelta(days=10), vo2max=50.0),
        run(3, TODAY - timedelta(days=5), vo2max=40.0),
        run(4, TODAY - timedelta(days=1), vo2max=48.0),
    ]
    # Window: 50, 40, 48 → best half (2 of 3): 50 and 48.
    assert p.smoothed_vo2max(runs, TODAY) == pytest.approx(49)
    trend = p.vo2max_trend(runs, None, TODAY)
    assert trend.latest == pytest.approx(49)
    assert [pt.value for pt in trend.points] == [60, 50, 40, 48]
    assert trend.points[1].line == pytest.approx(60)  # 60 and 50: the best one of two
    assert trend.change_90d is None  # nothing 90 days ago


def test_vo2max_change_over_90_days() -> None:
    runs = [run(1, TODAY - timedelta(days=95), vo2max=47.0), run(2, TODAY, vo2max=49.5)]
    assert p.vo2max_trend(runs, None, TODAY).change_90d == pytest.approx(2.5)


# RacePredictions


def test_vdot_times_match_daniels_tables() -> None:
    # Daniels' table for VDOT 50: 19:57, 41:21, 1:31:35, 3:10:49.
    assert p.vdot_time(50, 5000) == pytest.approx(19 * 60 + 57, abs=3)
    assert p.vdot_time(50, 10000) == pytest.approx(41 * 60 + 21, abs=3)
    assert p.vdot_time(50, 21097) == pytest.approx(91 * 60 + 35, abs=6)
    assert p.vdot_time(50, 42195) == pytest.approx(190 * 60 + 49, abs=12)
    assert p.vdot_of(5000, p.vdot_time(50, 5000)) == pytest.approx(50)


def test_riegel() -> None:
    assert p.riegel(1200, 5000, 10000) == pytest.approx(1200 * 2**1.06)


def test_shape_needed_rises_from_5_km_to_the_marathon() -> None:
    assert p.shape_needed(5000) == 0
    assert p.shape_needed(42195) == 1
    assert p.shape_needed(21097) == pytest.approx((21.097 - 5) / 37.195)  # 43 %


def test_marathon_shape_by_hand() -> None:
    vo2 = 50.0
    weekly_target = 50**1.135  # 84.79 km
    long_target = 12 * math.log(12.5)  # 30.31 km
    runs = [run(i, TODAY - timedelta(days=i), distance_m=10000.0) for i in range(1, 100)]
    runs.append(run(500, TODAY, distance_m=30000.0))
    runs.append(run(501, TODAY - timedelta(days=200), distance_m=30000.0))  # too old
    shape = p.marathon_shape(runs, TODAY, vo2)
    assert shape is not None
    weekly = (99 * 10 + 30) / 26
    long_share = ((30 - 13) / (long_target - 13)) ** 2 / 13
    assert shape.weekly_km == pytest.approx(weekly)
    assert shape.weekly_share == pytest.approx(weekly / weekly_target)
    assert shape.long_runs == 1
    assert shape.long_share == pytest.approx(long_share)
    assert shape.score == pytest.approx(2 / 3 * weekly / weekly_target + 1 / 3 * long_share)


def test_a_short_shape_slows_the_marathon_but_not_the_5_km() -> None:
    assert p.shaped_vdot(50, 0.71, 1.0) == pytest.approx(50 * (1 - 0.25 * 0.29))
    assert p.shaped_vdot(50, 0.71, 0.43) == 50
    assert p.shaped_vdot(50, 0.0, 0.0) == 50
    runs = [run(1, TODAY, vo2max=50.0, distance_m=8000.0)]
    result = p.predictions(runs, TODAY, 50.0)
    by_distance = {item.distance_m: item for item in result.items}
    assert not by_distance[5000].slowed
    assert by_distance[5000].vdot_s == pytest.approx(p.vdot_time(50, 5000))
    assert by_distance[42195].slowed
    assert by_distance[42195].vdot_s is not None
    assert by_distance[42195].vdot_s > p.vdot_time(50, 42195)


def test_riegel_projects_from_the_strongest_recent_effort() -> None:
    runs = [
        run(1, TODAY - timedelta(days=10), best_efforts={5000: 1300.0, 1000: 200.0}),
        run(2, TODAY - timedelta(days=20), best_efforts={10000: 2500.0}),  # VDOT ~49 vs ~46
        run(3, TODAY - timedelta(days=120), best_efforts={5000: 1000.0}),  # too old
    ]
    result = p.predictions(runs, TODAY, None)
    assert result.riegel_from == p.RiegelSource(10000, 2500.0, TODAY - timedelta(days=20), 2)
    half = next(i for i in result.items if i.distance_m == 21097)
    assert half.riegel_s == pytest.approx(2500 * 2.1097**1.06)
    assert half.vdot_s is None
    assert result.shape is None


# Easy-run efficiency


def easy(activity_id: int, day: date, ef: float, hr: float = 140, steady: bool = True):
    return run(
        activity_id,
        day,
        efficiency_factor=ef,
        avg_hr=hr,
        moving_s=1800,
        steady=steady,
        hr_threshold=170.0,
    )


def test_easy_runs_need_steady_twenty_minutes_under_zone_3() -> None:
    runs = [
        easy(1, TODAY, 1.5),
        easy(2, TODAY, 1.5, hr=160),  # zone 3 or above (floor 153: 0.9 of 170)
        easy(3, TODAY, 1.5, steady=False),
        run(4, TODAY, efficiency_factor=1.5, avg_hr=140, moving_s=900, steady=True),
    ]
    assert [r.activity_id for r in p.easy_runs(runs, None)] == [1]
    assert [r.activity_id for r in p.easy_runs(runs, 165)] == [1, 2]


def test_efficiency_trend_and_change_over_six_months() -> None:
    runs = [easy(i, TODAY - timedelta(days=150 - 50 * i), 1.0 + 0.1 * i) for i in range(4)]
    result = p.efficiency(runs, None, None, TODAY)
    assert len(result.points) == 4
    assert result.trend is not None
    assert result.trend.start == pytest.approx(1.0)
    assert result.trend.end == pytest.approx(1.3)
    assert result.change_6m_pct == pytest.approx(30)


# BikePerformance and records


def ride(activity_id: int, day: date, **values) -> p.ActivityFacts:
    return p.ActivityFacts(activity_id=activity_id, day=day, sport="road_biking", **values)


def test_the_bike_has_a_heart_rate_curve_and_climbs_but_no_power_curve_without_power() -> None:
    climbs = [p.ClimbFacts(2000, 120, 600, 0.06, 720), p.ClimbFacts(1000, 60, 400, 0.06, 540)]
    rides = [ride(1, TODAY, hr_curve=curve(lambda t: 160.0), climbs=climbs)]
    result = p.bike(rides, [])
    assert result.power_curve is None
    assert result.hr_curve.current[0].value == 160
    assert [c.vam for c in result.climbs] == [720, 540]
    with_power = p.bike([ride(2, TODAY, power_curve=curve(lambda t: 200.0))], [])
    assert with_power.power_curve is not None


def test_records_show_the_all_time_best_when_another_activity_holds_it() -> None:
    old = run(1, date(2025, 5, 1), best_efforts={5000: 1200.0, 1000: 220.0})
    new = run(2, date(2026, 5, 1), best_efforts={5000: 1250.0, 1000: 210.0})
    swim = p.ActivityFacts(3, date(2026, 6, 1), "open_water_swimming", best_efforts={400: 400.0})
    long = ride(4, date(2026, 7, 1), distance_m=90000.0, elevation_gain_m=1200.0)
    rows = [old, new, swim, long]
    result = p.records([new, swim, long], rows, compare=True)
    by_key = {r.key: r for r in result.run}
    assert by_key["5000"].value == 1250
    assert by_key["5000"].all_time == 1200
    assert by_key["5000"].all_time_day == date(2025, 5, 1)
    assert by_key["1000"].value == 210
    assert by_key["1000"].all_time is None  # this season's is the all-time best
    assert by_key["10000"].value is None
    swim_400 = next(r for r in result.swim if r.key == "400")
    assert swim_400.venue == "open_water"
    bike = {r.key: r.value for r in result.bike}
    assert bike["longest"] == 90000
    assert bike["climbing"] == 1200


def test_triathlons_total_their_legs_when_the_parent_has_no_totals() -> None:
    parent = p.ActivityFacts(10, TODAY, "multi_sport", name="Tri", is_parent=True)
    legs = [
        p.ActivityFacts(
            11, TODAY, "open_water_swimming", duration_s=1500, distance_m=1500, parent_id=10
        ),
        ride(12, TODAY, duration_s=4000, distance_m=40000, parent_id=10),
    ]
    result = p.triathlons([parent, *legs], [parent, *legs])
    assert result == [p.TriathlonResult(10, "Tri", TODAY, 5500, 41500)]


def test_performance_periods() -> None:
    assert p.period_start("season", TODAY) == date(2026, 1, 1)
    assert p.period_start("90d", TODAY) == TODAY - timedelta(days=89)
    assert p.period_start("all", TODAY) is None


# The endpoint


async def seed(home: Home) -> date:
    today = today_in(None)
    user = home.owner.user_id
    async with get_sessionmaker()() as session, session.begin():

        def at(ago: int) -> datetime:
            return datetime.combine(today - timedelta(days=ago), datetime.min.time(), UTC)

        activities = [
            (1, "running", 5, 10000.0, 255.0, 4.0),
            (2, "running", 20, 12000.0, 250.0, 3.9),
            (3, "road_biking", 6, 60000.0, None, 8.0),
            (4, "lap_swimming", 8, 1500.0, None, 1.1),
        ]
        for activity_id, sport, ago, distance, _cp, _speed in activities:
            session.add(
                Activity(
                    user_id=user,
                    activity_id=activity_id,
                    sport=sport,
                    started_at=at(ago),
                    distance_m=distance,
                    duration_s=3000,
                    avg_hr=140,
                    raw={},
                )
            )
        await session.flush()
        for activity_id, sport, _ago, _distance, cp, speed in activities:
            power = curve(lambda t, cp=cp: cp + 20000 / t) if cp else None
            session.add(
                ActivityDerived(
                    user_id=user,
                    activity_id=activity_id,
                    moving_s=3000,
                    hr_threshold=170,
                    power_curve=power,
                    hr_curve=curve(lambda t: 150.0),
                    speed_curve=curve(lambda t, s=speed: s + 100 / t),
                    best_efforts={"5000": 1250.0}
                    if sport == "running"
                    else ({"200": 160.0, "400": 340.0} if sport == "lap_swimming" else None),
                    vo2max=50.0 if sport == "running" else None,
                    efficiency_factor=1.6 if sport == "running" else None,
                    steady=True if sport == "running" else None,
                    climbs=[
                        {
                            "start_s": 0,
                            "duration_s": 600,
                            "distance_m": 2000.0,
                            "gain_m": 120.0,
                            "grade": 0.06,
                            "vam": 720.0,
                        }
                    ]
                    if sport == "road_biking"
                    else None,
                )
            )
        session.add(HeartRateZones(user_id=user, sport="RUNNING", zone3_floor=150))
        session.add(
            Weight(user_id=user, measured_at=at(1), day=today - timedelta(days=1), weight_kg=64)
        )
    return today


async def test_performance_endpoint_returns_the_members_figures(home: Home) -> None:
    await seed(home)
    async with api(home.owner) as client:
        response = await client.get("/api/health/performance", params={"period": "90d"})
    assert response.status_code == 200
    body = response.json()
    assert body["period"] == "90d"
    model = body["run_power"]["model"]
    assert model["cp"] == pytest.approx(255, abs=0.01)  # the best of the two runs
    assert model["w_prime"] == pytest.approx(20000, abs=1)
    assert model["cp_per_kg"] == pytest.approx(255 / 64, abs=0.001)
    assert body["run_pace"]["model"]["speed"] == pytest.approx(4.0, abs=1e-4)
    assert body["swim_threshold"]["pace_per_100_s"] == pytest.approx(90)
    assert body["vo2max"]["latest"] == pytest.approx(50)
    assert len(body["vo2max"]["points"]) == 2
    assert body["bike"]["power_curve"] is None
    assert body["bike"]["climbs"][0]["vam"] == 720
    assert len(body["efficiency"]["points"]) == 2
    assert {r["key"]: r["value"] for r in body["records"]["run"]}["5000"] == 1250
    assert [i["distance_m"] for i in body["predictions"]["items"]] == [5000, 10000, 21097, 42195]


async def test_performance_validates_the_period(home: Home) -> None:
    async with api(home.owner) as client:
        assert (
            await client.get("/api/health/performance", params={"period": "x"})
        ).status_code == 422
        default = await client.get("/api/health/performance")
    assert default.json()["period"] == "season"


async def test_a_second_member_gets_nothing(home: Home) -> None:
    await seed(home)
    async with api(home.member) as client:
        body = (await client.get("/api/health/performance", params={"period": "all"})).json()
    assert body["run_power"]["model"] is None
    assert all(pt["value"] is None for pt in body["run_power"]["current"])
    assert body["vo2max"]["points"] == []
    assert body["swim_threshold"] is None
    assert body["bike"]["climbs"] == []
    assert body["weight_kg"] is None
    assert all(r["value"] is None for r in body["records"]["run"])
