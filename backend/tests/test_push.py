"""Push alerts (M9 P6): subscribing, choosing alerts, sending once, and the alert rules."""

import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from households import Home, add, api, refresh
from pywebpush import WebPushException
from sqlalchemy import func, select

from hubnisio.core import push
from hubnisio.core.db import get_sessionmaker
from hubnisio.core.models import AlertKind, AlertSent, PushSubscription
from hubnisio.core.settings import get_settings
from hubnisio.finance import alerts as finance_alerts
from hubnisio.finance import schemas
from hubnisio.finance.models import (
    Connection,
    ConnectionStatus,
    ProviderName,
    SyncRun,
    SyncStatus,
    TransactionKind,
)
from hubnisio.health import alerts as health_alerts
from hubnisio.health import models as health

NOON = datetime(2026, 10, 15, 12, 0, tzinfo=UTC)  # 13:00 in Lisbon
NIGHT = datetime(2026, 10, 15, 2, 0, tzinfo=UTC)


class FakePushService:
    """Stands in for pywebpush: records each push, and refuses with `status` when set."""

    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []
        self.status: int | None = None

    def __call__(self, **kwargs: Any) -> None:
        if self.status is not None:
            response = type("Response", (), {"status_code": self.status})()
            raise WebPushException("refused", response=response)
        self.sent.append(kwargs)


