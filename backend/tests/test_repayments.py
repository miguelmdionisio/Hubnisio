"""Repayments and refunds (ADR-0007): money in with an expense category lowers that category's
spending, and its kind follows the category."""

from datetime import date
from decimal import Decimal
from typing import Any

import httpx
import pytest
from households import Home, add, api, refresh

from hubnisio.finance.budgets import budget_months
from hubnisio.finance.models import Overspend

pytestmark = pytest.mark.anyio

OCTOBER = {"months": 1, "until": "2026-10-01"}


async def items(client: httpx.AsyncClient, **params: Any) -> list[dict[str, Any]]:
    response = await client.get("/api/finance/transactions", params=params)
    assert response.status_code == 200, response.text
    return response.json()["items"]


async def categorize(
    client: httpx.AsyncClient, home: Home, name: str, *transactions: object
) -> None:
    for transaction in transactions:
        response = await client.patch(
            f"/api/finance/transactions/{transaction}",
            json={"category_id": str(home.categories[name])},
        )
        assert response.status_code == 200, response.text


async def test_a_repayment_lowers_the_category_and_is_not_income(home: Home) -> None:
    rent_paid = await add(home, "-1200.00", 3)
    repaid = await add(home, "600.00", 4)
    await refresh(home)

    async with api(home.owner) as client:
        await categorize(client, home, "Rent & mortgage", rent_paid, repaid)

        spending = (await client.get("/api/finance/insights/spending", params=OCTOBER)).json()
        [housing] = spending["groups"]
        assert (housing["name"], housing["amounts"]) == ("Housing", ["600.00"])
        [rent] = [c for c in housing["categories"] if c["name"] == "Rent & mortgage"]
        assert rent["amounts"] == ["600.00"]

        flow = (await client.get("/api/finance/insights/cash-flow", params=OCTOBER)).json()
        [october] = flow["months"]
        assert (october["income"], october["spending"], october["net"]) == (
            "0.00",
            "600.00",
            "-600.00",
        )

        response = await client.put(
            "/api/finance/budgets/overall", json={"amount": "1000", "from_month": "2026-10-01"}
        )
        assert response.status_code == 200, response.text
        budgets = (await client.get("/api/finance/budgets", params={"month": "2026-10-01"})).json()
        assert (budgets["overall"]["spent"], budgets["overall"]["remaining"]) == (
            "600.00",
            "400.00",
        )

        # Its kind is expense: in the row and in the list's filter.
        by_id = {item["id"]: item for item in await items(client)}
        assert by_id[str(repaid)]["kind"] == "expense"
        assert by_id[str(repaid)]["kind_source"] is None
        assert {i["id"] for i in await items(client, kind="expense")} == {
            str(rent_paid),
            str(repaid),
        }
        assert await items(client, kind="income") == []


async def test_the_kind_follows_the_category_unless_overridden(home: Home) -> None:
    refunded = await add(home, "25.00", 1)
    returned_salary = await add(home, "-100.00", 2)
    plain_income = await add(home, "40.00", 3)
    forced = await add(home, "30.00", 4)
    paired_out = await add(home, "-500.00", 5)
    paired_in = await add(home, "500.00", 5, account=home.savings)
    await refresh(home)

    async with api(home.owner) as client:
        await categorize(client, home, "Groceries", refunded, forced, paired_in)
        await categorize(client, home, "Salary", returned_salary)
        await client.patch(f"/api/finance/transactions/{forced}", json={"kind": "income"})

        by_id = {item["id"]: item["kind"] for item in await items(client)}
        assert by_id == {
            str(refunded): "expense",  # money in, expense category
            str(returned_salary): "income",  # money out, income category
            str(plain_income): "income",  # no category: the sign
            str(forced): "income",  # the override beats the category
            str(paired_out): "transfer",  # a transfer beats the category
            str(paired_in): "transfer",
        }

        def ids(found: list[dict[str, Any]]) -> set[str]:
            return {item["id"] for item in found}

        assert ids(await items(client, kind="expense")) == {str(refunded)}
        assert ids(await items(client, kind="income")) == {
            str(returned_salary),
            str(plain_income),
            str(forced),
        }
        assert ids(await items(client, kind="transfer")) == {str(paired_out), str(paired_in)}


async def test_a_rule_puts_money_in_into_an_expense_category(home: Home) -> None:
    repaid = await add(home, "600.00", 4, counterparty="Ana Silva")
    too_small = await add(home, "20.00", 5, counterparty="Ana Silva")
    someone_else = await add(home, "600.00", 6, counterparty="Rui Costa")
    paid_out = await add(home, "-600.00", 7, counterparty="Ana Silva")
    await refresh(home)

    async with api(home.owner) as client:
        created = await client.post(
            "/api/finance/rules",
            json={
                "name": "Ana pays half the rent",
                "match": "all",
                "conditions": [
                    {"field": "direction", "op": "is", "value": "in"},
                    {"field": "amount", "op": "between", "value": ["500", "700"]},
                    {"field": "counterparty", "op": "contains", "value": "ana"},
                ],
                "actions": [
                    {
                        "type": "set_category",
                        "category_id": str(home.categories["Rent & mortgage"]),
                    }
                ],
            },
        )
        assert created.status_code == 201, created.text

        by_id = {item["id"]: item for item in await items(client)}
        category = by_id[str(repaid)]["category"]
        assert (category["name"], category["source"]) == ("Rent & mortgage", "rule")
        assert by_id[str(repaid)]["kind"] == "expense"
        for other in (too_small, someone_else, paid_out):
            assert by_id[str(other)]["category"] is None

        spending = (await client.get("/api/finance/insights/spending", params=OCTOBER)).json()
        [housing] = spending["groups"]
        assert housing["amounts"] == ["-600.00"]  # nothing paid yet: the repayment dips below


async def test_a_month_that_nets_below_zero_shows_the_net(home: Home) -> None:
    refund = await add(home, "50.00", 0, on=date(2026, 9, 10))
    bill = await add(home, "-30.00", 3)
    await refresh(home)

    async with api(home.owner) as client:
        await categorize(client, home, "Utilities", refund, bill)
        response = await client.put(
            f"/api/finance/budgets/{home.categories['Utilities']}",
            json={"amount": "100", "from_month": "2026-09-01", "rollover": True},
        )
        assert response.status_code == 200, response.text

        async def utilities(month: str) -> dict[str, Any]:
            listed = (await client.get("/api/finance/budgets", params={"month": month})).json()
            [budget] = listed["budgets"]
            return budget

        september = await utilities("2026-09-01")
        assert (september["spent"], september["remaining"]) == ("-50.00", "150.00")

        # Rollover carries the extra 150 into October, where 30 is spent.
        october = await utilities("2026-10-01")
        assert (october["carried_in"], october["available"]) == ("150.00", "250.00")
        assert (october["spent"], october["remaining"]) == ("30.00", "220.00")


def test_negative_spending_rolls_over_like_any_remainder() -> None:
    months = budget_months(
        [(date(2026, 1, 1), Decimal(100))],
        {date(2026, 1, 1): Decimal(-50), date(2026, 2, 1): Decimal(30)},
        rollover=True,
        overspend=Overspend.FORGIVE,
        until=date(2026, 2, 1),
    )
    assert [(m.remaining, m.carried_in) for m in months] == [
        (Decimal(150), Decimal(0)),
        (Decimal(220), Decimal(150)),
    ]
