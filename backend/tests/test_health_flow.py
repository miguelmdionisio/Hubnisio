"""Health end to end against a fake Garmin (ADR-0009): linking, the first sync and later ones,
failures, renormalize, the API, and that a member sees only their own health data."""

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Any

import fit_data as fit
import garmin_data as g
import httpx
import pytest
from analytics_data import email_of
from households import Home, api
from procrastinate.testing import InMemoryConnector
from sqlalchemy import delete, func, select, update

from hubnisio.cli import garmin_link, garmin_renormalize, garmin_sync
from hubnisio.core.auth import Principal
from hubnisio.core.db import get_sessionmaker
from hubnisio.core.settings import get_settings
from hubnisio.health import sync, tasks
from hubnisio.health.ingest import fact_counts
from hubnisio.health.insights import load, running
from hubnisio.health.models import (
    FACT_TABLES,
    Activity,
    ActivityDerived,
    ActivityFile,
    ActivityLength,
    ActivityStream,
    Connection,
    ConnectionStatus,
    DailySummary,
    ProviderPayload,
    Sleep,
    SyncCursor,
    SyncRun,
    SyncStatus,
)
from hubnisio.health.providers.garmin import client as garmin_client
from hubnisio.health.providers.garmin.client import GarminClient
from hubnisio.health.scoping import mine, own_connection
from hubnisio.jobs import app as job_app

pytestmark = pytest.mark.anyio

TODAY = sync.today_in(g.TIME_ZONE)
START = TODAY - timedelta(days=3)  # the backfill's first day in these tests: four days


async def _no_sleep(_seconds: float) -> None:
    return None


@dataclass
class Setup:
    home: Home
    garmin: g.FakeGarmin
    jobs: InMemoryConnector

    def client(self, path: Path) -> GarminClient:
        return GarminClient(path, transport=httpx.MockTransport(self.garmin), sleep=_no_sleep)

    def connection_client(self, connection: Connection) -> GarminClient:
        return self.client(get_settings().garmin_keys_dir / connection.key_file)

    async def link(self, principal: Principal, expires: date | None = None) -> int:
        expires = expires or TODAY + timedelta(days=200)
        return await garmin_link(
            await email_of(principal), "garmin", expires, client_factory=self.client
        )

    async def sync(
        self, trigger: sync.SyncTrigger = sync.SyncTrigger.SCHEDULED, **kwargs: Any
    ) -> sync.SyncOutcome:
        connection = await connection_of(self.home.owner)
        return await sync.sync_connection(
            connection.id, trigger=trigger, client_factory=self.connection_client, **kwargs
        )


@pytest.fixture
def setup(home: Home, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Setup]:
    (tmp_path / "garmin").write_text(f"key={g.KEY}\n", encoding="utf-8")
    monkeypatch.setenv("HUBNISIO_GARMIN_KEYS_DIR", str(tmp_path))
    monkeypatch.setattr(sync, "BACKFILL_START", START)
    get_settings.cache_clear()
    garmin = g.FakeGarmin(
        weigh_ins=[TODAY - timedelta(days=1)], weight_goal_kg=68.0, activities=activities()
    )
    jobs = InMemoryConnector()
    with job_app.replace_connector(jobs):
        yield Setup(home, garmin, jobs)
    get_settings.cache_clear()


async def connection_of(principal: Principal) -> Connection:
    async with get_sessionmaker()() as session:
        connection = await own_connection(session, principal)
    assert connection is not None
    return connection


async def counts_of(principal: Principal) -> dict[str, int]:
    async with get_sessionmaker()() as session:
        return await fact_counts(session, principal.user_id)


async def cursors_of(principal: Principal) -> dict[str, date]:
    connection = await connection_of(principal)
    async with get_sessionmaker()() as session:
        rows = await session.execute(
            select(SyncCursor.kind, SyncCursor.synced_through).where(
                SyncCursor.connection_id == connection.id
            )
        )
        return {kind: day for kind, day in rows}


