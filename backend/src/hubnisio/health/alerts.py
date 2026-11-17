"""Health's push alerts (M9 P6): the Garmin key lapsing, and Garmin syncs failing.

Only about the member's own connection: health data belongs to one member. Each alert has a key,
so core/push.py sends it once.
"""

from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from hubnisio.core.models import AlertKind
from hubnisio.core.push import Alert
from hubnisio.health.models import Connection, ConnectionStatus, SyncRun, SyncStatus
from hubnisio.health.sync import today_in

# The Garmin page warns this long before the key lapses; the alert comes with it.
KEY_WARNING = timedelta(days=14)
# A connection is failing once its last success is this old and its latest attempt failed.
FAILING_FOR = timedelta(days=1)


async def health_alerts(session: AsyncSession, now: datetime) -> list[Alert]:
    last_run = (
        select(SyncRun.connection_id, func.max(SyncRun.started_at).label("at"))
        .group_by(SyncRun.connection_id)
        .subquery()
    )
    rows = await session.execute(
        select(Connection, SyncRun.status)
        .outerjoin(last_run, last_run.c.connection_id == Connection.id)
        .outerjoin(
            SyncRun,
            (SyncRun.connection_id == Connection.id) & (SyncRun.started_at == last_run.c.at),
        )
    )
    alerts: list[Alert] = []
    for connection, last_status in rows:
        expires = connection.key_expires_on
        if expires is not None and expires - today_in(connection.time_zone) <= KEY_WARNING:
            lapsed = connection.status == ConnectionStatus.EXPIRED or expires <= today_in(
                connection.time_zone
            )
            alerts.append(
                Alert(
                    user_id=connection.user_id,
                    kind=AlertKind.KEY_LAPSING,
                    key=f"key_lapsing:{connection.id}:{expires.isoformat()}",
                    title="Garmin key lapsed" if lapsed else "Garmin key lapses soon",
                    body=(
                        "Make a new key and link it on the PC."
                        if lapsed
                        else f"It lapses on {expires.day} {expires:%B}. Make a new one in time."
                    ),
                    url="/health/garmin",
                )
            )
        if connection.status != ConnectionStatus.ACTIVE:
            continue
        since = connection.last_synced_at or connection.created_at
        if last_status != SyncStatus.FAILED or now - since < FAILING_FOR:
            continue
        alerts.append(
            Alert(
                user_id=connection.user_id,
                kind=AlertKind.SYNC_FAILING,
                key=f"sync_failing:{connection.id}:{since.astimezone(UTC).isoformat()}",
                title="Sync failing",
                body="Garmin hasn't synced for a day.",
                url="/health/garmin",
            )
        )
    return alerts
