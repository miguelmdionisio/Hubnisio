"""Activities API against a real database (invented values): the list, one activity's page, the
file, and that a member sees only their own."""

import itertools
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from households import Home, api
from sqlalchemy import insert

from hubnisio.core.db import get_sessionmaker
from hubnisio.health.insights.activity_view import GROUPS, sport_group
from hubnisio.health.models import (
    Activity,
    ActivityDerived,
    ActivityFile,
    ActivityLap,
    ActivityLength,
    ActivityStream,
)

pytestmark = pytest.mark.anyio

START = datetime(2026, 11, 8, 8, 12, tzinfo=UTC)


_ids = itertools.count(7_000_000_000)


def new_id() -> int:
    return next(_ids)


async def put_activity(
    user: uuid.UUID,
    *,
    sport: str = "running",
    at: datetime = START,
    name: str | None = "Long run",
    distance: float = 10000,
    duration: float = 3000,
    **more: object,
) -> int:
    activity_id = new_id()
    async with get_sessionmaker()() as session, session.begin():
        await session.execute(
            insert(Activity).values(
                user_id=user,
                activity_id=activity_id,
                name=name,
                sport=sport,
                started_at=at,
                start_local=at.replace(tzinfo=None) + timedelta(hours=1),
                duration_s=duration,
                distance_m=distance,
                raw={},
                **more,
            )
        )
    return activity_id


async def put_run_detail(user: uuid.UUID, activity_id: int) -> None:
    n = 1500
    async with get_sessionmaker()() as session, session.begin():
        await session.execute(
            insert(ActivityStream).values(
                user_id=user,
                activity_id=activity_id,
                started_at=START,
                time_s=list(range(n)),
                distance_m=[4.0 * t for t in range(n)],
                heart_rate=[150 if t < 750 else 160 for t in range(n)],
                speed=[4.0] * n,
                altitude_m=[100.0 + 0.01 * t for t in range(n)],
                cadence=[170.0] * n,
                lat=[38.7 + 0.00001 * t for t in range(n)],
                lon=[-9.1 + 0.00002 * (t % 300) for t in range(n)],
            )
        )
        await session.execute(
            insert(ActivityDerived).values(
                user_id=user,
                activity_id=activity_id,
                moving_s=n,
                hr_threshold=171,
                hr_load=82.5,
                hr_zone_s=[30, 600, 700, 170, 0, 0],
                gap_speed=4.1,
                efficiency_factor=1.25,
                decoupling_pct=3.1,
                steady=True,
                vo2max=52.5,
                climbs=[],
            )
        )
        await session.execute(
            insert(ActivityLap).values(
                user_id=user, activity_id=activity_id, lap_index=0, timer_s=250, distance_m=1000
            )
        )
        await session.execute(
            insert(ActivityFile).values(
                user_id=user,
                activity_id=activity_id,
                status="stored",
                data=b"PK-invented",
                content_type="application/zip",
                size=11,
            )
        )


async def test_the_list_is_newest_first_with_load_and_the_sports_figure(home: Home) -> None:
    owner = home.owner.user_id
    run = await put_activity(owner, at=START)
    ride = await put_activity(
        owner, sport="cycling", at=START - timedelta(days=1), distance=36000, duration=3600
    )
    swim = await put_activity(
        owner, sport="lap_swimming", at=START - timedelta(days=2), distance=1000, duration=1800
    )
    await put_run_detail(owner, run)

    async with api(home.owner) as client:
        body = (await client.get("/api/health/activities")).json()

    mine = [item for item in body["items"] if item["id"] in (run, ride, swim)]
    assert [item["id"] for item in mine] == [run, ride, swim]
    first, second, third = mine
    assert first["start"].startswith("2026-11-08T09:12") and first["group"] == "run"
    assert first["load"] == 82.5
    assert (first["figure_kind"], first["figure"]) == ("pace_km", 300)
    assert (second["figure_kind"], second["figure"]) == ("speed_kmh", 36)
    assert (third["figure_kind"], third["figure"]) == ("pace_100m", 180)
    assert second["load"] is None and first["legs"] == []


