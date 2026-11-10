"""Bringing a member's Garmin data up to date (ADR-0009).

A sync reads, in order: the profile (for the member's time zone) and heart-rate zones; then
each day-range kind in windows no longer than its endpoint allows; then the kinds read one day
at a time (the night's HRV readings, the day's heart rate, SpO2); then fitness age and the
weight goal as of today.

Each kind starts a little before the last day it was synced through (`OVERLAP`, since today's
reply is partial and Garmin fills in last night later), or on `BACKFILL_START` the first time.
Every reply is stored in its own transaction before it's applied; a window that applies moves
its kind's cursor, so a sync cut short resumes where it stopped.

The weight calls, the weight goal and fitness age are `OPTIONAL`: their failure is logged and
recorded in the run's `skipped`, and the rest goes on. Any other failure ends the run.
"""

import enum
import logging
import uuid
from collections.abc import Callable, Collection
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from hubnisio.core.db import get_sessionmaker
from hubnisio.core.settings import get_settings
from hubnisio.health.ingest import apply
from hubnisio.health.models import (
    Connection,
    ConnectionStatus,
    ProviderPayload,
    SyncCursor,
    SyncRun,
    SyncStatus,
)
from hubnisio.health.providers.garmin.client import ENDPOINTS, Fetched, GarminClient, windows
from hubnisio.health.providers.garmin.errors import GarminError, KeyRejected, RateLimited
from hubnisio.health.providers.garmin.normalize import Records

logger = logging.getLogger(__name__)

BACKFILL_START = date(2025, 2, 1)  # the user's history starts in February 2025
OVERLAP = timedelta(days=2)
# Read over a range of days, in windows.
RANGE_KINDS = ("daily_summaries", "sleep", "hrv", "body_battery", "stress", "steps", "weight")
# Read one day per call: the night's detail and the day's heart rate.
DAY_KINDS = ("hrv_readings", "heart_rate", "spo2")
SYNCED_KINDS = (*RANGE_KINDS, *DAY_KINDS)
OPTIONAL = frozenset({"weight", "weight_goal", "fitness_age"})
APPLY_FAILED = "APPLY_FAILED"


class SyncTrigger(enum.StrEnum):
    INITIAL = "initial"  # right after linking
    SCHEDULED = "scheduled"
    USER = "user"  # "Sync now"
    BACKFILL = "backfill"  # cli garmin-backfill


@dataclass
class SyncOutcome:
    ran: bool = False
    succeeded: bool = False
    error_code: str | None = None
    payloads: int = 0
    skipped: list[str] = field(default_factory=list[str])

    @property
    def rate_limited(self) -> bool:
        return self.error_code == RateLimited.CODE


def default_client(connection: Connection) -> GarminClient:
    return GarminClient(get_settings().garmin_keys_dir / connection.key_file)


async def active_connection_ids() -> list[uuid.UUID]:
    async with get_sessionmaker()() as session:
        return list(
            await session.scalars(
                select(Connection.id).where(Connection.status == ConnectionStatus.ACTIVE)
            )
        )


def today_in(time_zone: str | None) -> date:
    """Today where the member is (UTC when their time zone is unknown)."""
    try:
        zone = ZoneInfo(time_zone) if time_zone else UTC
    except ZoneInfoNotFoundError, ValueError:
        zone = UTC
    return datetime.now(zone).date()


async def sync_connection(
    connection_id: uuid.UUID,
    *,
    trigger: SyncTrigger,
    since: date | None = None,
    kinds: Collection[str] | None = None,
    client_factory: Callable[[Connection], GarminClient] | None = None,
) -> SyncOutcome:
    """Sync one connection. `since` reads every kind from that day whatever its cursor
    (a backfill); `kinds` limits the day kinds read (profile and zones are always read)."""
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session, session.begin():
        connection = await session.get(Connection, connection_id)
        if connection is None or connection.status is not ConnectionStatus.ACTIVE:
            return SyncOutcome()
        if connection.key_expires_on is not None and connection.key_expires_on < today_in(
            connection.time_zone
        ):
            connection.status = ConnectionStatus.EXPIRED
            return SyncOutcome(ran=False, error_code="KEY_EXPIRED")
        run = SyncRun(
            connection_id=connection.id,
            user_id=connection.user_id,
            trigger=trigger,
            status=SyncStatus.RUNNING,
            started_at=datetime.now(UTC),
        )
        session.add(run)

    sync = _Sync(connection, run.id)
    error: Exception | None = None
    try:
        async with (client_factory or default_client)(connection) as client:
            await sync.run(client, since=since, kinds=kinds)
    except (GarminError, httpx.HTTPError) as exc:
        error = exc
    except Exception as exc:
        logger.exception("Unexpected error syncing health connection %s.", connection_id)
        error = exc

    outcome = SyncOutcome(
        ran=True, payloads=sync.payloads, skipped=sorted(sync.skipped), succeeded=error is None
    )
    if error is not None:
        outcome.error_code = _error_code(error)
    elif sync.apply_failed:
        outcome.succeeded = False
        outcome.error_code = APPLY_FAILED
    async with sessionmaker() as session, session.begin():
        run = await session.get_one(SyncRun, sync.run_id)
        run.status = SyncStatus.SUCCEEDED if outcome.succeeded else SyncStatus.FAILED
        run.error_code = outcome.error_code
        run.payloads = outcome.payloads
        run.skipped = outcome.skipped
        run.finished_at = datetime.now(UTC)
        stored = await session.get_one(Connection, connection_id)
        if sync.time_zone:
            stored.time_zone = sync.time_zone
        if outcome.succeeded:
            stored.last_synced_at = datetime.now(UTC)
        if isinstance(error, KeyRejected):
            stored.status = ConnectionStatus.EXPIRED
    logger.info(
        "Synced health connection %s: %s, %d replies, skipped %s.",
        connection_id,
        outcome.error_code or "ok",
        outcome.payloads,
        ", ".join(outcome.skipped) or "nothing",
    )
    return outcome


