"""The spending month: one month day by day, by category and by merchant."""

import uuid
from datetime import date
from decimal import Decimal
from typing import Any

import httpx
import pytest
from households import Home, add, api, refresh
from test_insights import set_rate

from hubnisio.finance.insights.spending import CategoryInfo, DayRow, add_months
from hubnisio.finance.insights.spending_month import MonthFilter, month_spending
from hubnisio.finance.models import CategoryKind, TransactionKind, TransactionStatus

pytestmark = pytest.mark.anyio

URL = "/api/finance/insights/spending/month"
SEPTEMBER = date(2026, 9, 1)  # always in the past, so the month is complete


async def merchant(client: httpx.AsyncClient, name: str) -> str:
    response = await client.post("/api/finance/counterparties", json={"name": name})
    assert response.status_code == 201, response.text
    return response.json()["id"]


async def decide(
    client: httpx.AsyncClient, transaction_id: uuid.UUID, category: uuid.UUID, who: str | None
) -> None:
    body = {"category_id": str(category)}
    if who:
        body["counterparty_id"] = who
    response = await client.patch(f"/api/finance/transactions/{transaction_id}", json=body)
    assert response.status_code == 200, response.text


def september(day: int) -> date:
    return date(2026, 9, day)


async def seed(home: Home) -> dict[str, str]:
    """September and August 2026; returns the merchants' IDs by name."""
    await set_rate("XTS", september(1), "11")
    groceries, restaurants = home.categories["Groceries"], home.categories["Restaurants"]
    async with api(home.owner) as client:
        lidl, cafe = await merchant(client, "Lidl"), await merchant(client, "Café")
        for amount, day, category, who, currency, account in (
            ("-50.00", 3, groceries, lidl, "EUR", None),
            ("10.00", 4, groceries, lidl, "EUR", None),  # a refund
            ("-20.00", 3, restaurants, cafe, "EUR", None),
            ("-110.00", 5, restaurants, cafe, "XTS", None),  # 10 euros
            ("-40.00", 6, groceries, lidl, "EUR", home.private),
        ):
            transaction = await add(
                home, amount, 0, on=september(day), currency=currency, account=account
            )
            await decide(client, transaction, category, who)
        salary = await add(home, "1000.00", 0, on=september(1))
        await decide(client, salary, home.categories["Salary"], None)
        await add(home, "-7.00", 0, on=september(8))  # no category, no merchant
        await add(home, "-999.00", 0, on=september(9), status=TransactionStatus.PENDING)
        await add(home, "-99.00", 0, on=date(2026, 8, 30), currency="XTS")  # no rate that day
        marked = await add(home, "-25.00", 0, on=september(10))
        await client.patch(f"/api/finance/transactions/{marked}", json={"kind": "transfer"})
        await add(home, "-300.00", 0, on=september(12))  # a transfer pair, found by matching
        await add(home, "300.00", 0, on=september(12), account=home.savings)
        # The month before, where the data starts.
        old = await add(home, "-30.00", 0, on=date(2026, 8, 10))
        await decide(client, old, groceries, lidl)
        await add(home, "-4.00", 0, on=date(2026, 8, 5))
    await refresh(home)
    return {"lidl": lidl, "cafe": cafe}


def by_day(part: dict[str, Any]) -> dict[int, tuple[str, int]]:
    return {
        int(d["day"][-2:]): (d["amount"], d["count"])
        for d in part["days"]
        if d["count"] or d["amount"] != "0.00"
    }


async def test_a_month_by_day_category_and_merchant(home: Home) -> None:
    ids = await seed(home)
    async with api(home.owner) as client:
        response = await client.get(URL, params={"month": SEPTEMBER.isoformat()})
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["month"] == "2026-09-01"
    assert (body["through"], body["incomplete"]) == ("2026-09-30", False)
    # The private account counts for its owner; income, pending, transfers and the payment
    # without a rate don't.
    assert by_day(body) == {
        3: ("70.00", 2),
        4: ("-10.00", 1),
        5: ("10.00", 1),
        6: ("40.00", 1),
        8: ("7.00", 1),
    }
    assert (body["total"], body["count"]) == ("117.00", 6)
    assert body["daily_average"] == "3.90"  # 117 over 30 days
    assert len(body["days"]) == 30
    running = [d["running"] for d in body["days"]]
    assert running[:6] == ["0.00", "0.00", "70.00", "60.00", "70.00", "110.00"]
    assert running[-1] == "117.00"

    # A refund lowers its category; the biggest comes first.
    assert [(c["name"], c["amount"], c["count"], c["share"]) for c in body["categories"]] == [
        ("Groceries", "80.00", 3, "0.6838"),
        ("Restaurants", "30.00", 2, "0.2564"),
        (None, "7.00", 1, "0.0598"),
    ]
    assert body["categories"][0]["parent_id"] == str(home.categories["Food"])
    assert [(m["name"], m["amount"], m["id"]) for m in body["merchants"]] == [
        ("Lidl", "80.00", ids["lidl"]),
        ("Café", "30.00", ids["cafe"]),
        (None, "7.00", None),
    ]

    previous = body["previous"]
    assert (previous["month"], previous["through"], previous["total"]) == (
        "2026-08-01",
        "2026-08-31",
        "34.00",
    )
    assert previous["incomplete"] is True  # the data starts on the 5th
    assert by_day(previous) == {5: ("4.00", 1), 10: ("30.00", 1)}
    assert body["previous_to_date"] == "34.00"
    assert previous["days"][-1]["running"] == "34.00"