async def test_a_multisport_activity_is_one_row_with_its_legs(home: Home) -> None:
    owner = home.owner.user_id
    parent = await put_activity(
        owner,
        sport="multi_sport",
        name="Sprint triathlon",
        at=START + timedelta(days=30),
        is_parent=True,
    )
    legs = []
    for offset, sport in enumerate(("lap_swimming", "cycling", "running")):
        leg = await put_activity(
            owner,
            sport=sport,
            at=START + timedelta(days=30, minutes=10 * offset),
            parent_id=parent,
        )
        legs.append(leg)
    async with get_sessionmaker()() as session, session.begin():
        for leg, load in zip(legs, (20, 40, 30), strict=True):
            await session.execute(
                insert(ActivityDerived).values(
                    user_id=owner, activity_id=leg, moving_s=1, hr_load=load
                )
            )

    async with api(home.owner) as client:
        body = (await client.get("/api/health/activities", params={"from": "2026-12-01"})).json()
        detail = (await client.get(f"/api/health/activities/{parent}")).json()
        leg_detail = (await client.get(f"/api/health/activities/{legs[1]}")).json()

    ids = [item["id"] for item in body["items"]]
    assert parent in ids and not set(legs) & set(ids)
    row = next(item for item in body["items"] if item["id"] == parent)
    assert [leg["id"] for leg in row["legs"]] == legs
    assert [leg["group"] for leg in row["legs"]] == ["swim", "bike", "run"]
    assert row["load"] == 90
    assert [leg["id"] for leg in detail["legs"]] == legs
    assert leg_detail["parent_id"] == parent


async def test_filters_by_sport_date_and_search_and_pages_with_a_cursor(home: Home) -> None:
    owner = home.owner.user_id
    # their own corner of the calendar, so the shared database can't interfere
    base = datetime(2031, 3, 1, 7, 0, tzinfo=UTC)
    keys = [
        "running",
        "trail_running",
        "cycling",
        "lap_swimming",
        "strength_training",
        "yoga",
        "hiking",
    ]
    ids: dict[str, int] = {}
    for i, key in enumerate(keys):
        ids[key] = await put_activity(
            owner, sport=key, at=base + timedelta(days=i), name=f"{key} {i}"
        )
    window = {"from": "2031-03-01", "to": "2031-03-31"}

    async with api(home.owner) as client:
        everything = (await client.get("/api/health/activities", params=window)).json()
        found: dict[str, set[int]] = {}
        for group in GROUPS:
            response = await client.get("/api/health/activities", params={**window, "sport": group})
            found[group] = {item["id"] for item in response.json()["items"]}
        narrow = (
            await client.get(
                "/api/health/activities", params={"from": "2031-03-03", "to": "2031-03-04"}
            )
        ).json()
        search = (await client.get("/api/health/activities", params={**window, "q": "YOGA"})).json()
        underscore = (
            await client.get("/api/health/activities", params={**window, "q": "trail_"})
        ).json()
        first = (await client.get("/api/health/activities", params={**window, "limit": 3})).json()
        second = (
            await client.get(
                "/api/health/activities",
                params={**window, "limit": 3, "cursor": first["next_cursor"]},
            )
        ).json()
        last = (
            await client.get(
                "/api/health/activities",
                params={**window, "limit": 3, "cursor": second["next_cursor"]},
            )
        ).json()
        bad = await client.get("/api/health/activities", params={"cursor": "nonsense"})

    assert len(everything["items"]) == 7 and everything["next_cursor"] is None
    # the SQL filter and the Python grouping agree on every key
    for key, activity_id in ids.items():
        assert activity_id in found[sport_group(key)]
    assert sum(len(v) for v in found.values()) == 7
    assert {item["id"] for item in narrow["items"]} == {ids["cycling"], ids["lap_swimming"]}
    assert [item["id"] for item in search["items"]] == [ids["yoga"]]
    assert [item["id"] for item in underscore["items"]] == [ids["trail_running"]]
    paged = [*first["items"], *second["items"], *last["items"]]
    assert [len(first["items"]), len(second["items"]), len(last["items"])] == [3, 3, 1]
    assert last["next_cursor"] is None
    assert [item["id"] for item in paged] == [item["id"] for item in everything["items"]]
    assert bad.status_code == 422


