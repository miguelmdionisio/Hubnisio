"""Web Push to the installed app on a member's phone (M9 P6, docs/design/m9-iphone.md).

The hub signs each push with its VAPID key (secrets/push, made by `cli push-keys`) and posts it,
encrypted for the device, to the device's push service (Apple's for an iPhone). Only the device
can read it. Pushes go out only while the PC and its worker run.

Alerts come from the domains (finance/alerts.py, health/alerts.py): each has a key, and
`deliver` sends it once per member, however often the checks run or catch up after the PC was
off, during the day only, and never a kind the member turned off.
"""

import asyncio
import base64
import json
import logging
import uuid
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from cryptography.hazmat.primitives import serialization
from py_vapid import Vapid02
from pywebpush import WebPushException, webpush
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from hubnisio.core.models import AlertKind, AlertPreference, AlertSent, PushSubscription
from hubnisio.core.settings import Settings, get_settings

logger = logging.getLogger(__name__)

VAPID_FILE = "vapid-private.pem"
# Alerts wait for the day: 08:00 to 22:00 in the alerts' time zone.
DAY_STARTS, DAY_ENDS = 8, 22
# How long the push service keeps trying a phone that's off.
TTL_SECONDS = 24 * 3600
# The push service's answers that mean the subscription is gone for good.
GONE = {404, 410}

ALERT_LABELS: dict[AlertKind, str] = {
    AlertKind.BILL_DUE: "A bill due tomorrow",
    AlertKind.BUDGET_OVER: "A budget overspent",
    AlertKind.SYNC_FAILING: "A sync failing for a day",
    AlertKind.KEY_LAPSING: "The Garmin key lapsing",
}


@dataclass(frozen=True, slots=True)
class Alert:
    """Something one member should hear about. `key` names it for sending once: the same
    bill on the same date, the same budget in the same month."""

    user_id: uuid.UUID
    kind: AlertKind
    key: str
    title: str
    body: str
    url: str


@dataclass(frozen=True, slots=True)
class Message:
    title: str
    body: str
    url: str = "/"
    tag: str | None = None  # a later push with the same tag replaces the earlier one


# --- Keys ---------------------------------------------------------------------------------


def vapid_key_path(settings: Settings | None = None) -> Path:
    return (settings or get_settings()).push_keys_dir / VAPID_FILE


def generate_vapid_key(path: Path) -> None:
    """Write a new VAPID private key (PEM). Never overwrites: a new key orphans every phone's
    subscription."""
    if path.exists():
        raise FileExistsError(f"{path} exists already.")
    path.parent.mkdir(parents=True, exist_ok=True)
    vapid = Vapid02()
    vapid.generate_keys()
    vapid.save_key(str(path))


def public_key(settings: Settings | None = None) -> str | None:
    """The VAPID public key as the browser wants it (base64url, uncompressed point), or None
    while there's no key."""
    path = vapid_key_path(settings)
    if not path.exists():
        return None
    key = Vapid02.from_file(str(path)).public_key
    if key is None:
        return None
    raw = key.public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
    )
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


# --- Sending ------------------------------------------------------------------------------

# pywebpush's blocking call; tests replace it.
Poster = Callable[..., Any]
_post: Poster = webpush


def _send_one(subscription: PushSubscription, payload: str, settings: Settings) -> int | None:
    """Post one push. Returns the push service's status when it refused, None when accepted."""
    try:
        _post(
            subscription_info={
                "endpoint": subscription.endpoint,
                "keys": {"p256dh": subscription.p256dh, "auth": subscription.auth},
            },
            data=payload,
            vapid_private_key=str(vapid_key_path(settings)),
            vapid_claims={"sub": settings.push_subject},  # pywebpush adds aud and exp to it
            ttl=TTL_SECONDS,
            timeout=15,
        )
    except WebPushException as error:
        status = error.response.status_code if error.response is not None else 0
        return status or 0
    return None


@dataclass(frozen=True, slots=True)
class SendResult:
    sent: int  # devices that took it
    failed: int  # refused or unreachable, kept for next time
    removed: int  # gone for good, deleted


async def send(session: AsyncSession, user_id: uuid.UUID, message: Message) -> SendResult:
    """Push one message to every device the member subscribed. A device the push service says
    is gone is forgotten. The caller commits."""
    settings = get_settings()
    subscriptions = list(
        await session.scalars(select(PushSubscription).where(PushSubscription.user_id == user_id))
    )
    if not subscriptions or not vapid_key_path(settings).exists():
        return SendResult(0, 0, 0)
    payload = json.dumps(
        {"title": message.title, "body": message.body, "url": message.url, "tag": message.tag}
    )
    sent = failed = removed = 0
    for subscription in subscriptions:
        refused = await asyncio.to_thread(_send_one, subscription, payload, settings)
        if refused is None:
            sent += 1
            subscription.last_sent_at = datetime.now(UTC)
        elif refused in GONE:
            removed += 1
            await session.delete(subscription)
        else:
            failed += 1
            logger.warning("A push was refused with status %s.", refused)
    return SendResult(sent, failed, removed)


def is_daytime(now: datetime, time_zone: str) -> bool:
    return DAY_STARTS <= now.astimezone(ZoneInfo(time_zone)).hour < DAY_ENDS


async def disabled_kinds(session: AsyncSession, user_id: uuid.UUID) -> set[AlertKind]:
    return set(
        await session.scalars(
            select(AlertPreference.kind).where(
                AlertPreference.user_id == user_id, AlertPreference.enabled.is_(False)
            )
        )
    )


async def deliver(session: AsyncSession, alerts: Iterable[Alert], now: datetime) -> int:
    """Send each alert not sent before, to members who want its kind, during the day. An alert
    is marked sent once a device took it; one that reached no device is tried again next run.
    Returns how many alerts went out. Commits as it goes, so a crash doesn't resend."""
    if not is_daytime(now, get_settings().alerts_time_zone):
        return 0
    delivered = 0
    for alert in alerts:
        if alert.kind in await disabled_kinds(session, alert.user_id):
            continue
        already = await session.get(AlertSent, (alert.user_id, alert.key))
        if already is not None:
            continue
        result = await send(
            session,
            alert.user_id,
            Message(title=alert.title, body=alert.body, url=alert.url, tag=alert.key),
        )
        if result.sent:
            session.add(AlertSent(user_id=alert.user_id, key=alert.key, kind=alert.kind))
            delivered += 1
        await session.commit()
    return delivered


async def forget_device(session: AsyncSession, user_id: uuid.UUID, endpoint: str) -> bool:
    deleted = await session.execute(
        delete(PushSubscription)
        .where(PushSubscription.user_id == user_id, PushSubscription.endpoint == endpoint)
        .returning(PushSubscription.id)
    )
    return deleted.first() is not None