async def linked(setup: Setup) -> Setup:
    assert await setup.link(setup.home.owner) == 0
    setup.jobs.jobs.clear()  # the worker took the initial sync
    return setup


RUN_ID, SWIM_ID = 7001, 7002
RUN_START = datetime.combine(TODAY - timedelta(days=1), time(7), UTC)
SWIM_START = RUN_START + timedelta(hours=10)
SWIM_LENGTHS = ((30.0, True, 16), (45.0, False, 0), (28.0, True, 15), (29.0, True, 15))


def activities() -> list[g.FakeActivity]:
    """Yesterday: a 25-minute run at 3 m/s and heart rate 150, then a pool swim."""
    run = fit.Leg("running", RUN_START, 1500, power=lambda _s: 250, laps=2)
    swim = fit.Leg(
        "swimming",
        SWIM_START,
        0,
        sub_sport="lap_swimming",
        lengths=SWIM_LENGTHS,
        pool_length=25.0,
    )
    return [
        g.FakeActivity(
            RUN_ID, "running", RUN_START, 1500, 4500.0, fit.zipped(fit.activity_file(run))
        ),
        g.FakeActivity(
            SWIM_ID, "lap_swimming", SWIM_START, 132, 75.0, fit.zipped(fit.activity_file(swim))
        ),
    ]


FULL = {
    "activities": 2,
    "activity_streams": 1,  # a pool swim has lengths, no samples
    "activity_laps": 3,
    "activity_lengths": 4,
    "activity_derived": 2,
    "activity_files": 2,
    "daily_summaries": 4,
    "sleeps": 4,
    "hrv_nights": 4,
    "heart_rate_zones": 2,
    "fitness_ages": 1,
    "weights": 1,
    "weight_goals": 1,
    "samples.heart_rate": 16,  # four a day: the fake's fifth reading is a gap
    "samples.hrv": 16,
    "samples.spo2": 12,
    "samples.body_battery": 12,
}


async def test_link_queues_the_first_sync(setup: Setup) -> None:
    assert await setup.link(setup.home.owner) == 0

    connection = await connection_of(setup.home.owner)
    assert connection.status is ConnectionStatus.ACTIVE
    assert connection.key_file == "garmin"
    assert connection.key_expires_on == TODAY + timedelta(days=200)
    assert connection.time_zone == g.TIME_ZONE
    (job,) = setup.jobs.jobs.values()
    assert job["task_name"] == "health:sync_connection"
    assert job["args"] == {"connection_id": str(connection.id), "trigger": "initial"}
    (exchange, profile) = setup.garmin.requests
    assert exchange.headers["authorization"] == f"ApiKey {g.KEY}"
    assert profile.url.path.endswith("/userprofile/settings")

    # Linking again takes the new expiry and reactivates the same connection.
    async with get_sessionmaker()() as session, session.begin():
        await session.execute(
            update(Connection)
            .where(Connection.id == connection.id)
            .values(status=ConnectionStatus.EXPIRED)
        )
    assert await setup.link(setup.home.owner, TODAY + timedelta(days=300)) == 0
    again = await connection_of(setup.home.owner)
    assert again.id == connection.id
    assert again.status is ConnectionStatus.ACTIVE
    assert again.key_expires_on == TODAY + timedelta(days=300)


async def test_link_refuses_bad_arguments(setup: Setup, capsys: pytest.CaptureFixture[str]) -> None:
    email = await email_of(setup.home.owner)
    assert await garmin_link(email, "../x", TODAY + timedelta(days=30)) == 1
    assert "file's name" in capsys.readouterr().err
    assert await garmin_link(email, "garmin", TODAY - timedelta(days=1)) == 1
    assert "after today" in capsys.readouterr().err
    assert await garmin_link("nobody@example.com", "garmin", TODAY + timedelta(days=9)) == 1
    assert "No household member" in capsys.readouterr().err
    assert await garmin_link(email, "missing", TODAY + timedelta(days=9)) == 1
    assert "Can't read the key file" in capsys.readouterr().err
    setup.garmin.key = "another-key"
    assert await setup.link(setup.home.owner) == 1
    assert "rejected the key" in capsys.readouterr().err
    assert setup.jobs.jobs == {}