async def test_a_run_has_all_its_sections(home: Home) -> None:
    owner = home.owner.user_id
    run = await put_activity(
        owner,
        distance=6000,
        duration=1500,
        avg_hr=155,
        elevation_gain_m=15,
        garmin_load=140,
        aerobic_te=3.8,
        anaerobic_te=0.9,
        ground_contact_ms=238,
        vertical_oscillation_cm=8.4,
        vertical_ratio_pct=7.6,
        stride_length_cm=109,
        avg_cadence=176,
        hr_zone_s=[0, 0, 0, 0, 0],
    )
    # two earlier runs set the 90-day baseline; a third is too old to count
    for days, contact in ((10, 240.0), (20, 244.0), (200, 100.0)):
        earlier = await put_activity(
            owner, at=START - timedelta(days=days), ground_contact_ms=contact, avg_cadence=174
        )
        async with get_sessionmaker()() as session, session.begin():
            await session.execute(
                insert(ActivityDerived).values(
                    user_id=owner, activity_id=earlier, moving_s=1, efficiency_factor=1.19
                )
            )
    await put_run_detail(owner, run)

    async with api(home.owner) as client:
        body = (await client.get(f"/api/health/activities/{run}")).json()

    assert body["group"] == "run" and body["family"] == "run" and body["pool"] is False
    assert body["has_file"] is True
    assert body["summary"]["graded_speed"] == pytest.approx(4.1)
    assert body["summary"]["vo2max"] == pytest.approx(52.5)
    assert body["loads"] == {
        "ours": 82.5,
        "garmin": 140,
        "aerobic_te": 3.8,
        "anaerobic_te": 0.9,
        "te_label": None,
    }
    streams = body["streams"]
    assert streams["axis"] == "distance" and len(streams["x"]) <= 600
    assert set(streams["series"]) == {"pace", "heart_rate", "altitude", "cadence"}
    assert all(len(v) == len(streams["x"]) for v in streams["series"].values())
    assert body["splits"]["kind"] == "km"
    assert [s["distance_m"] for s in body["splits"]["rows"]] == [1000] * 5 + [996]
    assert body["pool_sets"] is None
    assert body["zones"]["source"] == "ours" and body["zones"]["seconds"] == [600, 700, 170, 0, 0]
    durability = body["durability"]
    assert durability["decoupling_pct"] == 3.1 and durability["efficiency_90d"] == 1.19
    assert durability["first"]["heart_rate"] == 150 and durability["second"]["heart_rate"] == 160
    assert body["form"]["ground_contact_ms"] == {"value": 238, "avg_90d": 242}
    assert body["form"]["cadence"] == {"value": 176, "avg_90d": 174}
    assert 2 <= len(body["route"]) <= 500 and len(body["route"][0]) == 2


async def test_a_pool_swim_gets_sets_and_lengths_and_no_route(home: Home) -> None:
    owner = home.owner.user_id
    swim = await put_activity(
        owner,
        sport="lap_swimming",
        distance=100,
        duration=200,
        pool_length_m=25,
        hr_zone_s=[0, 0, 40, 20, 0],
    )
    async with get_sessionmaker()() as session, session.begin():
        await session.execute(
            insert(ActivityLength).values(
                [
                    {
                        "user_id": owner,
                        "activity_id": swim,
                        "length_index": i,
                        "active": active,
                        "swim_stroke": "freestyle" if active else None,
                        "strokes": 18 if active else None,
                        "elapsed_s": 30 if active else 20,
                        "swolf": 48 if active else None,
                    }
                    for i, active in enumerate((True, True, False, True))
                ]
            )
        )

    async with api(home.owner) as client:
        body = (await client.get(f"/api/health/activities/{swim}")).json()

    assert body["pool"] is True and body["route"] is None and body["streams"] is None
    assert [(s["lengths"], s["distance_m"], s["rest_s"]) for s in body["pool_sets"]["sets"]] == [
        (2, 50, 20),
        (1, 25, 0),
    ]
    assert len(body["pool_sets"]["lengths"]) == 3
    assert body["zones"]["source"] == "garmin"
    assert body["form"] is None and body["durability"] is None and body["splits"] is None


async def test_the_original_file_downloads_for_its_owner_only(home: Home) -> None:
    owner = home.owner.user_id
    run = await put_activity(owner)
    await put_run_detail(owner, run)
    bare = await put_activity(owner, name="No file")

    async with api(home.owner) as client:
        download = await client.get(f"/api/health/activities/{run}/file")
        missing = await client.get(f"/api/health/activities/{bare}/file")
    async with api(home.member) as client:
        theirs = await client.get(f"/api/health/activities/{run}/file")

    assert download.status_code == 200 and download.content == b"PK-invented"
    assert "attachment" in download.headers["content-disposition"]
    assert missing.status_code == 404
    assert theirs.status_code == 404


async def test_another_member_gets_nothing_and_cannot_fetch_by_id(home: Home) -> None:
    owner = home.owner.user_id
    run = await put_activity(owner, at=datetime(2032, 5, 1, 7, tzinfo=UTC))
    await put_run_detail(owner, run)

    async with api(home.member) as client:
        listing = (await client.get("/api/health/activities")).json()
        detail = await client.get(f"/api/health/activities/{run}")
        searched = (await client.get("/api/health/activities", params={"q": "Long run"})).json()
    async with api(home.owner) as client:
        own = await client.get(f"/api/health/activities/{run}")

    assert listing == {"items": [], "next_cursor": None}
    assert searched["items"] == []
    assert detail.status_code == 404
    assert own.status_code == 200