async def test_narrowing_by_account_category_and_merchant(home: Home) -> None:
    ids = await seed(home)
    month = {"month": SEPTEMBER.isoformat()}
    async with api(home.owner) as client:
        private = (await client.get(URL, params=month | {"account_id": str(home.private)})).json()
        shared = (await client.get(URL, params=month | {"account_id": str(home.shared)})).json()
        food = (
            await client.get(URL, params=month | {"category_id": str(home.categories["Food"])})
        ).json()
        groceries = (
            await client.get(URL, params=month | {"category_id": str(home.categories["Groceries"])})
        ).json()
        lidl = (await client.get(URL, params=month | {"merchant": ids["lidl"]})).json()

    assert (private["total"], private["count"]) == ("40.00", 1)
    assert private["previous"]["total"] == "0.00"
    assert private["incomplete"] is True  # its data starts in September
    assert shared["total"] == "77.00"
    # A group takes its categories.
    assert (food["total"], len(food["categories"])) == ("110.00", 2)
    assert (groceries["total"], [c["name"] for c in groceries["categories"]]) == (
        "80.00",
        ["Groceries"],
    )
    assert (lidl["total"], lidl["previous"]["total"]) == ("80.00", "30.00")
    assert [m["name"] for m in lidl["merchants"]] == ["Lidl"]


async def test_another_members_private_account_never_counts(home: Home) -> None:
    await seed(home)
    month = {"month": SEPTEMBER.isoformat()}
    async with api(home.member) as client:
        household = (await client.get(URL, params=month | {"view": "household"})).json()
        mine = (await client.get(URL, params=month)).json()
        peeking = (await client.get(URL, params=month | {"account_id": str(home.private)})).json()
        peeking_house = (
            await client.get(
                URL, params=month | {"view": "household", "account_id": str(home.private)}
            )
        ).json()

    assert household["total"] == "77.00"  # without the owner's private 40
    assert [m["amount"] for m in household["merchants"]] == ["40.00", "30.00", "7.00"]
    assert mine["total"] == "0.00"  # they own no account
    assert peeking["total"] == peeking_house["total"] == "0.00"


async def test_the_current_month_is_incomplete(home: Home) -> None:
    today = date.today()
    first = today.replace(day=1)
    await add(home, "-20.00", 0, on=today)
    await add(home, "-10.00", 0, on=add_months(first, -1))
    async with api(home.owner) as client:
        body = (await client.get(URL)).json()  # this month by default
        future = (await client.get(URL, params={"month": add_months(first, 1).isoformat()})).json()

    assert body["month"] == first.isoformat()
    assert (body["through"], body["incomplete"]) == (today.isoformat(), True)
    assert body["total"] == "20.00"
    assert body["daily_average"] == f"{Decimal(20) / today.day:.2f}"
    days = body["days"]
    assert days[today.day - 1]["running"] == "20.00"
    assert all(d["running"] is None for d in days[today.day :])
    assert body["previous"]["total"] == "10.00"
    assert body["previous_to_date"] == "10.00"
    assert (future["through"], future["incomplete"], future["total"]) == (None, True, "0.00")
    assert future["daily_average"] == "0.00"


def test_the_average_is_over_the_days_so_far() -> None:
    groceries = uuid.uuid4()
    categories = {groceries: CategoryInfo(groceries, "Groceries", CategoryKind.EXPENSE, None, 0)}
    expense = TransactionKind.EXPENSE
    rows = [
        DayRow(date(2026, 9, 2), groceries, None, expense, Decimal(-30), 1),
        DayRow(date(2026, 9, 10), groceries, None, expense, Decimal(-60), 2),
        DayRow(date(2026, 8, 4), groceries, None, expense, Decimal(-20), 1),
        DayRow(date(2026, 8, 20), groceries, None, expense, Decimal(-50), 1),
    ]
    body = month_spending(
        rows,
        categories,
        {},
        SEPTEMBER,
        today=date(2026, 9, 15),
        first_data=date(2026, 7, 1),
        narrowed=MonthFilter(),
    )
    assert (body.total, body.daily_average, body.through) == (
        Decimal("90.00"),
        Decimal("6.00"),
        date(2026, 9, 15),
    )
    assert body.incomplete is True
    assert [d.running for d in body.days][13:17] == [Decimal("90.00"), Decimal("90.00"), None, None]
    assert body.previous.incomplete is False
    assert body.previous_to_date == Decimal("20.00")  # through August 15th
    assert body.previous.total == Decimal("70.00")