async def test_first_sync_backfills_every_kind(setup: Setup) -> None:
    await linked(setup)

    outcome = await setup.sync(sync.SyncTrigger.INITIAL)

    assert outcome.succeeded and outcome.skipped == []
    assert await counts_of(setup.home.owner) == FULL
    assert await cursors_of(setup.home.owner) == dict.fromkeys(sync.SYNCED_KINDS, TODAY)
    # One call per window, and one per day for the night's detail.
    sleep_call = setup.garmin.calls("/dailySleepSummariesByDate")[0]
    assert sleep_call.url.params["startDate"] == START.isoformat()
    assert sleep_call.url.params["endDate"] == TODAY.isoformat()
    assert len(setup.garmin.calls("/hrv-service/hrv/2")) == 4
    assert len(setup.garmin.calls("/dailyHeartRate")) == 4
    async with get_sessionmaker()() as session:
        payloads = await session.execute(
            select(ProviderPayload.kind, func.count())
            .where(mine(ProviderPayload, setup.home.owner))
            .group_by(ProviderPayload.kind)
        )
        kinds = {kind: count for kind, count in payloads}
        run = await session.scalar(select(SyncRun).where(mine(SyncRun, setup.home.owner)))
        day = await session.get_one(DailySummary, (setup.home.owner.user_id, TODAY))
    assert kinds["heart_rate"] == 4 and kinds["daily_summaries"] == 1 and kinds["profile"] == 1
    assert run is not None and run.status is SyncStatus.SUCCEEDED
    assert run.payloads == sum(kinds.values())
    # The daily summary's values win over the stress and steps replies, which only fill.
    assert day.rest_stress_s == 36_000
    assert day.steps == 8000 + TODAY.toordinal() % 7
    assert day.body_battery_charged == 60


async def test_a_later_sync_starts_from_each_cursor_less_the_overlap(setup: Setup) -> None:
    await linked(setup)
    await setup.sync(sync.SyncTrigger.INITIAL)
    setup.garmin.requests.clear()

    outcome = await setup.sync()

    assert outcome.succeeded
    first = (TODAY - sync.OVERLAP).isoformat()
    assert setup.garmin.calls("/dailySleepSummariesByDate")[0].url.params["startDate"] == first
    assert len(setup.garmin.calls("/dailyHeartRate")) == sync.OVERLAP.days + 1
    assert await counts_of(setup.home.owner) == FULL  # read again, not doubled


async def test_a_failing_weight_call_is_skipped(setup: Setup) -> None:
    await linked(setup)
    setup.garmin.fail["weight"] = 400

    outcome = await setup.sync(sync.SyncTrigger.INITIAL)

    assert outcome.succeeded and outcome.skipped == ["weight"]
    counts = await counts_of(setup.home.owner)
    assert counts["weights"] == 0 and counts["sleeps"] == 4
    assert "weight" not in await cursors_of(setup.home.owner)
    async with get_sessionmaker()() as session:
        run = await session.scalar(select(SyncRun).where(mine(SyncRun, setup.home.owner)))
    assert run is not None and run.skipped == ["weight"] and run.status is SyncStatus.SUCCEEDED


