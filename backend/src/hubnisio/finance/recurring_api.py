"""Recurring payments, found by detection (finance/recurring), and the upcoming ones.

A series belongs to one account and is scoped like it (finance/scoping.py). Only confirmed
series count in upcoming payments, and only on accounts that aren't hidden (ADR-0007).
"""

import uuid
from datetime import date, timedelta
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import Select, select

from hubnisio.core.auth import Principal
from hubnisio.finance import schemas
from hubnisio.finance.deps import CurrentPrincipal, DbSession
from hubnisio.finance.fx.convert import to_eur
from hubnisio.finance.insights.spending import cents
from hubnisio.finance.models import Account, RecurringSeries, RecurringStatus, Review
from hubnisio.finance.naming import account_name
from hubnisio.finance.recurring.detect import CADENCES, next_date, status_on
from hubnisio.finance.scoping import listed_account_ids, visible_account_ids

router = APIRouter(prefix="/finance", tags=["finance"])

_ORDER = {RecurringStatus.ACTIVE: 0, RecurringStatus.DORMANT: 1, RecurringStatus.CANCELLED: 2}


@router.get("/recurring", operation_id="listRecurring")
async def list_recurring(
    session: DbSession, principal: CurrentPrincipal, review: Review | None = None
) -> list[schemas.RecurringOut]:
    """Active first, then by next expected date."""
    query = _query(principal)
    if review is not None:
        query = query.where(RecurringSeries.review == review)
    today = date.today()
    found = [_out(series, account, today) for series, account in await session.execute(query)]
    found.sort(key=lambda s: (_ORDER[s.status], s.next_expected_on, s.name))
    return found


@router.patch("/recurring/{series_id}", operation_id="updateRecurring")
async def update_recurring(
    series_id: uuid.UUID,
    body: schemas.RecurringUpdate,
    session: DbSession,
    principal: CurrentPrincipal,
) -> schemas.RecurringOut:
    row = (await session.execute(_query(principal).where(RecurringSeries.id == series_id))).first()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such recurring payment.")
    series, account = row
    fields = body.model_fields_set
    today = date.today()
    if "review" in fields and body.review is not None:
        series.review = body.review
    if "name" in fields:
        series.custom_name = (body.name or "").strip() or None
    if "cancelled" in fields and body.cancelled is not None:
        series.cancelled_on = today if body.cancelled else None
    series.status = status_on(series.cadence, series.next_expected_on, today, series.cancelled_on)
    out = _out(series, account, today)
    await session.commit()
    return out


@router.get("/recurring/upcoming", operation_id="listUpcomingPayments")
async def list_upcoming(
    session: DbSession,
    principal: CurrentPrincipal,
    days: Annotated[int, Query(ge=1, le=366)] = 30,
) -> list[schemas.UpcomingPayment]:
    """Expected dates of active, confirmed series in the next `days` days, soonest first. A
    payment that's due but not late yet shows on its expected date. Euro amounts use today's
    rate."""
    today = date.today()
    end = today + timedelta(days=days)
    rows = await session.execute(
        _query(principal).where(
            RecurringSeries.review == Review.CONFIRMED,
            RecurringSeries.account_id.in_(listed_account_ids(principal)),
        )
    )
    upcoming: list[schemas.UpcomingPayment] = []
    for series, _ in rows:
        state = status_on(series.cadence, series.next_expected_on, today, series.cancelled_on)
        if state != RecurringStatus.ACTIVE:
            continue
        eur = await to_eur(session, series.expected_amount, series.currency, today)
        tolerance = timedelta(days=CADENCES[series.cadence].tolerance)
        periods, on = 0, series.next_expected_on
        while on <= end:
            if on >= today - tolerance:
                upcoming.append(
                    schemas.UpcomingPayment(
                        series_id=series.id,
                        name=series.custom_name or series.name,
                        on=on,
                        kind=series.kind,
                        amount=series.expected_amount,
                        currency=series.currency,
                        amount_eur=cents(eur) if eur is not None else None,
                    )
                )
            periods += 1
            on = next_date(series.next_expected_on, series.cadence, periods)
    upcoming.sort(key=lambda payment: (payment.on, payment.name))
    return upcoming


def _query(principal: Principal) -> Select[RecurringSeries, Account]:
    return (
        select(RecurringSeries, Account)
        .join(Account, Account.id == RecurringSeries.account_id)
        .where(
            RecurringSeries.household_id == principal.household_id,
            RecurringSeries.account_id.in_(visible_account_ids(principal)),
        )
    )


def _out(series: RecurringSeries, account: Account, today: date) -> schemas.RecurringOut:
    return schemas.RecurringOut(
        id=series.id,
        account_id=account.id,
        account_name=account_name(account),
        name=series.custom_name or series.name,
        counterparty_id=series.counterparty_id,
        cadence=series.cadence,
        kind=series.kind,
        expected_amount=series.expected_amount,
        currency=series.currency,
        amount_varies=series.amount_varies,
        occurrences=series.occurrences,
        first_seen_on=series.first_seen_on,
        last_seen_on=series.last_seen_on,
        next_expected_on=series.next_expected_on,
        previous_amount=series.previous_amount,
        amount_changed_on=series.amount_changed_on,
        status=status_on(series.cadence, series.next_expected_on, today, series.cancelled_on),
        review=series.review,
    )
