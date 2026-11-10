"""Health background jobs, registered on the shared job app in hubnisio/jobs.py."""

import uuid

import procrastinate
from procrastinate.exceptions import AlreadyEnqueued
from procrastinate.types import TimeDeltaParams

from hubnisio.health import sync

blueprint = procrastinate.Blueprint()

# Garmin publishes no limits; the client already backed off a few times. Try again later.
RATE_LIMIT_RETRY: TimeDeltaParams = {"hours": 1}


@blueprint.task(name="sync_connection", queue="sync")
async def sync_connection(connection_id: str, trigger: str = sync.SyncTrigger.SCHEDULED) -> None:
    outcome = await sync.sync_connection(
        uuid.UUID(connection_id), trigger=sync.SyncTrigger(trigger)
    )
    if outcome.rate_limited:
        await defer_sync(uuid.UUID(connection_id), schedule_in=RATE_LIMIT_RETRY)


# Once a day, in the morning, when last night's sleep has usually reached Garmin. The cron runs
# in the worker's timezone (UTC in the container).
@blueprint.periodic(cron="0 9 * * *")
@blueprint.task(name="schedule_syncs", queue="sync")
async def schedule_syncs(timestamp: int) -> None:
    for connection_id in await sync.active_connection_ids():
        await defer_sync(connection_id)


async def defer_sync(
    connection_id: uuid.UUID,
    *,
    trigger: sync.SyncTrigger = sync.SyncTrigger.SCHEDULED,
    schedule_in: TimeDeltaParams | None = None,
) -> bool:
    """Queue a sync of one connection, unless one is already waiting. One connection's syncs
    never run at the same time. Returns whether a sync was queued."""
    lock = f"health.connection:{connection_id}"
    try:
        await sync_connection.configure(
            lock=lock, queueing_lock=lock, schedule_in=schedule_in
        ).defer_async(connection_id=str(connection_id), trigger=trigger)
    except AlreadyEnqueued:
        return False
    return True
