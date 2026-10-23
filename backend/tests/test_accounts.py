"""Retiring an account: hiding it, or deleting it with its history (ADR-0007)."""

import uuid
from datetime import date
from decimal import Decimal
from typing import Any

import httpx
import pytest
from households import Home, add, api, refresh
from sqlalchemy import func, select

from hubnisio.core.db import get_sessionmaker
from hubnisio.finance.insights.spending import add_months
from hubnisio.finance.models import BalanceSnapshot, Transaction, Transfer

pytestmark = pytest.mark.anyio

OCTOBER = {"months": 2, "until": "2026-10-01"}


async def names(client: httpx.AsyncClient, **params: Any) -> list[str]:
    """Sorted: accounts made in one transaction share their `created_at`."""
    response = await client.get("/api/finance/accounts", params=params)
    assert response.status_code == 200, response.text
    return sorted(account["name"] for account in response.json())


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


async def test_a_hidden_account_leaves_lists_and_net_worth_but_its_history_counts(
    home: Home,
) -> None:
    await add(home, "-40.00", 3)
    await add(home, "-25.00", 4, account=home.savings)
    await snapshot(home, home.shared, "1000.00")
    await snapshot(home, home.savings, "500.00")
    today = date.today()
    for months in (3, 2, 1):
        on = add_months(today, -months).replace(day=min(today.day, 28))
        await add(home, "-5.99", 0, on=on, counterparty="SPOTIFY", account=home.savings)
    await refresh(home)

    async with api(home.owner) as client:
        [series] = (await client.get("/api/finance/recurring")).json()
        await client.patch(f"/api/finance/recurring/{series['id']}", json={"review": "confirmed"})
        await client.put(
            "/api/finance/budgets/overall", json={"amount": "500", "from_month": "2026-10-01"}
        )
        flow = (await client.get("/api/finance/insights/cash-flow", params=OCTOBER)).json()
        spending = (await client.get("/api/finance/insights/spending", params=OCTOBER)).json()
        budget = (await client.get("/api/finance/budgets", params={"month": "2026-10-01"})).json()
        assert (await client.get("/api/finance/recurring/upcoming")).json() != []

        hidden = await client.patch(f"/api/finance/accounts/{home.savings}", json={"hidden": True})
        assert hidden.status_code == 200, hidden.text
        assert hidden.json()["hidden_at"] is not None
        assert hidden.json()["transaction_count"] == 4

        # Out of the account list, net worth and upcoming payments...
        assert await names(client) == ["Conta", "Pessoal"]
        assert await names(client, include_hidden=True) == ["Conta", "Pessoal", "Poupança"]
        worth = (await client.get("/api/finance/insights/net-worth")).json()
        assert "Poupança" not in {account["name"] for account in worth["accounts"]}
        assert worth["total"] == "1000.00"
        assert (await client.get("/api/finance/recurring/upcoming")).json() == []

        # ...but its past transactions still count.
        listed = (await client.get("/api/finance/transactions")).json()["items"]
        assert sum(item["account_id"] == str(home.savings) for item in listed) == 4
        assert (await client.get("/api/finance/insights/cash-flow", params=OCTOBER)).json() == flow
        assert (
            await client.get("/api/finance/insights/spending", params=OCTOBER)
        ).json() == spending
        after = (await client.get("/api/finance/budgets", params={"month": "2026-10-01"})).json()
        assert after["overall"] == budget["overall"]
        assert len((await client.get("/api/finance/recurring")).json()) == 1

        shown = await client.patch(f"/api/finance/accounts/{home.savings}", json={"hidden": False})
        assert shown.json()["hidden_at"] is None
        assert await names(client) == ["Conta", "Pessoal", "Poupança"]


async def test_deleting_an_account_keeps_its_transfers_as_transfers(home: Home) -> None:
    kept_out = await add(home, "-300.00", 12)  # pairs with the savings account below
    await add(home, "300.00", 12, account=home.savings)
    kept_in = await add(home, "50.00", 0, on=date(2026, 9, 20))
    await add(home, "-50.00", 0, on=date(2026, 9, 20), account=home.savings)
    await add(home, "-20.00", 5)  # spending on the account that stays
    await refresh(home)

    async with api(home.owner) as client:
        flow = (await client.get("/api/finance/insights/cash-flow", params=OCTOBER)).json()
        spending = (await client.get("/api/finance/insights/spending", params=OCTOBER)).json()

        blocked = await client.delete(f"/api/finance/accounts/{home.savings}")
        assert blocked.status_code == 409
        assert blocked.json() == {
            "detail": "This account has transactions. Confirm to delete them with it.",
            "transaction_count": 2,
            "transfer_count": 2,
        }

        deleted = await client.delete(
            f"/api/finance/accounts/{home.savings}", params={"confirm": True}
        )
        assert deleted.status_code == 204, deleted.text
        assert await names(client, include_hidden=True) == ["Conta", "Pessoal"]

        # Spending and income are unchanged: the kept sides are transfers on their own.
        assert (await client.get("/api/finance/insights/cash-flow", params=OCTOBER)).json() == flow
        assert (
            await client.get("/api/finance/insights/spending", params=OCTOBER)
        ).json() == spending
        kinds = {
            item["id"]: (item["kind"], item["kind_source"], item["transfer"])
            for item in (await client.get("/api/finance/transactions")).json()["items"]
        }
        assert kinds[str(kept_out)] == ("transfer", "auto", None)
        assert kinds[str(kept_in)] == ("transfer", "auto", None)

    async with get_sessionmaker()() as session:
        left = await session.scalar(
            select(func.count())
            .select_from(Transaction)
            .where(Transaction.account_id == home.savings)
        )
        pairs = await session.scalar(
            select(func.count()).select_from(Transfer).where(Transfer.outgoing_id == kept_out)
        )
    assert (left, pairs) == (0, 0)

    # The rules engine leaves the kept kind alone; unmarking it by hand still works.
    await refresh(home)
    async with api(home.owner) as client:
        assert (await client.get("/api/finance/insights/cash-flow", params=OCTOBER)).json() == flow
        reset = await client.patch(f"/api/finance/transactions/{kept_out}", json={"kind": None})
        assert reset.json()["transaction"]["kind"] == "expense"


async def test_an_empty_account_deletes_without_confirmation(home: Home) -> None:
    async with api(home.owner) as client:
        deleted = await client.delete(f"/api/finance/accounts/{home.private}")
        assert deleted.status_code == 204, deleted.text
        assert await names(client, include_hidden=True) == ["Conta", "Poupança"]


async def test_only_an_owner_hides_or_deletes(home: Home) -> None:
    await add(home, "-10.00", 3)
    async with api(home.member) as client:
        # The member sees the shared account but doesn't own it; the private one is unknown.
        assert await names(client) == ["Conta", "Poupança"]
        for account in (home.shared, home.private):
            hide = await client.patch(f"/api/finance/accounts/{account}", json={"hidden": True})
            delete = await client.delete(
                f"/api/finance/accounts/{account}", params={"confirm": True}
            )
            assert (hide.status_code, delete.status_code) == (404, 404)
        assert await names(client) == ["Conta", "Poupança"]
