"""Finance's push alerts (M9 P6): bills due, budgets overspent, connections failing.

Each check looks at the hub as the member sees it (their principal, their accounts) and names
its alert with a key, so core/push.py sends it once. A check that finds nothing sends nothing.
"""

import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from hubnisio.core.auth import Principal, household_principals
from hubnisio.core.models import AlertKind
from hubnisio.core.push import Alert
from hubnisio.finance.budgets import budgets_for_month
from hubnisio.finance.models import (
    Connection,
    ConnectionStatus,
    SyncRun,
    SyncStatus,
    TransactionKind,
)
from hubnisio.finance.recurring_api import upcoming_payments

# A connection is failing once its last success is this old and its latest attempt failed.
FAILING_FOR = timedelta(days=1)


def money(amount: Decimal, currency: str) -> str:
    """As the app shows it (en-GB): €45.20, or 45.20 USD for other currencies."""
    value = f"{abs(amount):,.2f}"
    return f"€{value}" if currency == "EUR" else f"{value} {currency}"


async def bill_alerts(session: AsyncSession, principal: Principal, today: date) -> list[Alert]:
    """A confirmed bill due tomorrow, or today when yesterday's alert was missed."""
    alerts = []
    for payment in await upcoming_payments(session, principal, days=1, today=today):
        if payment.kind != TransactionKind.EXPENSE or payment.on > today + timedelta(days=1):
            continue
        when = "today" if payment.on <= today else "tomorrow"
        alerts.append(
            Alert(
                user_id=principal.user_id,
                kind=AlertKind.BILL_DUE,
                key=f"bill_due:{payment.series_id}:{payment.on.isoformat()}",
                title=f"Due {when}",
                body=f"{payment.name}, {money(payment.amount, payment.currency)}",
                url="/finance/recurring",
            )
        )
    return alerts


async def budget_alerts(session: AsyncSession, principal: Principal, today: date) -> list[Alert]:
    """A budget (or the one on all spending) over its limit this month, in the member's own
    view. Once per budget per month; the amounts stay in the app."""
    budgets = await budgets_for_month(session, principal, today, view="personal")
    month = budgets.month.isoformat()[:7]
    over: list[tuple[str, str]] = []
    if budgets.overall is not None and budgets.overall.remaining < 0:
        over.append(("overall", "All spending"))
    for budget in budgets.budgets:
        for item in (budget, *budget.children):
            if item.remaining < 0:
                over.append((str(item.category_id), item.name))
    return [
        Alert(
            user_id=principal.user_id,
            kind=AlertKind.BUDGET_OVER,
            key=f"budget_over:{key}:{month}",
            title="Over budget",
            body=f"{name} is over its budget this month.",
            url="/finance/budgets",
        )
        for key, name in over
    ]


async def connection_alerts(
    session: AsyncSession, user_id: uuid.UUID, now: datetime
) -> list[Alert]:
    """The member's own bank connections that need them: one that expired, or one whose syncs
    have failed for a day. Once per outage: the key carries the last success."""
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
        .where(
            Connection.user_id == user_id,
            Connection.status.in_([ConnectionStatus.ACTIVE, ConnectionStatus.EXPIRED]),
        )
    )
    alerts = []
    seen: set[uuid.UUID] = set()
    for connection, last_status in rows:
        if connection.id in seen:  # two accounts' runs started at the same moment
            continue
        seen.add(connection.id)
        name = connection.institution_name
        if connection.status == ConnectionStatus.EXPIRED:
            alerts.append(
                Alert(
                    user_id=user_id,
                    kind=AlertKind.SYNC_FAILING,
                    key=f"sync_failing:{connection.id}:expired",
                    title="Bank needs reconnecting",
                    body=f"{name}'s access ended. Link it again on the PC.",
                    url="/finance/connections",
                )
            )
            continue
        since = connection.last_synced_at or connection.created_at
        if last_status != SyncStatus.FAILED or now - since < FAILING_FOR:
            continue
        alerts.append(
            Alert(
                user_id=user_id,
                kind=AlertKind.SYNC_FAILING,
                key=f"sync_failing:{connection.id}:{since.astimezone(UTC).isoformat()}",
                title="Sync failing",
                body=f"{name} hasn't synced for a day.",
                url="/finance/connections",
            )
        )
    return alerts


async def finance_alerts(session: AsyncSession, now: datetime, today: date) -> list[Alert]:
    """Every member's finance alerts, as of `now` (and `today`, in the alerts' time zone)."""
    alerts: list[Alert] = []
    for principal in await household_principals(session):
        alerts += await bill_alerts(session, principal, today)
        alerts += await budget_alerts(session, principal, today)
        alerts += await connection_alerts(session, principal.user_id, now)
    return alerts
