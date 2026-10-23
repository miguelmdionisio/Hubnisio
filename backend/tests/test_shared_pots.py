"""Shared pots and the two views (ADR-0005): in Mine, money moved into a pot is spending in its
category, and the pot's own spending and balance are left out."""

import uuid
from decimal import Decimal
from typing import Any

import httpx
import pytest
from households import Home, add, api, refresh

from hubnisio.core.db import get_sessionmaker
from hubnisio.finance.models import Account, AccountOwner, AccountVisibility, BalanceSnapshot

pytestmark = pytest.mark.anyio

OCTOBER = {"months": 1, "until": "2026-10-01"}
HOUSEHOLD = {"view": "household"}


async def snapshot(home: Home, account: uuid.UUID, amount: str) -> None:
    async with get_sessionmaker()() as session, session.begin():
        session.add(
            BalanceSnapshot(
                household_id=home.owner.household_id,
                account_id=account,
                balance_type="ITAV",
                amount=Decimal(amount),
                currency="EUR",
            )
        )


async def make_pot(
    client: httpx.AsyncClient, account: uuid.UUID, category: uuid.UUID | None
) -> dict[str, Any]:
    body = {"is_pot": True, "pot_category_id": str(category) if category else None}
    response = await client.patch(f"/api/finance/accounts/{account}", json=body)
    assert response.status_code == 200, response.text
    return response.json()


async def get(client: httpx.AsyncClient, path: str, **params: Any) -> Any:
    response = await client.get(f"/api/finance/{path}", params=params)
    assert response.status_code == 200, response.text
    return response.json()


def spent_in(spending: dict[str, Any]) -> dict[str, str]:
    """This month's spending per category, with the uncategorized total."""
    result = {"uncategorized": spending["uncategorized"][-1]}
    for group in spending["groups"]:
        result |= {c["name"]: c["amounts"][-1] for c in group["categories"]}
    return result


def flow_of(cash_flow: dict[str, Any]) -> tuple[str, str]:
    [month] = cash_flow["months"]
    return month["income"], month["spending"]


async def test_the_example_in_both_views(home: Home) -> None:
    """1,000 on a personal account, 300 moved into the pot, and the pot spends 120."""
    rent = home.categories["Rent & mortgage"]
    await add(home, "-300.00", 12)  # Conta -> the pot, paired by matching
    await add(home, "300.00", 12, account=home.savings)
    await add(home, "-120.00", 14, account=home.savings)
    await add(home, "-100.00", 15)  # Conta -> Pessoal: both the owner's, still a transfer
    await add(home, "100.00", 15, account=home.private)
    await snapshot(home, home.shared, "600.00")
    await snapshot(home, home.private, "100.00")
    await snapshot(home, home.savings, "180.00")
    await refresh(home)

    async with api(home.owner) as client:
        pot = await make_pot(client, home.savings, rent)
        assert (pot["is_pot"], pot["pot_category_id"]) == (True, str(rent))

        # Mine, the default: the move into the pot is spending; the pot's own isn't.
        assert spent_in(await get(client, "insights/spending", **OCTOBER)) == {
            "uncategorized": "0.00",
            "Rent & mortgage": "300.00",
        }
        assert flow_of(await get(client, "insights/cash-flow", **OCTOBER)) == ("0.00", "300.00")
        worth = await get(client, "insights/net-worth")
        assert worth["total"] == "700.00"
        assert sorted(a["name"] for a in worth["accounts"]) == ["Conta", "Pessoal"]

        # Household: everything in full, the moves are transfers.
        spending = await get(client, "insights/spending", **OCTOBER, **HOUSEHOLD)
        assert spent_in(spending) == {"uncategorized": "120.00"}
        cash_flow = await get(client, "insights/cash-flow", **OCTOBER, **HOUSEHOLD)
        assert flow_of(cash_flow) == ("0.00", "120.00")
        assert (await get(client, "insights/net-worth", **HOUSEHOLD))["total"] == "880.00"

        # The pot's real balance still shows on the accounts list.
        accounts = {a["name"]: a for a in await get(client, "accounts")}
        assert Decimal(accounts["Poupança"]["balance"]["amount"]) == Decimal("180.00")


async def test_money_back_from_the_pot_lowers_its_category(home: Home) -> None:
    rent = home.categories["Rent & mortgage"]
    await add(home, "-300.00", 12)
    await add(home, "300.00", 12, account=home.savings)
    await add(home, "-50.00", 20, account=home.savings)  # the pot -> Conta
    await add(home, "50.00", 20)
    await refresh(home)

    async with api(home.owner) as client:
        await make_pot(client, home.savings, rent)
        spending = await get(client, "insights/spending", **OCTOBER)
        assert spent_in(spending) == {"uncategorized": "0.00", "Rent & mortgage": "250.00"}
        assert flow_of(await get(client, "insights/cash-flow", **OCTOBER)) == ("0.00", "250.00")
        household = await get(client, "insights/cash-flow", **OCTOBER, **HOUSEHOLD)
        assert flow_of(household) == ("0.00", "0.00")


