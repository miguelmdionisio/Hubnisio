"""Budgets: the monthly arithmetic, and the API."""

from datetime import date
from decimal import Decimal

import pytest
from households import Home, add, api, refresh

from hubnisio.finance.budgets import budget_months
from hubnisio.finance.models import Overspend

JAN, FEB, MAR = date(2026, 1, 1), date(2026, 2, 1), date(2026, 3, 1)
# Under by 20, over by 30 (or 10 with January's 20 carried), then under.
SPENT = {JAN: Decimal(80), FEB: Decimal(130), MAR: Decimal(50)}


@pytest.mark.parametrize(
    ("rollover", "overspend", "available", "remaining"),
    [
        (False, Overspend.FORGIVE, [100, 100, 100], [20, -30, 50]),
        (True, Overspend.FORGIVE, [100, 120, 100], [20, -10, 50]),
        (False, Overspend.CARRY, [100, 100, 70], [20, -30, 20]),
        (True, Overspend.CARRY, [100, 120, 90], [20, -10, 40]),
    ],
)
def test_rollover_and_overspend(
    rollover: bool, overspend: Overspend, available: list[int], remaining: list[int]
) -> None:
    months = budget_months(
        [(JAN, Decimal(100))], SPENT, rollover=rollover, overspend=overspend, until=MAR
    )
    assert [m.month for m in months] == [JAN, FEB, MAR]
    assert [m.available for m in months] == [Decimal(a) for a in available]
    assert [m.remaining for m in months] == [Decimal(r) for r in remaining]
    assert months[0].carried_in == 0


def test_a_new_amount_holds_from_its_month() -> None:
    months = budget_months(
        [(MAR, Decimal(200)), (JAN, Decimal(100))],
        SPENT,
        rollover=True,
        overspend=Overspend.CARRY,
        until=date(2026, 3, 31),
    )
    assert [(m.limit, m.available) for m in months] == [
        (100, 100),
        (100, 120),
        (200, 190),
    ]


def test_nothing_before_the_first_month() -> None:
    assert (
        budget_months(
            [(MAR, Decimal(1))], SPENT, rollover=False, overspend=Overspend.FORGIVE, until=FEB
        )
        == []
    )


@pytest.mark.anyio
async def test_budgets_api(home: Home) -> None:
    october = date(2026, 10, 1)
    spending = {
        "Groceries": [
            await add(home, "-80.00", 3),
            await add(home, "-40.00", 4, account=home.private),
        ],
        "Restaurants": [
            await add(home, "-30.00", 5),
            await add(home, "-150.00", 0, on=date(2026, 9, 9)),
        ],
        "Fuel": [await add(home, "-60.00", 6)],
        "Utilities": [await add(home, "-40.00", 7)],
    }
    await add(home, "-7.00", 8)  # uncategorized
    await refresh(home)
    c = home.categories

    async with api(home.owner) as client:
        for name, ids in spending.items():
            for transaction_id in ids:
                await client.patch(
                    f"/api/finance/transactions/{transaction_id}",
                    json={"category_id": str(c[name])},
                )

        async def put(name: str, **body: object) -> dict:
            response = await client.put(f"/api/finance/budgets/{c[name]}", json=body)
            assert response.status_code == 200, response.text
            return response.json()

        await put("Food", amount="200", from_month="2026-09-15", rollover=True, overspend="carry")
        await put("Groceries", amount="100", from_month="2026-10-01")
        await put("Fuel", amount="50", from_month="2026-10-01")
        income = await client.put(
            f"/api/finance/budgets/{c['Salary']}", json={"amount": "1", "from_month": "2026-10-01"}
        )
        assert income.status_code == 422

        listed = (await client.get("/api/finance/budgets", params={"month": "2026-10-20"})).json()
        assert listed["month"] == october.isoformat()
        food, fuel = listed["budgets"]
        # September: 150 of 200 spent, so 50 carries into October.
        assert (food["name"], food["limit"], food["carried_in"], food["available"]) == (
            "Food",
            "200.00",
            "50.00",
            "250.00",
        )
        assert (food["spent"], food["remaining"], food["starts_on"]) == (
            "150.00",
            "100.00",
            "2026-09-01",
        )
        [groceries] = food["children"]
        assert (groceries["name"], groceries["spent"], groceries["remaining"]) == (
            "Groceries",
            "120.00",
            "-20.00",
        )
        assert (fuel["name"], fuel["group_id"], fuel["remaining"]) == (
            "Fuel",
            str(c["Transport"]),
            "-10.00",
        )
        # The totals count the group, not its sub-limit as well.
        assert (listed["total_limit"], listed["total_available"], listed["total_spent"]) == (
            "250.00",
            "300.00",
            "210.00",
        )
        assert (listed["unbudgeted"], listed["uncategorized"]) == ("40.00", "7.00")

        # A new amount from October keeps September's.
        settings = await put(
            "Food", amount="300", from_month="2026-10-01", rollover=True, overspend="carry"
        )
        assert [(x["starts_on"], x["amount"]) for x in settings["limits"]] == [
            ("2026-09-01", "200.0000"),
            ("2026-10-01", "300.0000"),
        ]
        # ...and setting it from September again replaces October's.
        settings = await put("Food", amount="200", from_month="2026-09-01")
        assert [x["starts_on"] for x in settings["limits"]] == ["2026-09-01"]
        assert settings["rollover"] is False

        before = (await client.get("/api/finance/budgets", params={"month": "2026-08-01"})).json()
        assert before["budgets"] == []

        assert (await client.delete(f"/api/finance/budgets/{c['Fuel']}")).status_code == 204
        listed = (await client.get("/api/finance/budgets", params={"month": "2026-10-01"})).json()
        assert [b["name"] for b in listed["budgets"]] == ["Food"]

    # The same budgets for another member, without the owner's private account.
    async with api(home.member) as client:
        listed = (await client.get("/api/finance/budgets", params={"month": "2026-10-01"})).json()
        [food] = listed["budgets"]
        assert food["children"][0]["spent"] == "80.00"
