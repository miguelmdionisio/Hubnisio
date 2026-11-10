"""Recovery (ADR-0009, H4): the pure functions on hand-checkable inputs, and the endpoint
against a real Postgres with invented values."""

from collections.abc import Mapping
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from households import Home, api
from sqlalchemy import insert

from hubnisio.core.db import get_sessionmaker
from hubnisio.health.insights.recovery import (
    DayFacts,
    band_of,
    recovery,
    swing_of,
)
from hubnisio.health.models import DailySummary, HrvNight, Sample, SampleKind, Sleep
from hubnisio.health.sync import today_in

pytestmark = pytest.mark.anyio

TODAY = date(2026, 11, 10)


def run(days: int = 30, form: float | None = None, **series: Mapping[int, float]):
    """Facts for the 90 days to TODAY: `series` maps a field to {days ago: value}."""
    facts = []
    for ago in range(100):
        values = {f: v[ago] for f, v in series.items() if ago in v and v[ago] is not None}
        facts.append(DayFacts(day=TODAY - timedelta(days=ago), **values))
    return recovery(facts, TODAY, days, form)


def test_band_is_the_mean_plus_or_minus_three_quarters_of_a_deviation() -> None:
    values = [40.0, 60.0] * 7  # mean 50, sample variance 14 * 100 / 13
    band = band_of(values)
    assert band is not None
    spread = 0.75 * (1400 / 13) ** 0.5
    assert band.mean == 50
    assert band.low == pytest.approx(50 - spread)
    assert band.high == pytest.approx(50 + spread)


def test_no_band_under_fourteen_nights() -> None:
    assert band_of([50.0] * 13) is None
    assert band_of([50.0] * 13 + [None, None]) is None
    assert band_of([50.0, None] * 14) is not None  # 14 present, gaps between


def test_swing_is_the_coefficient_of_variation() -> None:
    assert swing_of([8, 12, 8, 12]) == pytest.approx(20.0)  # mean 10, deviation 2
    assert swing_of([10, 10, 10, 10, None, None, None]) == 0
    assert swing_of([10, 12, 14, None, None]) is None  # under four nights


def test_hrv_flags_nights_below_the_band_and_averages_the_week() -> None:
    hrv = {ago: 50.0 + (ago % 2) * 2 for ago in range(80)}  # 50 and 52
    hrv[0] = 30.0
    result = run(hrv=hrv).hrv
    last = result.points[-1]
    assert last.value == 30
    assert last.below
    assert not any(p.below for p in result.points if p.value == 52)
    assert result.summary.below_nights == sum(p.below for p in result.points)
    assert result.summary.position == "below"
    # 7 nights to today: 30 and the six before it (ago 1..6: 52, 50, 52, 50, 52, 50)
    assert last.avg7 == pytest.approx((30 + 52 * 3 + 50 * 3) / 7, abs=0.05)
    assert result.points[0].band_low is not None  # 60 nights reach back from the first day


def test_gaps_stay_gaps() -> None:
    result = run(days=30, hrv={ago: 50.0 for ago in range(3, 80)})
    assert result.hrv.points[-1].value is None
    assert result.hrv.points[-1].avg7 == 50  # four nights in its week is enough
    assert result.resting_hr.points[-1].value is None
    assert result.resting_hr.summary.latest is None
    assert result.body_battery.summary.at_wake is None
    assert result.stress.points[-1].rest_min is None
    assert result.stress.summary.avg is None


def test_hrv_without_enough_nights_has_no_band_or_position() -> None:
    result = run(hrv={ago: 50.0 for ago in range(10)})
    assert result.hrv.summary.band_low is None
    assert result.hrv.summary.position is None
    assert result.hrv.summary.avg7 == 50
    assert result.signals.items[0].state == "no_data"


def test_the_ninety_day_swing_is_the_mean_of_the_weekly_ones() -> None:
    # Alternating 8 and 12 over an even week-long window: every 7-night window holds
    # 3 or 4 of each, so the swing isn't 20 exactly; with constant values it is 0.
    flat = run(hrv={ago: 50.0 for ago in range(100)}).hrv.summary
    assert flat.swing == 0
    assert flat.swing_90 == 0
    short = run(hrv={ago: 50.0 for ago in range(10)}).hrv.summary
    assert short.swing_90 is None


def test_resting_heart_rate_change_against_its_week() -> None:
    rhr = {0: 49.0, 1: 46.0, 2: 46.0, 3: 46.0, 4: 46.0, 5: 46.0, 6: 46.0}
    summary = run(resting_hr=rhr).resting_hr.summary
    assert summary.latest == 49
    assert summary.avg7 == pytest.approx(46.4)  # 325 / 7
    assert summary.change == pytest.approx(2.6)


def test_stress_is_in_minutes_and_battery_keeps_its_days() -> None:
    result = run(
        rest_s={0: 3600.0},
        low_s={0: 1800.0},
        medium_s={0: 90.0},
        high_s={0: 600.0},
        stress_avg={0: 30.0, 1: 20.0},
        battery_charged={0: 60.0},
        battery_drained={0: 55.0},
        battery_wake={0: 82.0},
    )
    today = result.stress.points[-1]
    assert (today.rest_min, today.low_min, today.medium_min, today.high_min) == (60, 30, 1.5, 10)
    assert result.stress.summary.avg == 25
    assert result.stress.summary.high_min == 10
    assert result.body_battery.points[-1].charged == 60
    assert result.body_battery.summary.at_wake == 82
    assert result.body_battery.summary.charged == 60


