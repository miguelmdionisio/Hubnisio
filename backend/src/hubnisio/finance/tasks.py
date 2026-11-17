"""Finance background jobs, registered on the shared job app in hubnisio/jobs.py."""

import logging
import uuid
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import procrastinate
from procrastinate.exceptions import AlreadyEnqueued
from procrastinate.types import JSONDict, TimeDeltaParams

from hubnisio.core import push
from hubnisio.core.db import get_sessionmaker
from hubnisio.core.settings import get_settings
from hubnisio.finance import sync
from hubnisio.finance.alerts import finance_alerts
from hubnisio.finance.fx.sources import FxClient
from hubnisio.finance.fx.store import refresh_rates
from hubnisio.finance.models import ProviderName
from hubnisio.finance.prices.sources import PriceClient
from hubnisio.finance.prices.store import refresh_prices

logger = logging.getLogger(__name__)

blueprint = procrastinate.Blueprint()

# On hitting a provider's rate limit, try again later.
RATE_LIMIT_RETRY: dict[ProviderName, TimeDeltaParams] = {
    # Banks allow about 4 unattended fetches a day.
    ProviderName.ENABLE_BANKING: {"hours": 6},
    # Trading 212's limits are per minute, and the client already waited for a few resets.
    ProviderName.TRADING212: {"minutes": 15},
}


@blueprint.task(name="sync_connection", queue="sync")
async def sync_connection(
    connection_id: str,
    trigger: str = sync.SyncTrigger.SCHEDULED,
    psu_headers: dict[str, str] | None = None,
) -> None:
    outcome = await sync.sync_connection(
        uuid.UUID(connection_id), trigger=sync.SyncTrigger(trigger), psu_headers=psu_headers
    )
    if outcome.rate_limited and outcome.provider is not None:
        await defer_sync(uuid.UUID(connection_id), schedule_in=RATE_LIMIT_RETRY[outcome.provider])


# Three runs a day stay under the banks' limit of 4 unattended fetches, leaving one spare.
# The cron runs in the worker's timezone (UTC in the container).
@blueprint.periodic(cron="0 7,13,19 * * *")
@blueprint.task(name="schedule_syncs", queue="sync")
async def schedule_syncs(timestamp: int) -> None:
    for connection_id in await sync.active_connection_ids():
        await defer_sync(connection_id)


# The schedules above only fire while the worker runs: a machine that was off or asleep at those
# hours misses them, and Procrastinate doesn't replay missed runs. Every half hour, sync what
# nothing has tried for 20 hours, so switching the machine on is enough to catch up.
CATCH_UP_AFTER = timedelta(hours=20)


@blueprint.periodic(cron="*/30 * * * *")
@blueprint.task(name="catch_up_syncs", queue="sync")
async def catch_up_syncs(timestamp: int) -> None:
    for connection_id in await sync.stale_connection_ids(CATCH_UP_AFTER):
        await defer_sync(connection_id)


# The ECB publishes its reference rates around 16:00 Central European Time, which is 14:00 to
# 15:00 UTC. The cron runs in the worker's timezone (UTC in the container).
@blueprint.periodic(cron="0 16 * * *")
@blueprint.task(name="fetch_fx_rates")
async def fetch_fx_rates(timestamp: int) -> None:
    """Fill in the rates missing since the last run. What was fetched is kept even if some
    currency failed; the failure then fails the job, and the next run fills the gap."""
    async with FxClient() as client, get_sessionmaker()() as session, session.begin():
        result = await refresh_rates(session, client)
    if result.failed:
        raise RuntimeError(
            "Exchange rates not fetched for " + ", ".join(sorted(result.failed)) + "."
        )


# After the day's closes in Europe (Xetra and Milan close by 16:30 UTC); the US closes of the
# day before are final too. Today's own close waits for the next run. The cron runs in the
# worker's timezone (UTC in the container).
@blueprint.periodic(cron="45 16 * * *")
@blueprint.task(name="fetch_prices")
async def fetch_prices(timestamp: int) -> None:
    """Fill in the instruments' closes missing since the last run (ADR-0008). What was fetched
    is kept even if some instrument failed; the failure then fails the job, and the next run
    fills the gap. An instrument without a symbol is only logged: it needs one by hand."""
    async with PriceClient() as client, get_sessionmaker()() as session, session.begin():
        result = await refresh_prices(session, client)
    for ticker in result.unmapped:
        logger.warning("No price symbol found for %s: set one with cli prices-symbol.", ticker)
    if result.failed:
        raise RuntimeError("Prices not fetched for " + ", ".join(sorted(result.failed)) + ".")


# Alerts (M9 P6): every half hour, like the catch-up, so a PC that was off sends what it
# missed. core/push.py sends each once, during the day, to members who want it.
@blueprint.periodic(cron="*/30 * * * *")
@blueprint.task(name="send_alerts")
async def send_alerts(timestamp: int) -> None:
    settings = get_settings()
    now = datetime.now(UTC)
    if not push.is_daytime(now, settings.alerts_time_zone):
        return
    async with get_sessionmaker()() as session:
        today = now.astimezone(ZoneInfo(settings.alerts_time_zone)).date()
        await push.deliver(session, await finance_alerts(session, now, today), now)


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
