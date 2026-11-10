"""Health HTTP endpoints: the member's Garmin connection and "Sync now" (ADR-0009).

Later slices add their routers beside this one (`sleep_api.py`, …) and list them in
`hubnisio.main.ROUTERS`. Every query goes through `health/scoping.py`: a member only ever sees
their own health data.
"""

from datetime import date, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from hubnisio.core.auth import Principal, get_principal
from hubnisio.core.db import get_session
from hubnisio.health import tasks
from hubnisio.health.ingest import fact_counts
from hubnisio.health.models import ConnectionStatus, SyncCursor, SyncRun, SyncStatus
from hubnisio.health.scoping import mine, own_connection
from hubnisio.health.sync import SyncTrigger, today_in

router = APIRouter(prefix="/health", tags=["health"])

DbSession = Annotated[AsyncSession, Depends(get_session)]
CurrentPrincipal = Annotated[Principal, Depends(get_principal)]

# The Garmin page warns from this long before the key lapses.
KEY_WARNING = timedelta(days=14)


class SyncRunOut(BaseModel):
    trigger: str
    status: SyncStatus
    error_code: str | None
    skipped: list[str]
    started_at: datetime
    finished_at: datetime | None


class HealthConnection(BaseModel):
    linked: bool
    provider: str | None = None
    status: ConnectionStatus | None = None
    key_expires_on: date | None = None
    # The key lapses within two weeks, or has lapsed.
    key_expires_soon: bool = False
    last_synced_at: datetime | None = None
    last_run: SyncRunOut | None = None
    # How far each kind is synced, and the rows stored per kind.
    synced_through: dict[str, date] = {}
    counts: dict[str, int] = {}


class SyncQueued(BaseModel):
    queued: bool


@router.get("/connection", operation_id="getHealthConnection")
async def get_connection(session: DbSession, principal: CurrentPrincipal) -> HealthConnection:
    connection = await own_connection(session, principal)
    if connection is None:
        return HealthConnection(linked=False)
    last_run = await session.scalar(
        select(SyncRun)
        .where(mine(SyncRun, principal), SyncRun.connection_id == connection.id)
        .order_by(SyncRun.started_at.desc(), SyncRun.id.desc())
        .limit(1)
    )
    cursors = await session.execute(
        select(SyncCursor.kind, SyncCursor.synced_through).where(
            SyncCursor.connection_id == connection.id
        )
    )
    expires = connection.key_expires_on
    return HealthConnection(
        linked=True,
        provider=connection.provider.value,
        status=connection.status,
        key_expires_on=expires,
        key_expires_soon=(
            expires is not None and expires - today_in(connection.time_zone) <= KEY_WARNING
        ),
        last_synced_at=connection.last_synced_at,
        last_run=(
            SyncRunOut(
                trigger=last_run.trigger,
                status=last_run.status,
                error_code=last_run.error_code,
                skipped=list(last_run.skipped),
                started_at=last_run.started_at,
                finished_at=last_run.finished_at,
            )
            if last_run is not None
            else None
        ),
        synced_through={kind: day for kind, day in cursors},
        counts=await fact_counts(session, principal.user_id),
    )


@router.post("/sync", status_code=status.HTTP_202_ACCEPTED, operation_id="syncHealth")
async def sync_now(session: DbSession, principal: CurrentPrincipal) -> SyncQueued:
    connection = await own_connection(session, principal)
    if connection is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No Garmin account is linked.")
    if connection.status is not ConnectionStatus.ACTIVE:
        raise HTTPException(status.HTTP_409_CONFLICT, "Link a new Garmin key first.")
    return SyncQueued(queued=await tasks.defer_sync(connection.id, trigger=SyncTrigger.USER))