class _Sync:
    def __init__(self, connection: Connection, run_id: uuid.UUID) -> None:
        self.connection_id = connection.id
        self.user_id = connection.user_id
        self.time_zone = connection.time_zone
        self.run_id = run_id
        self.payloads = 0
        self.skipped: set[str] = set()
        self.apply_failed = False

    async def run(
        self, client: GarminClient, *, since: date | None, kinds: Collection[str] | None
    ) -> None:
        profile = await self._read(client, "profile", date.today())
        if profile is not None and profile.time_zone:
            self.time_zone = profile.time_zone
        today = today_in(self.time_zone)
        await self._read(client, "hr_zones", today)
        cursors = await self._cursors()
        for kind in SYNCED_KINDS:
            if kinds is not None and kind not in kinds:
                continue
            start = since or (cursors[kind] - OVERLAP if kind in cursors else BACKFILL_START)
            size = ENDPOINTS[kind].window or 1
            for first, last in windows(start, today, size):
                if not await self._window(client, kind, first, last):
                    break
        if kinds is None or "fitness_age" in kinds:
            await self._read(client, "fitness_age", today)
        if kinds is None or "weight_goal" in kinds:
            await self._read(client, "weight_goal", today - timedelta(days=363), today)

    async def _window(self, client: GarminClient, kind: str, first: date, last: date) -> bool:
        """Read and apply one window, then move the kind's cursor. False when the kind
        stops here (skipped, or its rows couldn't be applied)."""
        records = await self._read(client, kind, first, last)
        if records is None:
            return False
        async with get_sessionmaker()() as session, session.begin():
            await _advance(session, self.connection_id, kind, last)
        return True

    async def _read(
        self, client: GarminClient, kind: str, first: date, last: date | None = None
    ) -> Records | None:
        """Fetch, store and apply one reply. Returns its rows, or None when the kind is
        skipped or its rows couldn't be applied."""
        try:
            fetched = await client.fetch(kind, first, last)
        except KeyRejected, RateLimited:
            raise
        except (GarminError, httpx.HTTPError) as exc:
            if kind not in OPTIONAL:
                raise
            logger.warning("Skipped Garmin %s from %s: %s.", kind, first, _error_code(exc))
            self.skipped.add(kind)
            return None
        payload_id = await self._store(fetched)
        try:
            async with get_sessionmaker()() as session, session.begin():
                return await apply(session, self.user_id, kind, fetched.raw, fetched.day_from)
        except Exception:
            logger.exception("Applying Garmin %s reply %s failed.", kind, payload_id)
            self.apply_failed = True
            return None

    async def _store(self, fetched: Fetched) -> uuid.UUID:
        async with get_sessionmaker()() as session, session.begin():
            payload = ProviderPayload(
                user_id=self.user_id,
                connection_id=self.connection_id,
                sync_run_id=self.run_id,
                kind=fetched.kind,
                day_from=fetched.day_from,
                day_to=fetched.day_to,
                request=fetched.request,
                response=fetched.raw,
                fetched_at=datetime.now(UTC),
            )
            session.add(payload)
        self.payloads += 1
        return payload.id

    async def _cursors(self) -> dict[str, date]:
        async with get_sessionmaker()() as session:
            rows = await session.execute(
                select(SyncCursor.kind, SyncCursor.synced_through).where(
                    SyncCursor.connection_id == self.connection_id
                )
            )
            return {kind: day for kind, day in rows}


async def _advance(session: AsyncSession, connection_id: uuid.UUID, kind: str, day: date) -> None:
    """Move the kind's cursor to `day`, never back (a backfill reads old days again)."""
    statement = insert(SyncCursor).values(
        connection_id=connection_id, kind=kind, synced_through=day
    )
    await session.execute(
        statement.on_conflict_do_update(
            index_elements=["connection_id", "kind"],
            set_={
                "synced_through": func.greatest(
                    SyncCursor.synced_through, statement.excluded.synced_through
                ),
                "updated_at": datetime.now(UTC),
            },
        )
    )


def _error_code(error: Exception) -> str:
    match error:
        case GarminError(code=code):
            return code
        case httpx.HTTPError():
            return "NETWORK"
        case _:
            return "UNEXPECTED"
