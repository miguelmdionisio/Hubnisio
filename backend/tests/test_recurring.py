"""Recurring payments: detection on its own, then through the database and the API."""

import uuid
from datetime import date, timedelta
from decimal import Decimal

import pytest
from households import Home, add, api, refresh

from hubnisio.finance.insights.spending import add_months
from hubnisio.finance.models import Cadence, RecurringStatus, TransactionKind
from hubnisio.finance.recurring.detect import Payment, detect, status_on

MERCHANTS: dict[str, uuid.UUID] = {}


def pay(
    on: date, amount: str, merchant: str | None = None, description: str | None = None
) -> Payment:
    merchant_id = MERCHANTS.setdefault(merchant, uuid.uuid4()) if merchant else None
    return Payment(uuid.uuid4(), on, Decimal(amount), "EUR", merchant_id, merchant, description)


def monthly(start: date, amounts: list[str], **kwargs: str) -> list[Payment]:
    return [pay(_same_day(start, i), amount, **kwargs) for i, amount in enumerate(amounts)]


def _same_day(start: date, months: int) -> date:
    return add_months(start, months).replace(day=start.day)


JAN = date(2026, 1, 15)


def test_a_monthly_subscription() -> None:
    [found] = detect(monthly(JAN, ["-9.99"] * 6, merchant="Netflix"))
    assert (found.cadence, found.kind, found.name) == (
        Cadence.MONTHLY,
        TransactionKind.EXPENSE,
        "Netflix",
    )
    assert (found.expected_amount, found.next_expected_on) == (Decimal("-9.99"), date(2026, 7, 15))
    assert (found.previous_amount, found.amount_varies, len(found.members)) == (None, False, 6)


def test_a_price_rise_stays_one_series() -> None:
    [found] = detect(monthly(JAN, ["-7.99"] * 3 + ["-9.99"] * 3, merchant="Netflix"))
    assert found.expected_amount == Decimal("-9.99")
    assert (found.previous_amount, found.amount_changed_on) == (Decimal("-7.99"), date(2026, 4, 15))


def test_yearly_and_weekly() -> None:
    yearly = [
        pay(date(2023, 3, 1), "-49"),
        pay(date(2024, 3, 2), "-49"),
        pay(date(2025, 2, 27), "-49"),
    ]
    weekly = [pay(date(2026, 1, 5) + timedelta(weeks=i), "-5.50") for i in range(8)]
    for payments, cadence in ((yearly, Cadence.YEARLY), (weekly, Cadence.WEEKLY)):
        payments = [
            Payment(p.id, p.on, p.amount, "EUR", None, None, "Domain renewal") for p in payments
        ]
        [found] = detect(payments)
        assert found.cadence == cadence


def test_two_subscriptions_from_one_merchant() -> None:
    found = detect(
        monthly(JAN, ["-0.99"] * 4, merchant="Apple")
        + monthly(JAN, ["-9.99"] * 4, merchant="Apple")
    )
    assert sorted(f.expected_amount for f in found) == [Decimal("-9.99"), Decimal("-0.99")]


def test_frequent_shopping_is_not_recurring() -> None:
    amounts = ["-25.00", "-30.00", "-28.00"]
    shopping = [
        pay(JAN + timedelta(days=3 * i), amounts[i % 3], merchant="Pingo Doce") for i in range(40)
    ]
    assert detect(shopping) == []


def test_a_missed_month_and_a_payment_every_other_month() -> None:
    once = [pay(_same_day(JAN, i), "-15") for i in (0, 1, 3, 4)]
    once = [Payment(p.id, p.on, p.amount, "EUR", None, None, "DD MEO 123") for p in once]
    [found] = detect(once)
    assert len(found.members) == 4
    bimonthly = [pay(_same_day(JAN, i), "-15", merchant="Insurer") for i in (0, 2, 4, 6)]
    assert detect(bimonthly) == []