async def test_a_rate_limit_ends_the_run_and_the_next_one_resumes(
    setup: Setup, monkeypatch: pytest.MonkeyPatch
) -> None:
    await linked(setup)
    setup.garmin.fail["spo2"] = 429
    monkeypatch.setattr(sync, "default_client", setup.connection_client)
    connection = await connection_of(setup.home.owner)

    await tasks.sync_connection(str(connection.id), "initial")

    cursors = await cursors_of(setup.home.owner)
    assert "spo2" not in cursors and cursors["daily_summaries"] == TODAY
    (retry,) = setup.jobs.jobs.values()  # tried again later
    assert retry["task_name"] == "health:sync_connection"
    assert retry["scheduled_at"] is not None
    async with get_sessionmaker()() as session:
        run = await session.scalar(select(SyncRun).where(mine(SyncRun, setup.home.owner)))
    assert run is not None and run.status is SyncStatus.FAILED
    assert run.error_code == "RATE_LIMITED"
    assert (await connection_of(setup.home.owner)).status is ConnectionStatus.ACTIVE

    del setup.garmin.fail["spo2"]
    setup.garmin.requests.clear()
    assert (await setup.sync()).succeeded
    assert len(setup.garmin.calls("/spo2acclimation/")) == 4  # from the start, no cursor yet
    assert await counts_of(setup.home.owner) == FULL


async def test_a_rejected_key_expires_the_connection(setup: Setup) -> None:
    await linked(setup)
    setup.garmin.key = "rotated"

    outcome = await setup.sync()

    assert not outcome.succeeded and outcome.error_code == "KEY_REJECTED"
    assert (await connection_of(setup.home.owner)).status is ConnectionStatus.EXPIRED
    assert (await setup.sync()).ran is False  # not synced until linked again
    async with api(setup.home.owner) as client:
        response = await client.post("/api/health/sync")
    assert response.status_code == 409


async def test_a_lapsed_key_expires_the_connection_without_a_call(setup: Setup) -> None:
    await linked(setup)
    connection = await connection_of(setup.home.owner)
    async with get_sessionmaker()() as session, session.begin():
        stored = await session.get_one(Connection, connection.id)
        stored.key_expires_on = TODAY - timedelta(days=1)
    setup.garmin.requests.clear()

    outcome = await setup.sync()

    assert outcome.error_code == "KEY_EXPIRED" and not outcome.ran
    assert setup.garmin.requests == []
    assert (await connection_of(setup.home.owner)).status is ConnectionStatus.EXPIRED


async def test_renormalize_rebuilds_the_same_rows(
    setup: Setup, capsys: pytest.CaptureFixture[str]
) -> None:
    await linked(setup)
    await setup.sync(sync.SyncTrigger.INITIAL)
    await setup.sync()  # a second reading of the last days, replayed in order too
    before = await _snapshot(setup.home.owner)
    async with get_sessionmaker()() as session, session.begin():
        await session.execute(delete(Sleep).where(mine(Sleep, setup.home.owner)))
        await session.execute(
            update(DailySummary).where(mine(DailySummary, setup.home.owner)).values(steps=1)
        )

    assert await garmin_renormalize(await email_of(setup.home.owner)) == 0

    assert await _snapshot(setup.home.owner) == before
    out = capsys.readouterr().out
    assert "replayed" in out and "sleeps: 4" in out


async def _snapshot(principal: Principal) -> dict[str, list[tuple[Any, ...]]]:
    result: dict[str, list[tuple[Any, ...]]] = {}
    async with get_sessionmaker()() as session:
        for model in FACT_TABLES:
            table = model.__table__
            keys = [column for column in table.c if column.primary_key]
            rows = await session.execute(
                select(table).where(mine(model, principal)).order_by(*keys)
            )
            result[model.__tablename__] = [tuple(row) for row in rows]
    return result


async def test_cli_sync_and_backfill_print_counts(
    setup: Setup, capsys: pytest.CaptureFixture[str]
) -> None:
    await linked(setup)
    email = await email_of(setup.home.owner)

    assert await garmin_sync(email, client_factory=setup.connection_client) == 0
    assert "synced" in capsys.readouterr().out
    setup.garmin.requests.clear()
    since = TODAY - timedelta(days=1)
    assert (
        await garmin_sync(
            email, since=since, kinds=["sleep"], client_factory=setup.connection_client
        )
        == 0
    )
    paths = {request.url.path.rsplit("/", 1)[-1] for request in setup.garmin.requests}
    assert paths == {"token", "settings", "v2", "dailySleepSummariesByDate"}
    assert "sleeps: 4" in capsys.readouterr().out
    assert await garmin_sync(await email_of(setup.home.member)) == 1  # nothing linked
    assert "No active Garmin connection" in capsys.readouterr().err