def states(result) -> dict[str, str]:
    return {s.key: s.state for s in result.signals.items}


def test_signals_are_independent_and_counted() -> None:
    result = run(
        hrv={ago: 50.0 + (ago % 2) * 2 for ago in range(80)},  # today 50: inside the band
        resting_hr={0: 49.0, **{ago: 46.0 for ago in range(1, 7)}},  # 49 vs 46.43 + 3: ok
        sleep_s={0: 6 * 3600.0},
        sleep_need_min={0: 480.0},  # 360 of 480 = 75%: watch
        battery_wake={0: 60.0},  # exactly the floor: ok
    )
    assert states(result) == {
        "hrv": "ok",
        "resting_hr": "ok",
        "sleep": "watch",
        "body_battery": "ok",
    }
    assert (result.signals.ok, result.signals.total) == (3, 4)
    sleep = result.signals.items[2]
    assert (sleep.value, sleep.reference_low, sleep.reference_high) == (360, 408, 480)


def test_resting_heart_rate_more_than_three_above_its_week_is_a_watch() -> None:
    result = run(resting_hr={0: 52.0, **{ago: 46.0 for ago in range(1, 7)}})
    # week average (52 + 6 * 46) / 7 = 46.86; limit 49.86
    assert states(result)["resting_hr"] == "watch"


def test_missing_signals_say_no_data_and_do_not_count() -> None:
    result = run(battery_wake={5: 90.0})  # five days old: stale
    assert set(states(result).values()) == {"no_data"}
    assert (result.signals.ok, result.signals.total) == (0, 0)


def test_form_is_left_out_unless_given() -> None:
    assert "form" not in states(run())
    assert states(run(form=-4.0))["form"] == "ok"
    assert states(run(form=-25.0))["form"] == "watch"
    assert run(form=-25.0).signals.total == 1


# The endpoint


async def seed(home: Home) -> None:
    today = today_in(None)
    async with get_sessionmaker()() as session, session.begin():
        for ago in range(40):
            day = today - timedelta(days=ago)
            if ago != 3:  # a night the watch wasn't worn
                session.add(
                    HrvNight(user_id=home.owner.user_id, day=day, last_night_avg=55 + ago % 3)
                )
            session.add(
                DailySummary(
                    user_id=home.owner.user_id,
                    day=day,
                    resting_hr=47,
                    stress_avg=25,
                    rest_stress_s=3600,
                    high_stress_s=1200,
                    body_battery_charged=70,
                    body_battery_drained=60,
                )
            )
        ended = datetime.combine(today, datetime.min.time(), tzinfo=UTC) + timedelta(hours=6)
        session.add(
            Sleep(
                user_id=home.owner.user_id,
                day=today,
                started_at=ended - timedelta(hours=8),
                ended_at=ended,
                sleep_s=8 * 3600,
                need_minutes=480,
            )
        )
        await session.flush()
        await session.execute(
            insert(Sample),
            [
                {
                    "user_id": home.owner.user_id,
                    "kind": SampleKind.BODY_BATTERY,
                    "at": ended + timedelta(minutes=offset),
                    "day": today,
                    "value": Decimal(value),
                }
                for offset, value in ((-60, 30), (0, 78), (3, 80), (60, 70))
            ],
        )


async def test_recovery_endpoint_returns_the_members_figures(home: Home) -> None:
    await seed(home)
    async with api(home.owner) as client:
        response = await client.get("/api/health/recovery", params={"days": 30})
    assert response.status_code == 200
    body = response.json()
    assert body["days"] == 30
    assert len(body["hrv"]["points"]) == 30
    gap = body["hrv"]["points"][-1 - 3]
    assert gap["value"] is None  # a gap, not a zero
    assert body["hrv"]["summary"]["band_low"] is not None
    assert body["resting_hr"]["summary"]["latest"] == 47
    assert body["body_battery"]["summary"]["at_wake"] == 78  # the first reading after waking
    assert body["body_battery"]["summary"]["charged"] == 70
    assert body["stress"]["points"][-1]["rest_min"] == 60
    assert body["stress"]["points"][-1]["high_min"] == 20
    signals = {s["key"]: s["state"] for s in body["signals"]["items"]}
    assert signals == {"hrv": "ok", "resting_hr": "ok", "sleep": "ok", "body_battery": "ok"}
    assert body["signals"]["ok"] == 4


async def test_recovery_validates_days(home: Home) -> None:
    async with api(home.owner) as client:
        assert (await client.get("/api/health/recovery", params={"days": 45})).status_code == 422
        default = await client.get("/api/health/recovery")
    assert default.json()["days"] == 90


async def test_a_second_member_gets_nothing(home: Home) -> None:
    await seed(home)
    async with api(home.member) as client:
        body = (await client.get("/api/health/recovery", params={"days": 30})).json()
    assert all(p["value"] is None for p in body["hrv"]["points"])
    assert all(p["value"] is None for p in body["resting_hr"]["points"])
    assert body["body_battery"]["summary"]["at_wake"] is None
    assert body["signals"]["ok"] == 0
    assert body["signals"]["total"] == 0
