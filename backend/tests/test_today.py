"""Today (ADR-0009, H8): one call that composes what Training, Sleep, Recovery and Activities
return, against a real Postgres with invented values."""

from datetime import timedelta

import pytest
from households import Home, api
from sqlalchemy import update
from test_recovery import seed as seed_recovery
from test_training import seed as seed_training

from hubnisio.core.db import get_sessionmaker
from hubnisio.health.models import Sleep
from hubnisio.health.sync import today_in

pytestmark = pytest.mark.anyio


async def seed(home: Home) -> None:
    today = today_in(None)
    await seed_training(home, today)
    await seed_recovery(home)
    async with get_sessionmaker()() as session, session.begin():
        await session.execute(
            update(Sleep)
            .where(Sleep.user_id == home.owner.user_id, Sleep.day == today)
            .values(deep_s=4800, light_s=14400, rem_s=6600, awake_s=1800, score=82, awake_count=2)
        )


async def test_today_equals_what_each_page_returns(home: Home) -> None:
    await seed(home)
    async with api(home.owner) as client:
        today = (await client.get("/api/health/today")).json()
        training = (await client.get("/api/health/training", params={"days": "90"})).json()
        night = (await client.get("/api/health/sleep/night")).json()
        recovery = (await client.get("/api/health/recovery", params={"days": 30})).json()
        activities = (await client.get("/api/health/activities", params={"limit": 5})).json()

    # Training: the last 90 days of fitness, fatigue and form, and the figure
    assert today["fitness"] == training["points"]
    summary = training["summary"]
    assert today["figures"]["form"] == {
        "form": summary["form"],
        "band": summary["band"],
        "fitness": summary["fitness"],
    }

    # Recovery: HRV for 30 nights, the figures and the signals
    assert today["hrv"] == recovery["hrv"]
    assert today["hrv"]["points"][-4]["value"] is None  # the night not worn: a gap
    assert today["signals"] == recovery["signals"]
    assert today["figures"]["hrv"] == {
        "avg7": recovery["hrv"]["summary"]["avg7"],
        "position": recovery["hrv"]["summary"]["position"],
    }
    rhr = recovery["resting_hr"]["summary"]
    assert today["figures"]["resting_hr"] == {
        "latest": rhr["latest"],
        "avg7": rhr["avg7"],
        "change": rhr["change"],
    }

    # Sleep: last night, its stages, and the figure
    detail = night["night"]
    last = today["night"]
    assert last["last_night"] is True
    assert last["day"] == night["day"] == today["today"]
    for key in (
        "started_at",
        "ended_at",
        "bed_min",
        "wake_min",
        "slept_s",
        "score",
        "score_qualifier",
        "need_minutes",
        "in_bed_s",
        "stages",
    ):
        assert last[key] == detail[key]
    assert [s["stage"] for s in last["stages"]] == ["deep", "light", "rem", "awake"]
    assert today["figures"]["sleep"] == {
        "day": night["day"],
        "last_night": True,
        "slept_s": detail["slept_s"],
        "score": 82,
        "need_minutes": 480,
    }

    # Activities: the five newest, a multisport parent as one row
    assert [a["id"] for a in today["activities"]] == [a["id"] for a in activities["items"]]
    assert 9003 in [a["id"] for a in today["activities"]]
    assert 9004 not in [a["id"] for a in today["activities"]]
    parent = next(a for a in today["activities"] if a["id"] == 9003)
    assert parent["load"] == 40.0  # its leg's load, as the list says
    listed = next(a for a in activities["items"] if a["id"] == 9003)
    for key in ("sport", "group", "name", "start", "distance_m", "duration_s", "load"):
        assert parent[key] == listed[key]


async def test_the_week_is_seven_days_of_hours_by_sport(home: Home) -> None:
    await seed(home)
    async with api(home.owner) as client:
        week = (await client.get("/api/health/today")).json()["week"]
    assert len(week["days"]) == 7
    # Running 3 days ago and cycling 5 days ago, an hour each; the multisport leg is 8 ago.
    assert week["total_hours"] == pytest.approx(2.0)
    assert week["average_hours"] == pytest.approx(2.0 / 7)
    assert week["days"][-4]["run"] == pytest.approx(1.0)
    assert week["days"][-6]["bike"] == pytest.approx(1.0)
    assert week["days"][-1] == {
        "day": week["days"][-1]["day"],
        "swim": 0,
        "bike": 0,
        "run": 0,
        "strength": 0,
        "other": 0,
    }


async def test_the_latest_night_is_dated_when_last_night_has_none(home: Home) -> None:
    await seed(home)
    today = today_in(None)
    async with get_sessionmaker()() as session, session.begin():
        await session.execute(
            update(Sleep)
            .where(Sleep.user_id == home.owner.user_id)
            .values(day=today - timedelta(days=400))
        )
    async with api(home.owner) as client:
        body = (await client.get("/api/health/today")).json()
    assert body["night"]["last_night"] is False
    assert body["figures"]["sleep"]["last_night"] is False
    assert body["figures"]["sleep"]["day"] == body["night"]["day"] != str(today)


async def test_a_second_member_gets_nothing(home: Home) -> None:
    await seed(home)
    async with api(home.member) as client:
        response = await client.get("/api/health/today")
    assert response.status_code == 200
    body = response.json()
    assert body["fitness"] == []
    assert body["figures"]["form"] == {"form": None, "band": None, "fitness": None}
    assert body["figures"]["sleep"] is None
    assert body["figures"]["hrv"] == {"avg7": None, "position": None}
    assert body["figures"]["resting_hr"] == {"latest": None, "avg7": None, "change": None}
    assert body["night"] is None
    assert body["activities"] == []
    assert body["week"]["total_hours"] == 0
    assert all(p["value"] is None for p in body["hrv"]["points"])
    assert body["signals"]["ok"] == 0
    assert body["signals"]["total"] == 0
