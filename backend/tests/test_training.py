"""Training (ADR-0009, H6): the pure functions on hand-checkable inputs, and the endpoint
against a real Postgres with invented values."""

from datetime import UTC, date, datetime, timedelta

import pytest
from households import Home, api
from sqlalchemy import insert

from hubnisio.core.db import get_sessionmaker
from hubnisio.health.insights.training import (
    ActivityRow,
    band_of,
    current_form,
    daily_load,
    ewma,
    first_monday,
    intensity,
    load_series,
    monthly_totals,
    sport_of,
    summarize,
    weekly_hours,
)
from hubnisio.health.models import Activity, ActivityDerived
from hubnisio.health.sync import today_in

pytestmark = pytest.mark.anyio

D0 = date(2026, 1, 5)  # a Monday


def row(day: date, load: float | None = 100, sport: str = "running", hours: float = 1.0, **kw):
    return ActivityRow(day=day, sport=sport, duration_s=hours * 3600, load=load, **kw)


def test_daily_load_sums_a_day_and_zeroes_rest_days() -> None:
    loads = daily_load([row(D0, 40), row(D0, 60), row(D0 + timedelta(days=3), 30)])
    assert loads == {
        D0: 100,
        D0 + timedelta(days=1): 0,
        D0 + timedelta(days=2): 0,
        D0 + timedelta(days=3): 30,
    }
    assert daily_load([]) == {}


def test_a_known_three_day_sequence() -> None:
    # Loads 42, 0, 84: fitness (tc 42) 1, 0.976..., then +(84 - x) / 42.
    fitness = ewma([42, 0, 84], 42)
    assert fitness[0] == pytest.approx(1.0)
    assert fitness[1] == pytest.approx(1.0 - 1 / 42)
    assert fitness[2] == pytest.approx(fitness[1] + (84 - fitness[1]) / 42)
    fatigue = ewma([42, 0, 84], 7)
    assert fatigue[0] == pytest.approx(6.0)
    assert fatigue[1] == pytest.approx(6.0 - 6 / 7)


def test_constant_load_converges_to_that_load() -> None:
    rows = [row(D0 + timedelta(days=i), 80) for i in range(400)]
    last = load_series(rows, D0 + timedelta(days=399))[-1]
    assert last.fitness == pytest.approx(80, abs=0.05)
    assert last.fatigue == pytest.approx(80, abs=0.001)
    assert last.form == pytest.approx(0, abs=0.1)


def test_form_is_yesterdays_fitness_less_yesterdays_fatigue() -> None:
    series = load_series([row(D0, 42)], D0 + timedelta(days=1))
    assert series[0].form == 0  # nothing before the first day
    assert series[1].form == pytest.approx(1.0 - 6.0)
    assert current_form([row(D0, 42)], D0 + timedelta(days=1)) == pytest.approx(-5.0)
    assert current_form([], D0) is None
    # Days after the last activity are rest days and keep running.
    assert load_series([row(D0, 42)], D0 + timedelta(days=9))[-1].load == 0


def test_the_history_before_the_window_still_counts() -> None:
    rows = [row(D0 + timedelta(days=i), 60) for i in range(100)]
    full = load_series(rows, D0 + timedelta(days=99))
    cropped = [p for p in full if p.day >= D0 + timedelta(days=70)]
    assert cropped[0].fitness > 45  # not restarted at zero


def test_bands_and_their_edges() -> None:
    assert band_of(5.1) == "fresh"
    assert band_of(5) == "neutral"
    assert band_of(-10) == "neutral"
    assert band_of(-10.1) == "optimal"
    assert band_of(-30) == "optimal"
    assert band_of(-30.1) == "high_risk"


def test_ramp_and_change_need_enough_history() -> None:
    short = summarize(
        load_series([row(D0 + timedelta(days=i), 50) for i in range(20)], D0 + timedelta(days=19))
    )
    assert short.ramp_per_week is None
    assert short.fitness_change is None
    rows = [row(D0 + timedelta(days=i), 50) for i in range(60)]
    series = load_series(rows, D0 + timedelta(days=59))
    summary = summarize(series)
    assert summary.ramp_per_week == pytest.approx((series[-1].fitness - series[-29].fitness) / 4)
    assert summary.fitness_change == pytest.approx(series[-1].fitness - series[-43].fitness)
    assert summary.ramp_safe is True
    steep = summarize(
        load_series([row(D0 + timedelta(days=i), 500) for i in range(40)], D0 + timedelta(days=39))
    )
    assert steep.ramp_safe is False
    assert summarize([]).fitness is None


def test_sport_groups() -> None:
    assert [sport_of(k) for k in ("trail_running", "indoor_cycling", "lap_swimming")] == [
        "run",
        "bike",
        "swim",
    ]
    assert sport_of("strength_training") == "strength"
    assert sport_of("walking") == "other"
    assert sport_of(None) == "other"


def test_hours_per_week_by_sport_with_a_partial_current_week() -> None:
    today = D0 + timedelta(days=15)  # Tuesday of the third week
    rows = [
        row(D0, hours=1.5),
        row(D0 + timedelta(days=2), sport="cycling", hours=2),
        row(D0 + timedelta(days=15), sport="lap_swimming", hours=1),
    ]
    result = weekly_hours(rows, D0, today)
    assert [w.week_start for w in result.weeks] == [
        D0,
        D0 + timedelta(days=7),
        D0 + timedelta(days=14),
    ]
    assert (result.weeks[0].run, result.weeks[0].bike) == (1.5, 2)
    assert result.weeks[1].run == 0  # a rest week is a zero
    assert result.weeks[2].swim == 1
    assert [w.partial for w in result.weeks] == [False, False, True]
    assert result.average == pytest.approx(3.5 / 2)  # the partial week is left out
    assert first_monday(D0) == D0
    assert first_monday(D0 + timedelta(days=1)) == D0 + timedelta(days=7)