# The API, and what another member sees


async def test_the_connection_as_the_member_who_linked_it(setup: Setup) -> None:
    async with api(setup.home.owner) as client:
        assert (await client.get("/api/health/connection")).json() == {
            "linked": False,
            "provider": None,
            "status": None,
            "key_expires_on": None,
            "key_expires_soon": False,
            "last_synced_at": None,
            "last_run": None,
            "synced_through": {},
            "counts": {},
            "ranges": {},
            "syncing": False,
        }
    await linked(setup)
    await setup.sync(sync.SyncTrigger.INITIAL)

    async with api(setup.home.owner) as client:
        body = (await client.get("/api/health/connection")).json()
    assert body["linked"] and body["provider"] == "garmin" and body["status"] == "active"
    assert body["key_expires_on"] == (TODAY + timedelta(days=200)).isoformat()
    assert body["key_expires_soon"] is False
    assert body["last_synced_at"] is not None
    assert body["last_run"]["status"] == "succeeded" and body["last_run"]["skipped"] == []
    assert body["last_run"]["trigger"] == "initial"
    assert body["synced_through"] == dict.fromkeys(sync.SYNCED_KINDS, TODAY.isoformat())
    assert body["counts"] == FULL
    assert body["syncing"] is False
    assert set(body["ranges"]["sleeps"]) == {"first", "last"}
    assert "heart_rate_zones" not in body["ranges"]


async def test_a_key_lapsing_within_two_weeks_is_flagged(setup: Setup) -> None:
    assert await setup.link(setup.home.owner, TODAY + timedelta(days=14)) == 0
    async with api(setup.home.owner) as client:
        assert (await client.get("/api/health/connection")).json()["key_expires_soon"] is True


async def test_sync_now_queues_one_sync(setup: Setup) -> None:
    await linked(setup)
    connection = await connection_of(setup.home.owner)
    async with api(setup.home.owner) as client:
        first = await client.post("/api/health/sync")
        second = await client.post("/api/health/sync")

    assert first.status_code == 202 and first.json() == {"queued": True}
    assert second.json() == {"queued": False}  # one is already waiting
    (job,) = setup.jobs.jobs.values()
    assert job["args"] == {"connection_id": str(connection.id), "trigger": "user"}


async def test_another_member_of_the_household_sees_nothing(setup: Setup) -> None:
    await linked(setup)
    await setup.sync(sync.SyncTrigger.INITIAL)
    member = setup.home.member

    async with api(member) as client:
        connection = (await client.get("/api/health/connection")).json()
        sync_now = await client.post("/api/health/sync")
    assert connection["linked"] is False and connection["counts"] == {}
    assert sync_now.status_code == 404
    assert setup.jobs.jobs == {}

    async with get_sessionmaker()() as session:
        assert await own_connection(session, member) is None
        for model in (*FACT_TABLES, ProviderPayload, SyncRun, Connection):
            theirs = await session.scalar(select(func.count()).where(mine(model, member)))
            ours = await session.scalar(select(func.count()).where(mine(model, setup.home.owner)))
            assert theirs == 0, model.__tablename__
            assert ours, model.__tablename__
    assert await counts_of(member) == {
        name: 0 for name in FULL if "." not in name and name != "activity_files"
    }
    async with get_sessionmaker()() as session:
        files = await session.scalar(select(func.count()).where(mine(ActivityFile, member)))
    assert files == 0


