"""Notifications (M9 P6): the phone subscribes for pushes, the member picks which alerts they
want, and can send themselves a test. What the alerts are lives in core/push.py."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from hubnisio.core import push
from hubnisio.core.auth import Principal, get_principal
from hubnisio.core.db import get_session
from hubnisio.core.models import AlertKind, AlertPreference, PushSubscription

router = APIRouter(prefix="/push", tags=["core"])

DbSession = Annotated[AsyncSession, Depends(get_session)]
CurrentPrincipal = Annotated[Principal, Depends(get_principal)]


class AlertSetting(BaseModel):
    kind: AlertKind
    label: str
    enabled: bool


class PushSettings(BaseModel):
    # The key the phone subscribes with; None until `cli push-keys` has made one.
    public_key: str | None
    devices: int  # the member's subscribed devices
    alerts: list[AlertSetting]


class SubscriptionKeys(BaseModel):
    p256dh: str = Field(min_length=1, max_length=200)
    auth: str = Field(min_length=1, max_length=100)


class SubscriptionIn(BaseModel):
    """A browser's PushSubscription, as `subscription.toJSON()` gives it."""

    endpoint: str = Field(min_length=1, max_length=2000, pattern=r"^https://")
    keys: SubscriptionKeys


class Unsubscribe(BaseModel):
    endpoint: str = Field(min_length=1, max_length=2000)


class AlertSettingIn(BaseModel):
    enabled: bool


class TestResult(BaseModel):
    sent: int  # devices that took it


async def _settings(session: AsyncSession, principal: Principal) -> PushSettings:
    devices = await session.scalar(
        select(func.count())
        .select_from(PushSubscription)
        .where(PushSubscription.user_id == principal.user_id)
    )
    off = await push.disabled_kinds(session, principal.user_id)
    return PushSettings(
        public_key=push.public_key(),
        devices=devices or 0,
        alerts=[
            AlertSetting(kind=kind, label=push.ALERT_LABELS[kind], enabled=kind not in off)
            for kind in AlertKind
        ],
    )


@router.get("", operation_id="getPushSettings")
async def get_push_settings(session: DbSession, principal: CurrentPrincipal) -> PushSettings:
    """The push key, how many devices get alerts, and which alerts are on."""
    return await _settings(session, principal)


@router.put("/subscriptions", operation_id="subscribePush", status_code=status.HTTP_204_NO_CONTENT)
async def subscribe(
    body: SubscriptionIn, session: DbSession, principal: CurrentPrincipal
) -> Response:
    """Remember this device for the member's alerts (again, if its keys changed)."""
    statement = insert(PushSubscription).values(
        user_id=principal.user_id,
        endpoint=body.endpoint,
        p256dh=body.keys.p256dh,
        auth=body.keys.auth,
    )
    await session.execute(
        statement.on_conflict_do_update(
            index_elements=[PushSubscription.endpoint],
            set_={
                "user_id": statement.excluded.user_id,
                "p256dh": statement.excluded.p256dh,
                "auth": statement.excluded.auth,
            },
        )
    )
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/subscriptions/remove",
    operation_id="unsubscribePush",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def unsubscribe(
    body: Unsubscribe, session: DbSession, principal: CurrentPrincipal
) -> Response:
    """Forget this device: it gets no more alerts."""
    await push.forget_device(session, principal.user_id, body.endpoint)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.put("/alerts/{kind}", operation_id="setAlert")
async def set_alert(
    kind: AlertKind, body: AlertSettingIn, session: DbSession, principal: CurrentPrincipal
) -> PushSettings:
    """Turn one kind of alert on or off for the member."""
    statement = insert(AlertPreference).values(
        user_id=principal.user_id, kind=kind, enabled=body.enabled
    )
    await session.execute(
        statement.on_conflict_do_update(
            index_elements=[AlertPreference.user_id, AlertPreference.kind],
            set_={"enabled": statement.excluded.enabled},
        )
    )
    await session.commit()
    return await _settings(session, principal)


@router.post("/test", operation_id="sendTestPush")
async def send_test(session: DbSession, principal: CurrentPrincipal) -> TestResult:
    """Send a test notification to the member's devices now, whatever the hour."""
    if push.public_key() is None:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "No push key yet: run `python -m hubnisio.cli push-keys`."
        )
    result = await push.send(
        session,
        principal.user_id,
        push.Message(
            title="Hubnisio",
            body="Notifications work on this device.",
            url="/settings/notifications",
            tag="test",
        ),
    )
    await session.commit()
    return TestResult(sent=result.sent)
