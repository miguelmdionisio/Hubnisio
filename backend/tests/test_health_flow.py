"""Health end to end against a fake Garmin (ADR-0009): linking, the first sync and later ones,
failures, renormalize, the API, and that a member sees only their own health data."""

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any

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
from hubnisio.health.models import (
    FACT_TABLES,
    Connection,
    ConnectionStatus,
    DailySummary,
    ProviderPayload,
    Sleep,
    SyncCursor,
    SyncRun,
    SyncStatus,
)
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
    garmin = g.FakeGarmin(weigh_ins=[TODAY - timedelta(days=1)], weight_goal_kg=68.0)
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


FULL = {
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
    assert await counts_of(member) == {name: 0 for name in FULL if "." not in name}


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