async def test_the_member_links_their_own_watch_apart(setup: Setup) -> None:
    await linked(setup)
    await setup.sync(sync.SyncTrigger.INITIAL)
    assert await setup.link(setup.home.member) == 0
    member_connection = await connection_of(setup.home.member)
    owner_connection = await connection_of(setup.home.owner)
    assert member_connection.id != owner_connection.id

    async with api(setup.home.member) as client:
        body = (await client.get("/api/health/connection")).json()
    assert body["linked"] and body["last_run"] is None and body["synced_through"] == {}
    assert sum(body["counts"].values()) == 0


# Activities (H2)


async def test_the_first_sync_stores_each_activity_its_file_and_results(setup: Setup) -> None:
    await linked(setup)

    outcome = await setup.sync(sync.SyncTrigger.INITIAL)

    assert outcome.succeeded and outcome.skipped == []
    (search,) = setup.garmin.calls("/activities/search/activities")
    assert search.url.params["startDate"] == START.isoformat()
    assert search.url.params["limit"] == "100" and search.url.params["sortOrder"] == "asc"
    assert len(setup.garmin.calls("/activity-service/activity/")) == 2
    downloads = setup.garmin.calls("/download-service/files/activity/")
    assert len(downloads) == 2
    assert all(r.headers.get("accept") in (None, "*/*") for r in downloads)  # never JSON: 406

    owner = setup.home.owner.user_id
    async with get_sessionmaker()() as session:
        run = await session.get_one(Activity, (owner, RUN_ID))
        stream = await session.get_one(ActivityStream, (owner, RUN_ID))
        derived = await session.get_one(ActivityDerived, (owner, RUN_ID))
        swim = await session.get_one(ActivityDerived, (owner, SWIM_ID))
        file = await session.get_one(ActivityFile, (owner, RUN_ID))
        lengths = list(
            await session.scalars(
                select(ActivityLength)
                .where(mine(ActivityLength, setup.home.owner))
                .order_by(ActivityLength.length_index)
            )
        )
        file_data = await session.scalar(
            select(ActivityFile.data).where(ActivityFile.activity_id == RUN_ID)
        )
    assert run.sport == "running" and run.started_at == RUN_START
    assert run.avg_hr == 150  # the search's value, not the detail's
    assert run.time_zone == g.TIME_ZONE  # from the detail
    assert run.garmin_load is not None and float(run.garmin_load) == 61.5
    assert file.status == "stored" and file.attempts == 0 and file_data is not None
    assert file.size == len(file_data) and file_data.startswith(b"PK")
    assert len(stream.time_s) == 1500 and stream.heart_rate == [150] * 1500
    assert stream.cadence is not None and stream.cadence[0] == 171.0
    # Derived against the member's running zones (threshold 170, max 190).
    assert derived.hr_reference_source == "zones"
    assert (derived.hr_threshold, derived.hr_max) == (170, 190)
    rest = 48 + (TODAY - timedelta(days=1)).toordinal() % 7
    assert derived.hr_rest == rest
    reference = load.HeartRateReference(170, 190, rest, "zones")
    assert derived.hr_load == pytest.approx(load.hr_load([150.0] * 1500, reference), rel=1e-5)
    assert derived.moving_s == 1500
    assert derived.best_efforts == {"400": 133.3, "1000": 333.3, "1609": 536.3}
    assert derived.efficiency_factor == pytest.approx(180 / 150, rel=1e-5)
    assert derived.decoupling_pct == pytest.approx(0, abs=1e-4) and derived.steady
    assert derived.vo2max == pytest.approx(
        running.vo2_cost(180) / running.vo2max_share(150 / 190), rel=1e-4
    )
    assert derived.power_curve is not None and derived.power_curve[0] == 250
    assert [(n.active, n.swolf) for n in lengths] == [
        (True, 46),
        (False, None),
        (True, 43),
        (True, 44),
    ]
    assert swim.hr_load is None and swim.best_efforts is None