def test_bpi_descriptions_without_merchants() -> None:
    payments = [
        pay(_same_day(JAN, i), "-35.00", description=f"DD SOLINCA {1000 + i} {i + 1:02d}/01")
        for i in range(4)
    ]
    [found] = detect(payments)
    assert (found.name, found.match_key) == ("Dd solinca", "text:dd solinca")


def test_varying_amounts_and_income() -> None:
    utility = monthly(JAN, ["-40", "-70", "-45", "-85", "-50"], merchant="EDP")
    salary = monthly(JAN.replace(day=25), ["1500"] * 4, merchant="Employer")
    found = {f.name: f for f in detect(utility + salary)}
    assert (found["EDP"].amount_varies, found["EDP"].expected_amount) == (True, Decimal(-50))
    assert found["Employer"].kind == TransactionKind.INCOME


def test_status() -> None:
    due = date(2026, 3, 15)
    assert status_on(Cadence.MONTHLY, due, date(2026, 3, 19)) == RecurringStatus.ACTIVE
    assert status_on(Cadence.MONTHLY, due, date(2026, 3, 25)) == RecurringStatus.DORMANT
    assert status_on(Cadence.MONTHLY, due, date(2026, 5, 20)) == RecurringStatus.CANCELLED
    assert status_on(Cadence.MONTHLY, due, date(2026, 3, 1), due) == RecurringStatus.CANCELLED


@pytest.mark.anyio
async def test_review_survives_detection(home: Home) -> None:
    today = date.today()
    for months in (3, 2, 1):
        on = add_months(today, -months).replace(day=min(today.day, 28))
        await add(home, "-9.99", 0, on=on, counterparty="NETFLIX.COM")
        await add(home, "-5.99", 0, on=on, counterparty="SPOTIFY")
        await add(home, "-20.00", 0, on=on, counterparty="GYM", account=home.private)
    await refresh(home)

    async with api(home.owner) as client:
        listed = (await client.get("/api/finance/recurring")).json()
        by_name = {s["name"]: s for s in listed}
        assert set(by_name) == {"NETFLIX.COM", "SPOTIFY", "GYM"}
        assert {s["review"] for s in listed} == {"suggested"}
        assert by_name["SPOTIFY"]["status"] == "active"

        netflix, spotify = by_name["NETFLIX.COM"]["id"], by_name["SPOTIFY"]["id"]
        await client.patch(f"/api/finance/recurring/{netflix}", json={"review": "dismissed"})
        renamed = await client.patch(
            f"/api/finance/recurring/{spotify}", json={"review": "confirmed", "name": "Music"}
        )
        assert renamed.json()["name"] == "Music"

    await refresh(home)  # detection again: the user's choices stay
    async with api(home.owner) as client:
        suggested = (
            await client.get("/api/finance/recurring", params={"review": "suggested"})
        ).json()
        assert [s["name"] for s in suggested] == ["GYM"]
        confirmed = (
            await client.get("/api/finance/recurring", params={"review": "confirmed"})
        ).json()
        assert [(s["name"], s["occurrences"]) for s in confirmed] == [("Music", 3)]

        # 20 days: with 5 days' grace, one monthly payment at most, whatever today's date (on
        # the 29th, the one due on the 28th still shows, and so would the next within 30 days).
        upcoming = (await client.get("/api/finance/recurring/upcoming", params={"days": 20})).json()
        assert [(u["name"], u["amount"], u["amount_eur"]) for u in upcoming] == [
            ("Music", "-5.9900", "-5.99")
        ]

        await client.patch(f"/api/finance/recurring/{spotify}", json={"cancelled": True})
        assert (await client.get("/api/finance/recurring/upcoming")).json() == []

    # Another member never sees a series on the owner's private account.
    async with api(home.member) as client:
        names = {s["name"] for s in (await client.get("/api/finance/recurring")).json()}
        assert names == {"NETFLIX.COM", "Music"}
