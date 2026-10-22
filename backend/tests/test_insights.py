"""Insights: spending by category, cash flow and net worth."""

import uuid
from datetime import date, timedelta
from decimal import Decimal

import pytest
from households import Home, add, api, refresh
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from hubnisio.core.db import get_sessionmaker
from hubnisio.finance.models import (
    BalanceSnapshot,
    Connection,
    FxRate,
    FxSource,
    ProviderAccount,
    TransactionStatus,
)

pytestmark = pytest.mark.anyio


async def set_rate(currency: str, on: date, rate: str) -> None:
    async with get_sessionmaker()() as session, session.begin():
        values = {"quote_currency": currency, "on": on, "rate": Decimal(rate)}
        await session.execute(
            insert(FxRate)
            .values(**values, source=FxSource.ECB)
            .on_conflict_do_update(index_elements=["quote_currency", "on"], set_=values)
        )


async def snapshot(
    home: Home,
    account: uuid.UUID,
    *balances: tuple[str, str],
    currency: str = "EUR",
    reference_date: date | None = None,
) -> None:
    """One sync's balances, as (type, amount): one transaction, so one `fetched_at`."""
    async with get_sessionmaker()() as session, session.begin():
        session.add_all(
            BalanceSnapshot(
                household_id=home.owner.household_id,
                account_id=account,
                balance_type=balance_type,
                amount=Decimal(amount),
                currency=currency,
                reference_date=reference_date,
            )
            for balance_type, amount in balances
        )


async def test_spending_and_cash_flow(home: Home) -> None:
    october = date(2026, 10, 1)
    await set_rate("XTS", date(2026, 10, 1), "11")
    groceries = [
        await add(home, "-50.00", 3),
        await add(home, "10.00", 4),  # a refund
        await add(home, "-30.00", 0, on=date(2026, 9, 10)),
        await add(home, "-40.00", 6, account=home.private),
    ]
    restaurants = [
        await add(home, "-20.00", 7),
        await add(home, "-110.00", 5, currency="XTS"),  # 10 euros
        await add(home, "-99.00", 0, on=date(2026, 9, 1), currency="XTS"),  # no rate that day
    ]
    salary = await add(home, "1000.00", 1)
    await add(home, "-7.00", 8)  # uncategorized spending
    await add(home, "100.00", 9)  # uncategorized income
    marked = await add(home, "-25.00", 10)  # marked as a transfer below
    await add(home, "-999.00", 11, status=TransactionStatus.PENDING)
    await add(home, "-300.00", 12)  # a transfer pair, found by matching
    await add(home, "300.00", 12, account=home.savings)
    await refresh(home)

    async with api(home.owner) as client:
        for ids, name in (
            (groceries, "Groceries"),
            (restaurants, "Restaurants"),
            ([salary], "Salary"),
        ):
            for transaction_id in ids:
                response = await client.patch(
                    f"/api/finance/transactions/{transaction_id}",
                    json={"category_id": str(home.categories[name])},
                )
                assert response.status_code == 200, response.text
        await client.patch(f"/api/finance/transactions/{marked}", json={"kind": "transfer"})

        params = {"months": 2, "until": october.isoformat()}
        spending = (await client.get("/api/finance/insights/spending", params=params)).json()
        assert spending["months"] == ["2026-09-01", "2026-10-01"]
        assert spending["unconverted"] == 1
        assert spending["uncategorized"] == ["0.00", "7.00"]
        [food] = spending["groups"]
        assert (food["name"], food["amounts"]) == ("Food", ["30.00", "110.00"])
        assert [(c["name"], c["amounts"]) for c in food["categories"]] == [
            ("Groceries", ["30.00", "80.00"]),
            ("Restaurants", ["0.00", "30.00"]),
        ]

        flow = (await client.get("/api/finance/insights/cash-flow", params=params)).json()
        assert [(m["income"], m["spending"], m["net"]) for m in flow["months"]] == [
            ("0.00", "30.00", "-30.00"),
            ("1100.00", "117.00", "983.00"),
        ]

    # Another member doesn't see the owner's private account, even as a total.
    async with api(home.member) as client:
        spending = (await client.get("/api/finance/insights/spending", params=params)).json()
        [food] = spending["groups"]
        assert food["amounts"] == ["30.00", "70.00"]


async def test_net_worth(home: Home) -> None:
    today = date.today()

    def ago(days: int) -> date:
        return today - timedelta(days=days)

    await add(home, "-10.00", 0, on=ago(5))
    await add(home, "50.00", 0, on=ago(3))
    await add(home, "-100.00", 0, on=ago(1))
    await snapshot(
        home, home.shared, ("ITAV", "1200.00"), ("CLBD", "1000.00"), reference_date=today
    )
    await add(home, "200.00", 0, on=ago(2), account=home.savings)
    await snapshot(home, home.savings, ("ITAV", "500.00"))
    # The owner's private account: no transactions, 300 XTT at 3 per euro.
    await snapshot(home, home.private, ("ITAV", "300.00"), currency="XTT")
    await set_rate("XTT", ago(4), "3")

    async with api(home.owner) as client:
        worth = (await client.get("/api/finance/insights/net-worth")).json()
        # Starts when every account with transactions has data: the savings account's first.
        assert [(p["on"], p["amount"]) for p in worth["points"]] == [
            (ago(2).isoformat(), "1700.00"),  # the booked balance, before the -100
            (ago(1).isoformat(), "1600.00"),
            (today.isoformat(), "1600.00"),
        ]
        assert worth["total"] == "1600.00"
        assert worth["unconverted"] == 0
        assert {a["name"]: a["balance_eur"] for a in worth["accounts"]} == {
            "Conta": "1000.00",
            "Poupança": "500.00",
            "Pessoal": "100.00",
        }

        later = await client.get(
            "/api/finance/insights/net-worth", params={"date_from": ago(1).isoformat()}
        )
        assert len(later.json()["points"]) == 2

        excluded = await client.patch(
            f"/api/finance/accounts/{home.savings}", json={"include_in_net_worth": False}
        )
        assert excluded.status_code == 200, excluded.text
        worth = (await client.get("/api/finance/insights/net-worth")).json()
        # From the account's first transaction; the private account has no rate that day.
        assert worth["points"][0] == {"on": ago(5).isoformat(), "amount": "1050.00"}
        assert worth["unconverted"] == 1
        assert worth["total"] == "1100.00"

    async with api(home.member) as client:
        worth = (await client.get("/api/finance/insights/net-worth")).json()
        assert worth["total"] == "1000.00"
        assert [a["name"] for a in worth["accounts"]] == ["Conta"]

    # Accounts on one connection share its history: savings was empty before its first.
    async with get_sessionmaker()() as session, session.begin():
        connection_id = await session.scalar(
            select(Connection.id).where(Connection.household_id == home.owner.household_id)
        )
        session.add_all(
            ProviderAccount(connection_id=connection_id, provider_account_uid=uid, account_id=id_)
            for uid, id_ in (("a", home.shared), ("b", home.savings))
        )
    async with api(home.owner) as client:
        await client.patch(
            f"/api/finance/accounts/{home.savings}", json={"include_in_net_worth": True}
        )
        worth = (await client.get("/api/finance/insights/net-worth")).json()
        assert worth["points"][0] == {"on": ago(5).isoformat(), "amount": "1350.00"}
