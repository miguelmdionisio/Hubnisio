"""Sleep: the pure functions on hand-checkable nights, and the API against a real database
(invented values; a member sees only their own nights)."""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from households import Home, api
from sqlalchemy import insert

from hubnisio.core.db import get_sessionmaker
from hubnisio.health.insights import sleep as s
from hubnisio.health.models import HrvNight, Sample, SampleKind, Sleep

pytestmark = pytest.mark.anyio

MON = date(2026, 11, 9)  # a Monday


def night(
    day: date,
    *,
    bed: int = -30,  # minutes from midnight, local
    wake: int = 420,
    offset: int = 60,
    slept_h: float = 7.5,
    need: int | None = 480,
    score: int | None = 80,
    stages: tuple[int, int, int, int] | None = None,
) -> s.NightRow:
    midnight = datetime(day.year, day.month, day.day, tzinfo=UTC) - timedelta(minutes=offset)
    deep, light, rem, awake = stages or (3600, 14400, 7200, 3600)
    return s.NightRow(
        day=day,
        started_at=midnight + timedelta(minutes=bed),
        ended_at=midnight + timedelta(minutes=wake),
        utc_offset_minutes=offset,
        sleep_s=round(slept_h * 3600),
        deep_s=deep,
        light_s=light,
        rem_s=rem,
        awake_s=awake,
        awake_count=2,
        score=score,
        score_qualifier="GOOD",
        need_minutes=need,
        avg_hr=48.5,
        avg_respiration=14.2,
        min_respiration=12.0,
        max_respiration=17.0,
        avg_spo2=95.0,
        min_spo2=89,
    )


def test_stage_shares_are_of_the_stage_total_with_typical_ranges() -> None:
    shares = {x.stage: x for x in s.stage_shares(night(MON))}

    assert [x.share for x in shares.values()] == [0.125, 0.5, 0.25, 0.125]
    assert shares["light"].typical_low == 0.45
    assert shares["awake"].typical_low is None


def test_no_stage_seconds_means_no_split() -> None:
    assert s.stage_shares(night(MON, stages=(0, 0, 0, 0))) == []


def test_night_detail_converts_to_local_time() -> None:
    detail = s.night_detail([night(MON)], MON)

    assert detail is not None
    assert detail.started_at == datetime(2026, 11, 8, 23, 30)
    assert (detail.bed_min, detail.wake_min) == (-30, 420)
    assert detail.in_bed_s == 450 * 60


def test_a_night_not_worn_has_no_detail() -> None:
    assert s.night_detail([night(MON)], MON + timedelta(days=1)) is None
    unworn = night(MON, slept_h=0)
    assert s.night_detail([unworn], MON) is None


def test_score_against_the_30_nights_before() -> None:
    rows = [night(MON - timedelta(days=n), score=70 + n) for n in range(1, 4)]  # 71, 72, 73
    rows.append(night(MON, score=84))

    detail = s.night_detail(rows, MON)

    assert detail is not None
    assert detail.score_vs_baseline == 12.0


def test_no_earlier_nights_means_no_baseline() -> None:
    detail = s.night_detail([night(MON)], MON)
    assert detail is not None
    assert detail.score_vs_baseline is None


def test_debt_is_need_less_slept_over_seven_nights() -> None:
    rows = [night(MON - timedelta(days=n), slept_h=7.5) for n in range(7)]

    debt = s.sleep_debt(rows, MON)

    assert (debt.nights, debt.missing) == (7, 0)
    assert (debt.need_minutes, debt.slept_minutes, debt.debt_minutes) == (3360, 3150, 210)


def test_debt_skips_nights_without_a_reading_instead_of_counting_zero() -> None:
    rows = [night(MON - timedelta(days=n), slept_h=8.5) for n in (0, 1, 2, 3, 4)]
    rows.append(night(MON - timedelta(days=5), need=None))
    rows.append(night(MON - timedelta(days=9)))  # outside the seven

    debt = s.sleep_debt(rows, MON)

    assert (debt.nights, debt.missing) == (5, 2)
    assert debt.debt_minutes == 5 * 480 - 5 * 510  # ahead: negative


def test_neighbours_skip_the_gaps() -> None:
    days = [date(2026, 11, 1), date(2026, 11, 4), date(2026, 11, 9)]
    assert s.neighbours(days, date(2026, 11, 4)) == (date(2026, 11, 1), date(2026, 11, 9))
    assert s.neighbours(days, date(2026, 11, 9)) == (date(2026, 11, 4), None)
    assert s.neighbours(days, date(2026, 11, 5)) == (date(2026, 11, 4), date(2026, 11, 9))


def test_readings_keep_the_low_and_its_time() -> None:
    start = night(MON).started_at
    samples = [
        s.SampleRow(start + timedelta(minutes=m), v)
        for m, v in ((10, 52.0), (130, 44.0), (250, 49.0))
    ] + [s.SampleRow(start - timedelta(minutes=5), 90.0)]  # before the night: ignored

    detail = s.night_detail([night(MON)], MON, heart_rate=samples)

    assert detail is not None
    hr = detail.heart_rate
    assert (hr.low, hr.low_at, hr.high, hr.high_at) == (44.0, 130, 52.0, 10)
    assert hr.avg == 48.5  # the night's own average wins
    assert [p.t for p in hr.series] == [10, 130, 250]