@pytest.fixture
def service(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> FakePushService:
    """A push key of the test's own (never the real one) and a fake push service."""
    monkeypatch.setattr(get_settings(), "push_keys_dir", tmp_path)
    push.generate_vapid_key(push.vapid_key_path())
    fake = FakePushService()
    monkeypatch.setattr(push, "_post", fake)
    return fake


def device(n: int = 1) -> dict[str, Any]:
    return {
        "endpoint": f"https://web.push.apple.com/{uuid.uuid4().hex}-{n}",
        "keys": {"p256dh": "BPublicKeyOfTheDevice", "auth": "authsecret"},
    }


@pytest.mark.anyio
async def test_settings_subscribe_and_choose_alerts(home: Home, service: FakePushService) -> None:
    phone = device()
    async with api(home.owner) as client:
        settings = (await client.get("/api/push")).json()
        assert settings["public_key"] and len(settings["public_key"]) == 87  # 65 bytes, base64url
        assert settings["devices"] == 0
        assert {a["kind"]: a["enabled"] for a in settings["alerts"]} == {
            "bill_due": True,
            "budget_over": True,
            "sync_failing": True,
            "key_lapsing": True,
        }

        assert (await client.put("/api/push/subscriptions", json=phone)).status_code == 204
        # Again, with new keys: still one device.
        phone["keys"]["auth"] = "newsecret"
        assert (await client.put("/api/push/subscriptions", json=phone)).status_code == 204
        assert (await client.get("/api/push")).json()["devices"] == 1

        off = await client.put("/api/push/alerts/budget_over", json={"enabled": False})
        assert {a["kind"]: a["enabled"] for a in off.json()["alerts"]}["budget_over"] is False

        test = await client.post("/api/push/test")
        assert test.json() == {"sent": 1}
        assert service.sent[0]["subscription_info"]["keys"]["auth"] == "newsecret"
        assert '"title": "Hubnisio"' in service.sent[0]["data"]

        removed = await client.post("/api/push/subscriptions/remove", json=phone)
        assert removed.status_code == 204
        assert (await client.get("/api/push")).json()["devices"] == 0

    # The other member has their own devices and choices.
    async with api(home.member) as client:
        settings = (await client.get("/api/push")).json()
        assert settings["devices"] == 0
        assert all(alert["enabled"] for alert in settings["alerts"])


@pytest.mark.anyio
async def test_a_subscription_must_be_https(home: Home) -> None:
    async with api(home.owner) as client:
        bad = device()
        bad["endpoint"] = "http://example.com/push"
        assert (await client.put("/api/push/subscriptions", json=bad)).status_code == 422


@pytest.mark.anyio
async def test_alerts_go_once_by_day_and_only_when_wanted(
    home: Home, service: FakePushService
) -> None:
    async with api(home.owner) as client:
        await client.put("/api/push/subscriptions", json=device())
        await client.put("/api/push/alerts/key_lapsing", json={"enabled": False})
    user = home.owner.user_id
    bill = push.Alert(user, AlertKind.BILL_DUE, f"bill_due:{uuid.uuid4()}", "Due", "Rent", "/")
    key = push.Alert(user, AlertKind.KEY_LAPSING, f"key:{uuid.uuid4()}", "Key", "Soon", "/")

    async with get_sessionmaker()() as session:
        assert await push.deliver(session, [bill, key], NIGHT) == 0  # waits for the day
        assert await push.deliver(session, [bill, key], NOON) == 1  # the key alert is off
        assert await push.deliver(session, [bill, key], NOON) == 0  # sent already
    assert len(service.sent) == 1

    # Refused for now (not gone): not marked sent, so the next run tries again.
    service.status = 503
    again = push.Alert(user, AlertKind.BILL_DUE, f"bill_due:{uuid.uuid4()}", "Due", "Gas", "/")
    async with get_sessionmaker()() as session:
        assert await push.deliver(session, [again], NOON) == 0
        assert await session.get(AlertSent, (user, again.key)) is None
    # Gone for good: the device is forgotten.
    service.status = 410
    async with get_sessionmaker()() as session:
        assert await push.deliver(session, [again], NOON) == 0
        devices = await session.scalar(
            select(func.count())
            .select_from(PushSubscription)
            .where(PushSubscription.user_id == user)
        )
        assert devices == 0


@pytest.mark.anyio
async def test_bill_alerts_for_tomorrow_and_a_missed_today(
    home: Home, monkeypatch: pytest.MonkeyPatch
) -> None:
    today = date(2026, 10, 15)

    def payment(name: str, on: date, kind: TransactionKind) -> schemas.UpcomingPayment:
        return schemas.UpcomingPayment(
            series_id=uuid.uuid4(),
            name=name,
            on=on,
            kind=kind,
            amount=Decimal("-45.2"),
            currency="EUR",
            amount_eur=Decimal("-45.2"),
        )

    async def upcoming(*_: Any, **__: Any) -> list[schemas.UpcomingPayment]:
        return [
            payment("Rent", today, TransactionKind.EXPENSE),
            payment("Electricity", today + timedelta(days=1), TransactionKind.EXPENSE),
            payment("Salary", today + timedelta(days=1), TransactionKind.INCOME),
        ]

    monkeypatch.setattr(finance_alerts, "upcoming_payments", upcoming)
    async with get_sessionmaker()() as session:
        alerts = await finance_alerts.bill_alerts(session, home.owner, today)
    assert [(a.title, a.body) for a in alerts] == [
        ("Due today", "Rent, €45.20"),
        ("Due tomorrow", "Electricity, €45.20"),
    ]
    assert alerts[1].key.endswith(":2026-10-16")


@pytest.mark.anyio
async def test_budget_alerts_name_what_is_over(home: Home) -> None:
    groceries = await add(home, "-130.00", 3)
    await refresh(home)
    c = home.categories
    async with api(home.owner) as client:
        await client.patch(
            f"/api/finance/transactions/{groceries}", json={"category_id": str(c["Groceries"])}
        )
        await client.put(
            f"/api/finance/budgets/{c['Groceries']}",
            json={"amount": "100", "from_month": "2026-10-01"},
        )
        await client.put(
            f"/api/finance/budgets/{c['Fuel']}", json={"amount": "50", "from_month": "2026-10-01"}
        )
    async with get_sessionmaker()() as session:
        alerts = await finance_alerts.budget_alerts(session, home.owner, date(2026, 10, 20))
    assert [(a.body, a.key) for a in alerts] == [
        ("Groceries is over its budget this month.", f"budget_over:{c['Groceries']}:2026-10")
    ]


@pytest.mark.anyio
async def test_connection_alerts_after_a_day_of_failures(home: Home) -> None:
    user = home.owner.user_id
    async with get_sessionmaker()() as session, session.begin():

        def bank(name: str, status: ConnectionStatus, last: datetime | None) -> Connection:
            connection = Connection(
                household_id=home.owner.household_id,
                user_id=user,
                provider=ProviderName.ENABLE_BANKING,
                institution_name=name,
                status=status,
                last_synced_at=last,
            )
            session.add(connection)
            return connection

        failing = bank("Failing Bank", ConnectionStatus.ACTIVE, NOON - timedelta(days=2))
        recent = bank("Blip Bank", ConnectionStatus.ACTIVE, NOON - timedelta(hours=5))
        expired = bank("Old Bank", ConnectionStatus.EXPIRED, NOON - timedelta(days=90))
        await session.flush()
        for connection in (failing, recent):
            session.add(
                SyncRun(
                    household_id=home.owner.household_id,
                    connection_id=connection.id,
                    account_id=home.shared,
                    trigger="scheduled",
                    strategy="default",
                    status=SyncStatus.FAILED,
                    started_at=NOON - timedelta(hours=1),
                )
            )
    async with get_sessionmaker()() as session:
        alerts = await finance_alerts.connection_alerts(session, user, NOON)
    bodies = sorted(a.body for a in alerts)
    assert bodies == [
        "Failing Bank hasn't synced for a day.",
        "Old Bank's access ended. Link it again on the PC.",
    ]
    assert {a.key for a in alerts} >= {f"sync_failing:{expired.id}:expired"}
    # The other member doesn't hear about the owner's connections.
    async with get_sessionmaker()() as session:
        assert await finance_alerts.connection_alerts(session, home.member.user_id, NOON) == []


@pytest.mark.anyio
async def test_garmin_key_alert_from_two_weeks_out(home: Home) -> None:
    user = home.member.user_id
    soon = date.today() + timedelta(days=10)
    async with get_sessionmaker()() as session, session.begin():
        session.add(
            health.Connection(
                user_id=user,
                provider=health.ProviderName.GARMIN,
                status=health.ConnectionStatus.ACTIVE,
                key_file="garmin-test",
                key_expires_on=soon,
                time_zone="Europe/Lisbon",
                last_synced_at=datetime.now(UTC),
            )
        )
    async with get_sessionmaker()() as session:
        mine = [
            a
            for a in await health_alerts.health_alerts(session, datetime.now(UTC))
            if a.user_id == user
        ]
    assert [(a.kind, a.title) for a in mine] == [(AlertKind.KEY_LAPSING, "Garmin key lapses soon")]
    assert mine[0].key.endswith(soon.isoformat())