async def test_another_members_deposit_never_shows_in_mine(home: Home) -> None:
    rent = home.categories["Rent & mortgage"]
    async with get_sessionmaker()() as session, session.begin():
        theirs = Account(
            household_id=home.owner.household_id,
            institution_name="Revolut",
            currency="EUR",
            display_name="Rui",
            visibility=AccountVisibility.SHARED,
        )
        session.add(theirs)
        await session.flush()
        session.add(AccountOwner(account_id=theirs.id, user_id=home.member.user_id))
    await add(home, "-200.00", 5, account=theirs.id)  # the member's account -> the pot
    await add(home, "200.00", 5, account=home.savings)
    await add(home, "80.00", 6, account=home.savings)  # from a bank outside the hub
    await refresh(home)

    async with api(home.owner) as client:
        await make_pot(client, home.savings, rent)
        assert spent_in(await get(client, "insights/spending", **OCTOBER)) == {
            "uncategorized": "0.00"
        }
        assert flow_of(await get(client, "insights/cash-flow", **OCTOBER)) == ("0.00", "0.00")
        household = await get(client, "insights/cash-flow", **OCTOBER, **HOUSEHOLD)
        assert flow_of(household) == ("80.00", "0.00")

    # For the member, it's their own contribution.
    async with api(home.member) as client:
        assert spent_in(await get(client, "insights/spending", **OCTOBER)) == {
            "uncategorized": "0.00",
            "Rent & mortgage": "200.00",
        }


async def test_budgets_follow_the_view(home: Home) -> None:
    rent = home.categories["Rent & mortgage"]
    await add(home, "-300.00", 12)
    await add(home, "300.00", 12, account=home.savings)
    await add(home, "-120.00", 14, account=home.savings)
    await refresh(home)

    async with api(home.owner) as client:
        await make_pot(client, home.savings, rent)
        for path, body in (
            (f"budgets/{rent}", {"amount": "400", "from_month": "2026-10-01"}),
            ("budgets/overall", {"amount": "1000", "from_month": "2026-10-01"}),
        ):
            response = await client.put(f"/api/finance/{path}", json=body)
            assert response.status_code == 200, response.text

        mine = await get(client, "budgets", month="2026-10-01")
        [budget] = mine["budgets"]
        assert (budget["name"], budget["spent"], budget["remaining"]) == (
            "Rent & mortgage",
            "300.00",
            "100.00",
        )
        assert mine["overall"]["spent"] == "300.00"
        assert mine["uncategorized"] == "0.00"

        household = await get(client, "budgets", month="2026-10-01", **HOUSEHOLD)
        assert household["budgets"][0]["spent"] == "0.00"
        assert household["overall"]["spent"] == "120.00"
        assert household["uncategorized"] == "120.00"


async def test_a_contribution_without_a_category_is_uncategorized(home: Home) -> None:
    await add(home, "-300.00", 12)
    await add(home, "300.00", 12, account=home.savings)
    await refresh(home)

    async with api(home.owner) as client:
        pot = await make_pot(client, home.savings, None)
        assert (pot["is_pot"], pot["pot_category_id"]) == (True, None)
        spending = await get(client, "insights/spending", **OCTOBER)
        assert spent_in(spending) == {"uncategorized": "300.00"}
        assert flow_of(await get(client, "insights/cash-flow", **OCTOBER)) == ("0.00", "300.00")

        # Back to an ordinary account: the move is a transfer again.
        response = await client.patch(
            f"/api/finance/accounts/{home.savings}", json={"is_pot": False}
        )
        assert response.json()["is_pot"] is False
        assert flow_of(await get(client, "insights/cash-flow", **OCTOBER)) == ("0.00", "0.00")


async def test_only_an_owner_sets_a_pot_and_its_category_is_for_spending(home: Home) -> None:
    async with api(home.member) as client:
        response = await client.patch(f"/api/finance/accounts/{home.shared}", json={"is_pot": True})
        assert response.status_code == 404

    async with api(home.owner) as client:
        salary = home.categories["Salary"]
        response = await client.patch(
            f"/api/finance/accounts/{home.shared}", json={"pot_category_id": str(salary)}
        )
        assert response.status_code == 422
        response = await client.patch(
            f"/api/finance/accounts/{home.shared}", json={"pot_category_id": str(uuid.uuid4())}
        )
        assert response.status_code == 404
        accounts = {a["name"]: a for a in await get(client, "accounts")}
        assert (accounts["Conta"]["is_pot"], accounts["Conta"]["pot_category_id"]) == (False, None)