def test_without_samples_the_summary_stands_and_the_series_is_empty() -> None:
    detail = s.night_detail([night(MON)], MON, hrv_night=s.HrvRow(MON, 58, 81))

    assert detail is not None
    assert detail.hrv.series == []
    assert (detail.hrv.avg, detail.hrv.high) == (58, 81.0)
    assert (detail.spo2.avg, detail.spo2.low) == (95.0, 89)


# --- trends ---------------------------------------------------------------------------------


def test_trend_has_a_point_per_day_and_gaps_are_not_zeros() -> None:
    rows = [night(MON - timedelta(days=n), slept_h=8.0, score=90 - n) for n in (0, 2, 3)]

    t = s.trends(rows, MON, 7, {})

    assert t.points[0].day == MON - timedelta(days=6)
    assert len(t.points) == 7
    gaps = [p for p in t.points if not p.worn]
    assert len(gaps) == 4
    assert all(p.slept_s is None and p.score is None for p in gaps)
    assert t.nights_worn == 3
    assert t.average_slept_minutes == 480  # not dragged down by the gaps
    assert t.average_need_minutes == 480


def test_schedule_spread_is_the_standard_deviation_of_bed_and_wake_times() -> None:
    rows = [
        night(MON, bed=-30, wake=420),
        night(MON - timedelta(days=1), bed=30, wake=420),
    ]

    spread = s.trends(rows, MON, 2, {}).schedule

    assert spread.nights == 2
    assert (spread.bed_avg, spread.bed_sd) == (0, 30)
    assert (spread.wake_avg, spread.wake_sd) == (420, 0)


def test_schedule_splits_weekend_nights_from_weekday_ones() -> None:
    sat, sun = date(2026, 11, 7), date(2026, 11, 8)
    rows = [
        night(MON, bed=-40, wake=410),
        night(sat, bed=20, wake=500),
        night(sun, bed=40, wake=520),
    ]

    spread = s.trends(rows, MON, 3, {}).schedule

    assert (spread.weekday_bed_avg, spread.weekday_wake_avg) == (-40, 410)
    assert (spread.weekend_bed_avg, spread.weekend_wake_avg) == (30, 510)


def test_one_night_has_no_spread() -> None:
    spread = s.trends([night(MON)], MON, 1, {}).schedule
    assert spread.bed_sd is None and spread.wake_sd is None


def _linear(count: int) -> tuple[list[s.NightRow], dict[date, int | None]]:
    """Hours slept 6.0, 6.1, ... with the next morning's HRV exactly 10 ms per hour plus 5."""
    rows, hrv = [], {}
    for n in range(count):
        day = MON - timedelta(days=count - 1 - n)
        hours = 6 + n / 10
        rows.append(night(day, slept_h=hours))
        hrv[day + timedelta(days=1)] = round(10 * hours + 5)
    return rows, hrv


def test_sleep_against_next_mornings_hrv_has_a_line_and_r() -> None:
    rows, hrv = _linear(20)

    c = s.trends(rows, MON, 20, hrv).correlation

    assert len(c.pairs) == 20
    assert c.slope is not None and c.intercept is not None and c.r is not None
    assert c.slope == pytest.approx(10, abs=0.2)
    assert c.intercept == pytest.approx(5, abs=1.5)
    assert c.r == pytest.approx(1, abs=0.01)


def test_the_correlation_needs_twenty_pairs() -> None:
    rows, hrv = _linear(19)

    c = s.trends(rows, MON, 19, hrv).correlation

    assert len(c.pairs) == 19
    assert (c.slope, c.intercept, c.r) == (None, None, None)


def test_pairs_use_the_next_day_hrv_and_skip_nights_without_one() -> None:
    rows = [night(MON), night(MON - timedelta(days=1))]
    hrv: dict[date, int | None] = {MON + timedelta(days=1): 60, MON: None}

    pairs = s.trends(rows, MON, 2, hrv).correlation.pairs

    assert [(p.day, p.hrv) for p in pairs] == [(MON, 60)]


def test_score_by_weekday_averages_per_weekday_and_leaves_empty_ones_empty() -> None:
    rows = [
        night(MON, score=80),
        night(MON - timedelta(days=7), score=70),
        night(MON + timedelta(days=1), score=60),  # a Tuesday
    ]

    scores = s.trends(rows, MON + timedelta(days=1), 14, {}).weekday_scores

    assert (scores[0].nights, scores[0].score) == (2, 75)
    assert (scores[1].nights, scores[1].score) == (1, 60)
    assert (scores[2].nights, scores[2].score) == (0, None)


# --- API ------------------------------------------------------------------------------------