async def test_a_later_sync_fetches_only_new_activities(setup: Setup) -> None:
    await linked(setup)
    await setup.sync(sync.SyncTrigger.INITIAL)
    later = datetime.combine(TODAY, time(6), UTC)
    setup.garmin.activities.append(
        g.FakeActivity(
            7003,
            "running",
            later,
            300,
            900.0,
            fit.zipped(fit.activity_file(fit.Leg("running", later, 300))),
        )
    )
    setup.garmin.requests.clear()

    assert (await setup.sync()).succeeded

    search = setup.garmin.calls("/activities/search/activities")[0]
    assert search.url.params["startDate"] == (TODAY - sync.OVERLAP).isoformat()
    assert [r.url.path.rsplit("/", 1)[-1] for r in setup.garmin.calls("/download-service/")] == [
        "7003"
    ]
    counts = await counts_of(setup.home.owner)
    assert counts["activities"] == 3 and counts["activity_derived"] == 3


async def test_a_failing_activity_is_the_activitys_alone(setup: Setup) -> None:
    await linked(setup)
    setup.garmin.fail_files[RUN_ID] = 500

    outcome = await setup.sync(sync.SyncTrigger.INITIAL)

    assert outcome.succeeded and outcome.skipped == [sync.ACTIVITY_FILES]
    counts = await counts_of(setup.home.owner)
    assert counts["activities"] == 2 and counts["activity_derived"] == 1  # the swim
    assert (await cursors_of(setup.home.owner))["activities"] == TODAY
    owner = setup.home.owner.user_id
    async with get_sessionmaker()() as session:
        failed = await session.get_one(ActivityFile, (owner, RUN_ID))
    assert (failed.status, failed.attempts, failed.error_code) == ("failed", 1, "HTTP_500")

    # Later syncs try again, until the limit.
    for attempt in range(2, sync.MAX_FILE_ATTEMPTS + 1):
        await setup.sync()
        async with get_sessionmaker()() as session:
            assert (await session.get_one(ActivityFile, (owner, RUN_ID))).attempts == attempt
    setup.garmin.requests.clear()
    await setup.sync()
    assert setup.garmin.calls("/download-service/") == []  # left alone

    # A backfill doesn't reset it, but the row going away does (by hand).
    async with get_sessionmaker()() as session, session.begin():
        await session.execute(delete(ActivityFile).where(ActivityFile.activity_id == RUN_ID))
    del setup.garmin.fail_files[RUN_ID]
    assert (await setup.sync()).succeeded
    assert (await counts_of(setup.home.owner))["activity_derived"] == 2


async def test_a_file_that_does_not_parse_is_kept(setup: Setup) -> None:
    await linked(setup)
    run = setup.garmin.activity(RUN_ID)
    assert run is not None
    run.file = b"not a fit file"

    outcome = await setup.sync(sync.SyncTrigger.INITIAL)

    assert outcome.succeeded and outcome.skipped == [sync.ACTIVITY_FILES]
    async with get_sessionmaker()() as session:
        kept = await session.get_one(ActivityFile, (setup.home.owner.user_id, RUN_ID))
    assert (kept.status, kept.error_code) == ("stored", "PARSE_FAILED")
    counts = await counts_of(setup.home.owner)
    assert counts["activity_derived"] == 1 and counts["activity_files"] == 2


async def test_a_rate_limited_download_ends_the_run_and_the_next_resumes(setup: Setup) -> None:
    await linked(setup)
    setup.garmin.fail_files[RUN_ID] = 429

    outcome = await setup.sync(sync.SyncTrigger.INITIAL)

    assert not outcome.succeeded and outcome.error_code == "RATE_LIMITED"
    assert (await counts_of(setup.home.owner)).get("activity_files", 0) == 0
    del setup.garmin.fail_files[RUN_ID]
    assert (await setup.sync()).succeeded
    assert await counts_of(setup.home.owner) == FULL