def test_zones_group_and_share() -> None:
    zones = [100, 200, 300, 400, 500, 500]  # below z1, z1..z5
    rows = [
        row(D0, zone_s=zones),
        row(D0, sport="cycling", zone_s=[0, 0, 600, 200, 100, 100]),
        row(D0, sport="strength_training"),  # no zones
        row(D0 - timedelta(days=60), zone_s=zones),  # outside
    ]
    result = {i.sport: i for i in intensity(rows, D0 - timedelta(days=10), D0)}
    run = result["run"]
    assert (run.z12_s, run.z3_s, run.z45_s) == (600, 400, 1000)
    assert run.z12_share == pytest.approx(0.3)
    assert result["bike"].z3_share == pytest.approx(0.2)
    assert result["all"].z12_s == 1200
    assert "strength" not in result
    assert intensity([], D0, D0) == []


def test_monthly_totals_mark_the_current_month_partial() -> None:
    today = date(2026, 3, 10)
    rows = [
        row(date(2026, 1, 20), 50, distance_m=10000, climb_m=100),
        row(date(2026, 1, 21), 20, sport="cycling", distance_m=40000, climb_m=300),
        row(date(2026, 3, 2), 70, sport="lap_swimming", distance_m=2000),
    ]
    months = monthly_totals(rows, date(2026, 1, 1), today)
    assert [m.month for m in months] == [date(2026, 3, 1), date(2026, 2, 1), date(2026, 1, 1)]
    assert [m.partial for m in months] == [True, False, False]
    jan = months[2]
    assert (jan.run_m, jan.bike_m, jan.sessions, jan.hours, jan.load, jan.climb_m) == (
        10000,
        40000,
        2,
        2,
        70,
        400,
    )
    assert months[1].sessions == 0
    assert months[0].swim_m == 2000


# The endpoint


async def seed(home: Home, today: date) -> None:
    async with get_sessionmaker()() as session, session.begin():
        base = {"user_id": home.owner.user_id, "raw": {}}
        specs = [
            # (id, days ago, sport, is_parent, parent_id, load, zones)
            (9001, 3, "running", False, None, 80.0, [60, 600, 600, 300, 120, 60]),
            (9002, 5, "cycling", False, None, 120.0, [0, 900, 900, 600, 300, 100]),
            (9003, 8, "multi_sport", True, None, 999.0, None),  # a parent: not counted
            (9004, 8, "lap_swimming", False, 9003, 40.0, [0, 1200, 300, 0, 0, 0]),
            (9005, 40, "running", False, None, None, None),  # no heart rate
        ]
        for aid, ago, sport, parent, parent_id, load, zones in specs:
            when = datetime.combine(today - timedelta(days=ago), datetime.min.time(), UTC)
            await session.execute(
                insert(Activity).values(
                    **base,
                    activity_id=aid,
                    sport=sport,
                    started_at=when.replace(hour=9),
                    start_local=when.replace(hour=9, tzinfo=None),
                    duration_s=3600,
                    distance_m=10000,
                    elevation_gain_m=100,
                    is_parent=parent,
                    parent_id=parent_id,
                )
            )
            await session.execute(
                insert(ActivityDerived).values(
                    **{
                        "user_id": home.owner.user_id,
                        "activity_id": aid,
                        "moving_s": 3600,
                        "hr_load": load,
                        "hr_zone_s": zones,
                    }
                )
            )


async def test_endpoint_returns_the_members_training(home: Home) -> None:
    today = today_in(None)
    await seed(home, today)
    async with api(home.owner) as client:
        response = await client.get("/api/health/training", params={"days": "90"})
        everything = await client.get("/api/health/training", params={"days": "all"})
        short = await client.get("/api/health/training", params={"days": "180"})
    assert response.status_code == 200
    body = response.json()
    assert body["first_day"] == str(today - timedelta(days=40))  # no earlier activity
    assert len(body["points"]) == 41
    assert sum(p["load"] for p in body["points"]) == pytest.approx(240.0)  # parent not counted
    assert body["summary"]["fitness"] > 0
    assert body["summary"]["band"] in {"fresh", "neutral", "optimal", "high_risk"}
    swim_zones = next(i for i in body["intensity"] if i["sport"] == "swim")
    assert swim_zones["z12_s"] == 1500
    assert body["months"][0]["partial"] is True
    assert sum(m["sessions"] for m in body["months"]) == 4  # legs and rides, no parent
    assert everything.json()["first_day"] == str(today - timedelta(days=40))
    assert len(everything.json()["points"]) == 41
    assert short.status_code == 200
    assert (await api_get(home, "45")).status_code == 422


async def api_get(home: Home, days: str):
    async with api(home.owner) as client:
        return await client.get("/api/health/training", params={"days": days})


async def test_a_second_member_gets_nothing(home: Home) -> None:
    await seed(home, today_in(None))
    async with api(home.member) as client:
        body = (await client.get("/api/health/training", params={"days": "all"})).json()
    assert body["first_day"] is None
    assert body["points"] == []
    assert body["months"] == []
    assert body["intensity"] == []
    assert body["summary"]["fitness"] is None


async def test_form_joins_the_recovery_signals(home: Home) -> None:
    await seed(home, today_in(None))
    async with api(home.owner) as client:
        mine = (await client.get("/api/health/recovery", params={"days": 30})).json()
    assert "form" in {s["key"] for s in mine["signals"]["items"]}
    async with api(home.member) as client:
        theirs = (await client.get("/api/health/recovery", params={"days": 30})).json()
    assert "form" not in {s["key"] for s in theirs["signals"]["items"]}