async def put_night(user_id, day: date, *, hours: float = 7.5, score: int = 80) -> None:
    row = night(day, slept_h=hours, score=score)
    async with get_sessionmaker()() as session, session.begin():
        await session.execute(
            insert(Sleep).values(
                user_id=user_id,
                day=day,
                started_at=row.started_at,
                ended_at=row.ended_at,
                utc_offset_minutes=row.utc_offset_minutes,
                sleep_s=row.sleep_s,
                deep_s=row.deep_s,
                light_s=row.light_s,
                rem_s=row.rem_s,
                awake_s=row.awake_s,
                awake_count=row.awake_count,
                score=score,
                score_qualifier="GOOD",
                need_minutes=480,
                avg_hr=Decimal("48.5"),
                avg_spo2=Decimal("95.0"),
                min_spo2=89,
            )
        )


async def put_samples(
    user_id, kind: SampleKind, day: date, minutes: list[tuple[int, float]]
) -> None:
    start = night(day).started_at
    async with get_sessionmaker()() as session, session.begin():
        await session.execute(
            insert(Sample),
            [
                {
                    "user_id": user_id,
                    "kind": kind,
                    "at": start + timedelta(minutes=m),
                    "day": day,
                    "value": Decimal(str(v)),
                }
                for m, v in minutes
            ],
        )


async def test_night_defaults_to_the_latest_and_steps_over_gaps(home: Home) -> None:
    owner = home.owner.user_id
    for day in (MON - timedelta(days=5), MON - timedelta(days=2), MON):
        await put_night(owner, day)
    await put_samples(owner, SampleKind.HEART_RATE, MON, [(10, 52), (130, 44)])
    await put_samples(owner, SampleKind.SPO2, MON, [(60, 96), (180, 92)])
    async with get_sessionmaker()() as session, session.begin():
        await session.execute(
            insert(HrvNight).values(
                user_id=owner, day=MON, last_night_avg=58, last_night_5min_high=81
            )
        )

    async with api(home.owner) as client:
        latest = (await client.get("/api/health/sleep/night")).json()
        middle = (await client.get("/api/health/sleep/night", params={"date": "2026-11-07"})).json()
        absent = (await client.get("/api/health/sleep/night", params={"date": "2026-11-08"})).json()

    assert latest["day"] == "2026-11-09"
    assert latest["previous_day"] == "2026-11-07" and latest["next_day"] is None
    night_ = latest["night"]
    assert night_["slept_s"] == 27000 and night_["score"] == 80
    assert night_["bed_min"] == -30 and night_["wake_min"] == 420
    assert [x["stage"] for x in night_["stages"]] == ["deep", "light", "rem", "awake"]
    assert night_["heart_rate"]["low"] == 44 and night_["heart_rate"]["low_at"] == 130
    assert len(night_["heart_rate"]["series"]) == 2
    assert night_["spo2"]["low"] == 92
    assert night_["hrv"]["avg"] == 58 and night_["hrv"]["high"] == 81
    assert middle["previous_day"] == "2026-11-04" and middle["next_day"] == "2026-11-09"
    # a day with no night is a gap, still placed between its neighbours
    assert absent["night"] is None
    assert (absent["previous_day"], absent["next_day"]) == ("2026-11-07", "2026-11-09")


async def test_a_member_with_no_nights_gets_nothing(home: Home) -> None:
    await put_night(home.owner.user_id, MON)
    await put_samples(home.owner.user_id, SampleKind.HEART_RATE, MON, [(10, 52)])

    async with api(home.member) as client:
        empty = (await client.get("/api/health/sleep/night")).json()
        theirs = (await client.get("/api/health/sleep/night", params={"date": "2026-11-09"})).json()
        trends = (await client.get("/api/health/sleep/trends")).json()

    assert empty == {"day": None, "night": None, "previous_day": None, "next_day": None}
    assert theirs["night"] is None and theirs["previous_day"] is None
    assert trends["nights_worn"] == 0
    assert all(not p["worn"] for p in trends["points"])


async def test_trends_cover_the_window_up_to_the_latest_night(home: Home) -> None:
    owner = home.owner.user_id
    for n in (0, 1, 3):
        await put_night(owner, MON - timedelta(days=n), score=70 + n)

    async with api(home.owner) as client:
        response = await client.get("/api/health/sleep/trends", params={"nights": 30})
        bad = await client.get("/api/health/sleep/trends", params={"nights": 45})

    assert bad.status_code == 422
    assert response.status_code == 200, response.text
    data = response.json()
    assert (data["start"], data["end"], data["nights"]) == ("2026-10-11", "2026-11-09", 30)
    assert len(data["points"]) == 30
    assert data["nights_worn"] == 3
    assert data["average_slept_minutes"] == 450
    assert data["points"][-3]["worn"] is False  # the 7th, a gap
    assert data["correlation"]["r"] is None  # too few pairs
    monday = data["weekday_scores"][0]
    assert monday["nights"] == 1 and monday["score"] == 70