async def test_a_triathlon_counts_its_legs_once(setup: Setup) -> None:
    """The parent has no file; one leg is listed, the other only named by the parent."""
    await linked(setup)
    start = datetime.combine(TODAY - timedelta(days=2), time(8), UTC)
    ride = fit.Leg("cycling", start, 900, speed=8.0, heart_rate=lambda _s: 140)
    leg_run = fit.Leg("running", start + timedelta(seconds=1000), 600, heart_rate=lambda _s: 160)
    file = fit.zipped(fit.activity_file(ride, leg_run))
    setup.garmin.activities = [
        g.FakeActivity(8000, "multi_sport", start, 1600, 9000.0, is_parent=True),
        g.FakeActivity(8001, "cycling", start, 900, 7200.0, file),
        g.FakeActivity(
            8002, "running", start + timedelta(seconds=1000), 600, 1800.0, file, listed=False
        ),
    ]
    setup.garmin.activities[0].child_ids = [8001, 8002]

    assert (await setup.sync(sync.SyncTrigger.INITIAL)).succeeded

    owner = setup.home.owner.user_id
    async with get_sessionmaker()() as session:
        rows = {
            a.activity_id: a
            for a in await session.scalars(select(Activity).where(mine(Activity, setup.home.owner)))
        }
        files = {
            f.activity_id: f.status
            for f in await session.scalars(
                select(ActivityFile).where(mine(ActivityFile, setup.home.owner))
            )
        }
        bike = await session.get(ActivityStream, (owner, 8001))
        run = await session.get(ActivityStream, (owner, 8002))
    assert set(rows) == {8000, 8001, 8002}
    assert files == {8000: "none", 8001: "stored", 8002: "stored"}
    assert bike is not None and run is not None
    assert rows[8000].is_parent and rows[8000].child_ids == [8001, 8002]
    assert rows[8001].parent_id == 8000 and rows[8002].parent_id == 8000
    assert rows[8002].sport == "running"  # made from its detail
    assert files == {8000: "none", 8001: "stored", 8002: "stored"}
    assert len(setup.garmin.calls("/download-service/")) == 2
    assert len(setup.garmin.calls("/activity-service/activity/")) == 3  # one detail each
    # Each leg keeps its own part of the shared file.
    assert len(bike.time_s) == 900 and bike.heart_rate == [140] * 900
    assert len(run.time_s) == 600 and run.heart_rate == [160] * 600


async def test_activity_pages(setup: Setup, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(garmin_client, "ACTIVITY_PAGE", 2)
    monkeypatch.setattr(sync, "ACTIVITY_PAGE", 2)
    await linked(setup)
    start = datetime.combine(TODAY - timedelta(days=1), time(9), UTC)
    setup.garmin.activities = [
        g.FakeActivity(6000 + n, "strength_training", start + timedelta(hours=n), 600, manual=True)
        for n in range(3)
    ]

    assert (await setup.sync(sync.SyncTrigger.INITIAL)).succeeded

    pages = setup.garmin.calls("/activities/search/activities")
    assert [r.url.params["start"] for r in pages] == ["0", "2"]
    counts = await counts_of(setup.home.owner)
    assert counts["activities"] == 3 and "activity_files" not in counts  # manual: no file
    assert setup.garmin.calls("/download-service/") == []


async def test_renormalize_parses_the_stored_files_again(
    setup: Setup, capsys: pytest.CaptureFixture[str]
) -> None:
    await linked(setup)
    await setup.sync(sync.SyncTrigger.INITIAL)
    before = await _snapshot(setup.home.owner)
    async with get_sessionmaker()() as session, session.begin():
        await session.execute(
            delete(ActivityDerived).where(mine(ActivityDerived, setup.home.owner))
        )
        await session.execute(delete(ActivityStream).where(mine(ActivityStream, setup.home.owner)))
    setup.garmin.requests.clear()

    assert await garmin_renormalize(await email_of(setup.home.owner)) == 0

    assert setup.garmin.requests == []
    assert await _snapshot(setup.home.owner) == before
    assert "parsed 2 activity files" in capsys.readouterr().out
