"""Finance background jobs, registered on the shared job app in hubnisio/jobs.py."""

import uuid
from collections.abc import Mapping

import procrastinate
from procrastinate.exceptions import AlreadyEnqueued
from procrastinate.types import JSONDict, TimeDeltaParams

from hubnisio.finance import sync

blueprint = procrastinate.Blueprint()

# Banks allow about 4 unattended fetches a day; on hitting the limit, try again later.
RATE_LIMIT_RETRY: TimeDeltaParams = {"hours": 6}


@blueprint.task(name="sync_connection", queue="sync")
async def sync_connection(
    connection_id: str,
    trigger: str = sync.SyncTrigger.SCHEDULED,
    psu_headers: dict[str, str] | None = None,
) -> None:
    outcome = await sync.sync_connection(
        uuid.UUID(connection_id), trigger=sync.SyncTrigger(trigger), psu_headers=psu_headers
    )
    if outcome.rate_limited:
        await defer_sync(uuid.UUID(connection_id), schedule_in=RATE_LIMIT_RETRY)


# Three runs a day stay under the banks' limit of 4 unattended fetches, leaving one spare.
# The cron runs in the worker's timezone (UTC in the container).
@blueprint.periodic(cron="0 7,13,19 * * *")
@blueprint.task(name="schedule_syncs", queue="sync")
async def schedule_syncs(timestamp: int) -> None:
    for connection_id in await sync.active_connection_ids():
        await defer_sync(connection_id)


async def defer_sync(
    connection_id: uuid.UUID,
    *,
    trigger: sync.SyncTrigger = sync.SyncTrigger.SCHEDULED,
    psu_headers: Mapping[str, str] | None = None,
    schedule_in: TimeDeltaParams | None = None,
) -> bool:
    """Queue a sync of one connection, unless one is already waiting. One connection's syncs
    never run at the same time. Returns whether a sync was queued."""
    lock = f"finance.connection:{connection_id}"
    headers: JSONDict | None = dict(psu_headers) if psu_headers else None
    try:
        await sync_connection.configure(
            lock=lock, queueing_lock=lock, schedule_in=schedule_in
        ).defer_async(connection_id=str(connection_id), trigger=trigger, psu_headers=headers)
    except AlreadyEnqueued:
        return False
    return True
