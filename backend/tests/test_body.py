"""Body (ADR-0009, H8): the pure functions on hand-checkable inputs, and the endpoint against a
real Postgres with invented values (a second member gets nothing)."""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from households import Home, api

from hubnisio.core.db import get_sessionmaker
from hubnisio.health.insights.body import AgeReading, WeighIn, body
from hubnisio.health.models import FitnessAge, Weight, WeightGoal
from hubnisio.health.sync import today_in

pytestmark = pytest.mark.anyio

TODAY = date(2026, 11, 10)


def weigh(ago: int, kg: float, hour: int = 8, bmi: float | None = None) -> WeighIn:
    day = TODAY - timedelta(days=ago)
    return WeighIn(datetime(day.year, day.month, day.day, hour, tzinfo=UTC), day, kg, bmi)


def test_nothing_stored_is_an_honest_gap() -> None:
    result = body([], [], None, TODAY, 90)
    assert result.weight.points == []
    assert result.weight.summary.count == 0
    assert result.weight.summary.latest_kg is None
    assert result.weight.summary.change_kg is None
    assert result.fitness_age.latest is None
    assert result.first_day == TODAY - timedelta(days=89)


def test_one_weigh_in_has_a_latest_but_no_change() -> None:
    result = body([weigh(10, 78.4, bmi=24.1)], [], 74.0, TODAY, 90)
    summary = result.weight.summary
    assert (summary.count, summary.latest_kg, summary.bmi) == (1, 78.4, 24.1)
    assert summary.change_kg is None
    assert summary.to_goal_kg == 4.4
    assert result.weight.goal_kg == 74.0


def test_two_weigh_ins_give_the_change_over_the_period() -> None:
    result = body([weigh(60, 80.0), weigh(5, 78.5)], [], None, TODAY, 90)
    assert result.weight.summary.change_kg == -1.5
    assert result.weight.summary.to_goal_kg is None
    assert [p.kg for p in result.weight.points] == [80.0, 78.5]


def test_the_window_cuts_the_points_but_latest_may_be_older() -> None:
    old = weigh(200, 81.0)
    result = body([old], [], None, TODAY, 90)
    assert result.weight.points == []
    assert result.weight.summary.latest_kg == 81.0
    assert result.weight.summary.latest_day == old.day
    assert body([old], [], None, TODAY, None).weight.summary.count == 1


def test_all_time_starts_at_the_first_stored_day() -> None:
    result = body(
        [weigh(400, 85.0)], [AgeReading(TODAY - timedelta(days=30), 38.0)], None, TODAY, None
    )
    assert result.days is None
    assert result.first_day == TODAY - timedelta(days=400)


def test_a_day_with_two_weigh_ins_keeps_the_later() -> None:
    result = body([weigh(3, 79.0, hour=7), weigh(3, 78.6, hour=21)], [], None, TODAY, 90)
    assert [p.kg for p in result.weight.points] == [78.6]
    assert result.weight.summary.count == 1


def test_a_future_dated_row_is_ignored() -> None:
    assert body([weigh(-2, 70.0)], [], None, TODAY, 90).weight.summary.count == 0


def test_fitness_age_against_real_age() -> None:
    readings = [
        AgeReading(TODAY - timedelta(days=40), 36.0, 41),
        AgeReading(
            TODAY - timedelta(days=2), 34.5, 41, resting_hr=46, bmi=23.0, vigorous_days_avg=3.5
        ),
        AgeReading(TODAY - timedelta(days=1), None, 41),  # a day without a value
    ]
    result = body([], readings, None, TODAY, 90).fitness_age
    assert [p.fitness_age for p in result.points] == [36.0, 34.5, None]
    assert result.latest is not None
    assert result.latest.fitness_age == 34.5
    assert result.latest.difference == -6.5
    assert (result.latest.resting_hr, result.latest.bmi) == (46, 23.0)
    assert result.latest.vigorous_minutes_avg is None


# The endpoint


async def seed(home: Home) -> None:
    today = today_in(None)
    user = home.owner.user_id
    async with get_sessionmaker()() as session, session.begin():
        for ago, kg in ((100, "80.200"), (20, "78.400")):
            when = datetime.combine(today - timedelta(days=ago), datetime.min.time(), UTC)
            session.add(
                Weight(
                    user_id=user,
                    measured_at=when,
                    day=when.date(),
                    weight_kg=Decimal(kg),
                    bmi=Decimal("24.1"),
                )
            )
        session.add(WeightGoal(user_id=user, target_kg=Decimal("75.000")))
        session.add(
            FitnessAge(
                user_id=user,
                day=today - timedelta(days=3),
                fitness_age=Decimal("35.5"),
                chronological_age=41,
                resting_hr=46,
            )
        )


async def test_body_endpoint_returns_the_members_figures(home: Home) -> None:
    await seed(home)
    async with api(home.owner) as client:
        year = (await client.get("/api/health/body", params={"days": "365"})).json()
        quarter = (await client.get("/api/health/body", params={"days": "90"})).json()
        everything = (await client.get("/api/health/body", params={"days": "all"})).json()
    assert year["days"] == 365 and everything["days"] is None
    assert [p["kg"] for p in year["weight"]["points"]] == [80.2, 78.4]
    assert [p["kg"] for p in quarter["weight"]["points"]] == [78.4]  # 100 days ago is out
    assert quarter["weight"]["summary"]["change_kg"] is None
    assert year["weight"]["summary"]["change_kg"] == -1.8
    assert year["weight"]["goal_kg"] == 75.0
    assert year["weight"]["summary"]["to_goal_kg"] == 3.4
    assert year["weight"]["summary"]["bmi"] == 24.1
    latest = year["fitness_age"]["latest"]
    assert latest["fitness_age"] == 35.5 and latest["difference"] == -5.5
    assert latest["resting_hr"] == 46


async def test_body_validates_days_and_defaults_to_a_year(home: Home) -> None:
    async with api(home.owner) as client:
        assert (await client.get("/api/health/body", params={"days": "45"})).status_code == 422
        default = await client.get("/api/health/body")
    assert default.json()["days"] == 365


async def test_a_second_member_gets_nothing(home: Home) -> None:
    await seed(home)
    async with api(home.member) as client:
        body_out = (await client.get("/api/health/body", params={"days": "all"})).json()
    assert body_out["weight"]["points"] == []
    assert body_out["weight"]["goal_kg"] is None
    assert body_out["weight"]["summary"]["latest_kg"] is None
    assert body_out["fitness_age"]["points"] == []
    assert body_out["fitness_age"]["latest"] is None
