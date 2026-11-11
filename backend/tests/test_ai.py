"""The MCP server (ADR-0006): each tool gives the app's own figures for the same member and view,
query_sql runs one read-only query and nothing else, and every call is audited."""

import os
import sys
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import psycopg
import pytest
from analytics_data import OCTOBER, SEPTEMBER, VIEWS, Data, Login, new_account, save
from health_data import seed_health
from households import Home, add, api, make_home
from mcp import Client, StdioServerParameters
from portfolios import Trade, investment_account, new_instrument, set_prices
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert

from hubnisio.ai import outputs, server
from hubnisio.ai.__main__ import main
from hubnisio.ai.server import build_server, wrap
from hubnisio.core.auth import Principal
from hubnisio.core.db import get_sessionmaker
from hubnisio.core.models import AiCall
from hubnisio.core.settings import get_settings
from hubnisio.finance import schemas
from hubnisio.finance.budgets import budgets_for_month
from hubnisio.finance.insights.investments import investments
from hubnisio.finance.insights.net_worth import net_worth
from hubnisio.finance.insights.returns import investment_returns
from hubnisio.finance.insights.spending import household_categories, months_until
from hubnisio.finance.insights_api import get_cash_flow, get_spending
from hubnisio.finance.models import (
    AccountVisibility,
    BalanceSnapshot,
    Category,
    CategoryAssignment,
    Connection,
    Counterparty,
    FxRate,
    FxSource,
    ProviderAccount,
    Review,
    Source,
    TransactionAnnotation,
    TransactionStatus,
    Transfer,
)
from hubnisio.finance.recurring_api import list_recurring
from hubnisio.finance.scoping import listed_account_ids

pytestmark = pytest.mark.anyio

TOOLS = {
    "balances",
    "budget_status",
    "cashflow",
    "health_activities",
    "health_body",
    "health_performance",
    "health_recovery",
    "health_sleep",
    "health_training",
    "investments",
    "list_accounts",
    "list_categories",
    "net_worth_history",
    "query_sql",
    "recurring_payments",
    "search_transactions",
    "spending_summary",
    "suggest_categories",
    "uncategorized_overview",
}


@asynccontextmanager
async def connected(login: Login) -> AsyncIterator[Client]:
    """An MCP client talking to the server in memory, as the member's login."""
    async with Client(build_server(login.dsn)) as client:
        yield client


async def call(client: Client, tool: str, **arguments: Any) -> dict[str, Any]:
    result = await client.call_tool(tool, arguments)
    assert not result.is_error, result.content
    assert isinstance(result.structured_content, dict)
    return result.structured_content


async def failure(client: Client, tool: str, **arguments: Any) -> str:
    result = await client.call_tool(tool, arguments)
    assert result.is_error, result.structured_content
    return " ".join(getattr(content, "text", "") for content in result.content)


def principals(home: Home) -> tuple[Principal, Principal]:
    return home.owner, home.member


async def foreign_account(home: Home) -> uuid.UUID:
    """The owner's shared account in a test-only currency, on the BPI connection, so net worth
    goes back as far as that connection's history. Its rates leave gaps before today: from
    analytics_data, 4 on 1 October; here, 5 yesterday. Its balance today: 500, 100 euros."""
    today = date.today()
    wise = await new_account(home, "Wise", home.owner, AccountVisibility.SHARED, currency="XTQ")
    await add(home, "-40.00", 0, on=today - timedelta(days=3), account=wise, currency="XTQ")
    await add(home, "100.00", 0, on=today, account=wise, currency="XTQ")
    async with get_sessionmaker()() as session, session.begin():
        bpi = await session.scalar(
            select(Connection.id).where(
                Connection.household_id == home.owner.household_id,
                Connection.user_id == home.owner.user_id,
            )
        )
        assert bpi is not None
        session.add(
            ProviderAccount(connection_id=bpi, provider_account_uid="wise", account_id=wise)
        )
        session.add(
            BalanceSnapshot(
                household_id=home.owner.household_id,
                account_id=wise,
                balance_type="CLBD",
                amount=Decimal("400.00"),
                currency="XTQ",
                reference_date=today - timedelta(days=2),
                fetched_at=datetime.now(UTC),
            )
        )
        # Removed with the rest of XTQ's rates by the `data` fixture.
        await session.execute(
            insert(FxRate)
            .values(
                quote_currency="XTQ",
                on=today - timedelta(days=1),
                rate=Decimal(5),
                source=FxSource.ECB,
            )
            .on_conflict_do_nothing(index_elements=["quote_currency", "on"])
        )
    return wise


async def broker_account(home: Home) -> uuid.UUID:
    """The owner's shared investment account (ADR-0008), in net worth: a euro ETF priced
    every few days, and a stock in XTQ, whose rates leave gaps (see foreign_account). Today:
    2 ETF at 110 and 3 shares at 50 XTQ (30 euros), with 500 cash."""
    today = date.today()

    def ago(days: int) -> date:
        return today - timedelta(days=days)

    etf = await new_instrument(kind="ETF")
    stock = await new_instrument(currency="XTQ")
    account = await investment_account(
        home,
        home.owner,
        as_of=datetime.combine(today, time(9), UTC),
        cash="500",
        total_value="750",
        holdings={etf.id: ("2", "110"), stock.id: ("3", "50")},
        trades=[
            Trade(etf.id, ago(40), "3", "100", "300", tax="-0.30"),
            Trade(etf.id, ago(25), "-1", "104", "104", side="SELL"),
            Trade(stock.id, ago(8), "3", "45", "27"),
        ],
        movements={
            ago(60): ("700.00", "T212_DEPOSIT"),
            ago(9): ("23.00", "T212_INTEREST_ON_FREE_CASH"),
        },
    )
    await set_prices(etf.id, {ago(n): str(100 + n % 7) for n in range(40, 0, -6)})
    await set_prices(etf.id, {today: "110"})
    await set_prices(stock.id, {ago(8): "45", today: "50"})
    return account


# Agreement with the app.


@pytest.mark.usefixtures("data")
async def test_insights_agree_with_the_app(home: Home, logins: dict[uuid.UUID, Login]) -> None:
    async with get_sessionmaker()() as session:
        for principal in principals(home):
            async with connected(logins[principal.user_id]) as client:
                for view in VIEWS:
                    context = (principal, view)
                    spending = await call(
                        client, "spending_summary", months=2, until="2026-10-15", view=view
                    )
                    expected = await get_spending(
                        session, principal, months=2, until=OCTOBER, view=view
                    )
                    assert expected.groups, context
                    assert schemas.Spending.model_validate(spending) == expected, context

                    flow = await call(client, "cashflow", months=2, until="2026-10-15", view=view)
                    expected_flow = await get_cash_flow(
                        session, principal, months=2, until=OCTOBER, view=view
                    )
                    assert schemas.CashFlow.model_validate(flow) == expected_flow, context

                    for month in (SEPTEMBER, OCTOBER):
                        budgets = await call(
                            client, "budget_status", month=month.isoformat(), view=view
                        )
                        app = await budgets_for_month(session, principal, month, view=view)
                        assert app.overall is not None, context
                        assert schemas.BudgetsOut.model_validate(budgets) == app, (context, month)


@pytest.mark.usefixtures("data")
async def test_balances_agree_with_net_worth(home: Home, logins: dict[uuid.UUID, Login]) -> None:
    wise = await foreign_account(home)
    broker = await broker_account(home)
    async with get_sessionmaker()() as session:
        for principal in principals(home):
            listed = set(await session.scalars(listed_account_ids(principal)))
            async with connected(logins[principal.user_id]) as client:
                for view in VIEWS:
                    balances = await call(client, "balances", view=view)
                    app = await net_worth(session, principal, date.today(), view=view)
                    context = (principal, view)
                    assert Decimal(balances["net_worth"]) == app.total, context
                    assert balances["unconverted"] == 0, context
                    accounts = {uuid.UUID(a["account_id"]): a for a in balances["accounts"]}
                    assert set(accounts) == listed, context
                    counted = {id_ for id_, a in accounts.items() if a["in_net_worth"]}
                    assert counted == {a.id for a in app.accounts}, context
                    for expected in app.accounts:
                        account = accounts[expected.id]
                        assert (
                            _decimal(account["balance_today"]),
                            _decimal(account["balance_today_eur"]),
                            account["as_of"] and date.fromisoformat(account["as_of"]),
                        ) == (expected.balance, expected.balance_eur, expected.as_of), context
                    # The pot is the owner's, but its money isn't theirs alone.
                    if principal == home.owner:
                        assert accounts[home.savings]["in_net_worth"] == (view == "household")
                        assert _decimal(accounts[wise]["balance_today_eur"]) == Decimal("100.00")
                        # Cash, the ETF at 110 and the stock at 50 XTQ, 5 to the euro.
                        assert _decimal(accounts[broker]["balance_today_eur"]) == Decimal("750.00")


@pytest.mark.usefixtures("data")
async def test_net_worth_history_agrees_with_net_worth(
    home: Home, logins: dict[uuid.UUID, Login]
) -> None:
    await foreign_account(home)
    await broker_account(home)
    today = date.today()
    recent = today - timedelta(days=20)

    def by_id(accounts: list[schemas.NetWorthAccount]) -> dict[uuid.UUID, schemas.NetWorthAccount]:
        return {account.id: account for account in accounts}

    async with get_sessionmaker()() as session:
        for principal in principals(home):
            async with connected(logins[principal.user_id]) as client:
                for view in VIEWS:
                    context = (principal, view)
                    app = await net_worth(session, principal, today, view=view)
                    daily = outputs.NetWorthHistory.model_validate(
                        await call(client, "net_worth_history", every="day", view=view)
                    )
                    assert len(app.points) > 1, context
                    assert (daily.total, daily.points, daily.unconverted, daily.unpriced) == (
                        app.total,
                        app.points,
                        app.unconverted,
                        app.unpriced,
                    ), context
                    assert by_id(daily.accounts) == by_id(app.accounts), context

                    monthly = outputs.NetWorthHistory.model_validate(
                        await call(client, "net_worth_history", every="month", view=view)
                    )
                    assert monthly.points == [
                        p
                        for p in app.points
                        if (p.on + timedelta(days=1)).day == 1 or p.on == today
                    ], context

                    app = await net_worth(session, principal, today, recent, view=view)
                    weekly = outputs.NetWorthHistory.model_validate(
                        await call(
                            client, "net_worth_history", date_from=recent.isoformat(), view=view
                        )
                    )
                    assert weekly.every == "week", context
                    assert weekly.points == [
                        p for p in app.points if p.on.weekday() == 6 or p.on == today
                    ], context
                    assert weekly.points[-1].on == today, context
                    assert weekly.unconverted == app.unconverted, context
                    # Days without a rate for the owner's foreign account are left out.
                    if principal == home.owner:
                        assert daily.unconverted > 0, context


@pytest.mark.usefixtures("data")
async def test_investments_agree_with_the_investments_page(
    home: Home, logins: dict[uuid.UUID, Login]
) -> None:
    broker = await broker_account(home)
    today = date.today()
    recent = today - timedelta(days=30)

    async with get_sessionmaker()() as session:
        for principal in principals(home):
            overview = await investments(session, principal, months_until(today, 12))
            async with connected(logins[principal.user_id]) as client:
                for date_from in (None, recent):
                    context = (principal, date_from)
                    period = {"date_from": date_from.isoformat()} if date_from else {}
                    tool = outputs.Investments.model_validate(
                        await call(client, "investments", every="day", **period)
                    )
                    app = await investment_returns(session, principal, today, date_from)
                    assert app.accounts, context
                    assert (tool.months, tool.accounts) == (overview.months, overview.accounts)
                    assert tool.returns == app.accounts, context

                monthly = outputs.Investments.model_validate(await call(client, "investments"))
                app = await investment_returns(session, principal, today)
                assert monthly.every == "month"
                assert [account.points for account in monthly.returns] == [
                    [p for p in a.points if (p.on + timedelta(days=1)).day == 1 or p.on == today]
                    for a in app.accounts
                ]
                assert "date_to is before" in await failure(
                    client, "investments", date_from=today.isoformat(), date_to="2020-01-01"
                )
        everything = await investment_returns(session, home.owner, today)

    # Deposited 700 sixty days ago; 23 of interest; a 0.30 fee on the first trade.
    (shown,) = [account for account in everything.accounts if account.id == broker]
    assert (shown.date_from, shown.net_deposits) == (today - timedelta(days=60), Decimal(700))
    assert shown.breakdown is not None
    assert (shown.breakdown.interest, shown.breakdown.fees) == (Decimal(23), Decimal("-0.30"))
    assert shown.start_value is not None and shown.end_value is not None
    assert shown.breakdown.total == shown.end_value - shown.start_value - shown.net_deposits


@pytest.mark.usefixtures("data")
async def test_lists_agree_with_the_app(home: Home, logins: dict[uuid.UUID, Login]) -> None:
    async with get_sessionmaker()() as session:
        for principal in principals(home):
            async with connected(logins[principal.user_id]) as client:
                accounts = await call(client, "list_accounts")
                assert {uuid.UUID(a["id"]) for a in accounts["accounts"]} == set(
                    await session.scalars(listed_account_ids(principal))
                )

                every = await call(client, "list_categories", include_archived=True)
                assert {uuid.UUID(c["id"]) for c in every["categories"]} == set(
                    await household_categories(session, principal)
                )
                await session.execute(
                    update(Category)
                    .where(Category.id == home.categories["Rent & mortgage"])
                    .values(archived_at=date(2026, 10, 1))
                )
                await session.commit()
                listed = await call(client, "list_categories")
                assert len(listed["categories"]) == len(every["categories"]) - 1
                assert home.categories["Rent & mortgage"] not in {
                    uuid.UUID(c["id"]) for c in listed["categories"]
                }
                await session.execute(
                    update(Category)
                    .where(Category.id == home.categories["Rent & mortgage"])
                    .values(archived_at=None)
                )
                await session.commit()

                app = await list_recurring(session, principal)
                for include_suggested, reviews in (
                    (False, {Review.CONFIRMED}),
                    (True, {Review.CONFIRMED, Review.SUGGESTED}),
                ):
                    found = await call(
                        client, "recurring_payments", include_suggested=include_suggested
                    )
                    assert [
                        (p["name"], p["status"], p["next_expected_on"], p["expected_amount"])
                        for p in found["payments"]
                    ] == [
                        (
                            s.name,
                            s.status.value,
                            s.next_expected_on.isoformat(),
                            str(s.expected_amount),
                        )
                        for s in app
                        if s.review in reviews
                    ]
            names = {p["name"] for p in found["payments"]}
            assert names == (
                {"Netflix", "Gym"} if principal == home.owner else {"Netflix", "Spotify"}
            )


async def test_search_transactions_agrees_with_the_transactions_page(
    home: Home, logins: dict[uuid.UUID, Login], data: Data
) -> None:
    async with get_sessionmaker()() as session:
        pingo = await session.scalar(
            select(Counterparty.id).where(
                Counterparty.household_id == home.owner.household_id, Counterparty.name == "Pingo"
            )
        )
    assert pingo is not None
    cases: list[tuple[dict[str, Any], dict[str, Any]]] = [
        ({}, {}),
        ({"text": "pingo"}, {"q": "pingo"}),
        ({"kind": "income"}, {"kind": "income"}),
        ({"kind": "transfer"}, {"kind": "transfer"}),
        ({"category_id": str(home.categories["Food"])}, {"category_id": home.categories["Food"]}),
        ({"uncategorized": True}, {"uncategorized": True}),
        ({"merchant_id": str(pingo)}, {"counterparty_id": pingo}),
        (
            {"date_from": "2026-10-10", "date_to": "2026-10-15", "account_id": str(home.shared)},
            {"date_from": "2026-10-10", "date_to": "2026-10-15", "account_id": home.shared},
        ),
    ]
    for principal in principals(home):
        async with connected(logins[principal.user_id]) as client, api(principal) as page:
            for tool_arguments, page_params in cases:
                found = await call(client, "search_transactions", limit=200, **tool_arguments)
                response = await page.get(
                    "/api/finance/transactions", params={"limit": 200, **page_params}
                )
                expected = [item["id"] for item in response.json()["items"]]
                assert expected, (principal, page_params)
                assert [t["id"] for t in found["transactions"]] == expected, (
                    principal,
                    page_params,
                )
                assert found["matched"] == len(expected)
            # Euros at the day's rate, the cap, and only what the member may see.
            everything = await call(client, "search_transactions", text=" ", limit=200)
            assert {
                t["eur_amount"] for t in everything["transactions"] if t["currency"] == "XTQ"
            } == {"-10.00"}
            capped = await call(client, "search_transactions", limit=2)
            assert len(capped["transactions"]) == 2
            assert capped["matched"] == len(everything["transactions"])
            seen = {uuid.UUID(t["id"]) for t in everything["transactions"]}
            own, others = (
                (data.owner_private, data.member_private)
                if principal == home.owner
                else (data.member_private, data.owner_private)
            )
            assert own <= seen
            assert not others & seen

    # A category an AI suggested.
    async with connected(logins[home.owner.user_id]) as client:
        assert (await call(client, "search_transactions", ai_suggested=True))["matched"] == 0
        uncategorized = await call(client, "search_transactions", uncategorized=True, limit=1)
        [transaction] = uncategorized["transactions"]
        async with get_sessionmaker()() as session, session.begin():
            session.add(
                CategoryAssignment(
                    household_id=home.owner.household_id,
                    transaction_id=uuid.UUID(transaction["id"]),
                    category_id=home.categories["Groceries"],
                    source=Source.AI,
                )
            )
        suggested = await call(client, "search_transactions", ai_suggested=True)
        assert [
            (t["id"], t["category"], t["category_source"]) for t in suggested["transactions"]
        ] == [(transaction["id"], "Groceries", "ai")]


async def test_health_tools_agree_with_the_health_pages(
    home: Home, logins: dict[uuid.UUID, Login]
) -> None:
    """Each health tool gives what its page's API gives the same member; the household's other
    member gets their own (empty) health, never the owner's."""
    today = await seed_health(home.owner.user_id)
    night = today - timedelta(days=5)
    cases: list[tuple[str, dict[str, Any], str, dict[str, Any], str | None]] = [
        ("health_training", {"days": "90"}, "/api/health/training", {"days": "90"}, None),
        ("health_training", {"days": "all"}, "/api/health/training", {"days": "all"}, None),
        ("health_recovery", {"days": 30}, "/api/health/recovery", {"days": 30}, None),
        ("health_recovery", {"days": 90}, "/api/health/recovery", {"days": 90}, None),
        ("health_performance", {}, "/api/health/performance", {}, None),
        (
            "health_performance",
            {"period": "all"},
            "/api/health/performance",
            {"period": "all"},
            None,
        ),
        ("health_body", {"days": "90"}, "/api/health/body", {"days": "90"}, None),
        ("health_body", {}, "/api/health/body", {}, None),
        ("health_sleep", {"nights": 90}, "/api/health/sleep/trends", {"nights": 90}, "trends"),
        ("health_sleep", {}, "/api/health/sleep/night", {}, "night"),
        (
            "health_sleep",
            {"on": night.isoformat()},
            "/api/health/sleep/night",
            {"date": night.isoformat()},
            "night",
        ),
    ]
    for principal in principals(home):
        async with connected(logins[principal.user_id]) as client, api(principal) as page:
            for tool, arguments, path, params, part in cases:
                found = await call(client, tool, **arguments)
                response = await page.get(path, params=params)
                assert response.status_code == 200, (tool, response.text)
                context = (principal, tool, arguments)
                assert (found[part] if part else found) == response.json(), context
            if principal == home.member:
                assert (await call(client, "health_activities"))["matched"] == 0
                assert "No activity 1000" in await failure(
                    client, "health_activities", activity_id=1000
                )

    async with connected(logins[home.owner.user_id]) as client:
        sleep = await call(client, "health_sleep", on=night.isoformat())
        assert sleep["night"]["night"]["hrv"]["avg"] is not None
        assert (await call(client, "health_training"))["summary"]["fitness"] > 0

        # Activities: newest first, filtered, and one in full with its derived results and laps.
        everything = await call(client, "health_activities", limit=200)
        assert everything["matched"] == len(everything["activities"]) == 27
        started = [a["start_local"] or "" for a in everything["activities"] if a["start_local"]]
        assert started == sorted(started, reverse=True)
        runs = await call(client, "health_activities", sport="running", limit=200)
        assert runs["matched"] == 9  # eight runs and the triathlon's run
        assert {a["sport"] for a in runs["activities"]} == {"running"}
        recent = await call(
            client,
            "health_activities",
            date_from=(today - timedelta(days=10)).isoformat(),
            date_to=today.isoformat(),
            limit=200,
        )
        assert recent["matched"] == 4
        named = await call(client, "health_activities", text="triathlon", limit=1)
        assert named["matched"] == 4 and len(named["activities"]) == 1

        detail = (await call(client, "health_activities", activity_id=1000))["detail"]
        assert (detail["sport"], detail["has_derived"], len(detail["laps"])) == ("running", True, 2)
        assert detail["best_efforts"] == {"1000": 230.0, "5000": 1240.0 + 1000 % 9}
        assert len(detail["power_curve"]) == len(detail["curve_durations_s"])
        without_file = (await call(client, "health_activities", activity_id=1003))["detail"]
        assert (without_file["has_derived"], without_file["hr_load"], without_file["laps"]) == (
            False,
            None,
            [],
        )
        parent = (await call(client, "health_activities", activity_id=2000))["detail"]
        assert (parent["is_parent"], parent["child_ids"]) == (True, [2001, 2002, 2003])


@pytest.mark.usefixtures("data")
async def test_uncategorized_overview_adds_up_to_spending(
    home: Home, logins: dict[uuid.UUID, Login]
) -> None:
    async with get_sessionmaker()() as session:
        for principal in principals(home):
            async with connected(logins[principal.user_id]) as client:
                for view in VIEWS:
                    overview = await call(
                        client,
                        "uncategorized_overview",
                        date_from="2026-09-01",
                        date_to="2026-10-31",
                        view=view,
                    )
                    spending = await get_spending(
                        session, principal, months=2, until=OCTOBER, view=view
                    )
                    context = (principal, view)
                    assert Decimal(overview["spent"]) == sum(spending.uncategorized), context
                    assert overview["spent"] != "0.00", context
                    assert overview["group_count"] == len(overview["groups"]), context
                    assert sum(Decimal(g["spent"]) for g in overview["groups"]) == Decimal(
                        overview["spent"]
                    )
                    assert (
                        sum(g["transactions"] for g in overview["groups"])
                        == (overview["transactions"])
                    )
                    # The XTN payment, on the owner's shared account.
                    mine = principal == home.owner or view == "household"
                    assert overview["unconverted"] == (1 if mine else 0), context
                    if principal == home.member:
                        [pingo] = [g for g in overview["groups"] if g["merchant_id"]]
                        assert (pingo["name"], pingo["transactions"], pingo["spent"]) == (
                            "Pingo",
                            2,
                            "50.00",
                        )
                limited = await call(client, "uncategorized_overview", limit=1)
                assert len(limited["groups"]) == 1
                assert limited["group_count"] >= 1


# query_sql: one read-only query, nothing else.


async def test_query_sql_reads_the_views(home: Home, logins: dict[uuid.UUID, Login]) -> None:
    async with connected(logins[home.owner.user_id]) as client:
        everything = await call(client, "search_transactions", limit=1)
        result = await call(client, "query_sql", query="SELECT count(*) AS n FROM transactions")
        assert result == {"columns": ["n"], "rows": [[everything["matched"]]], "truncated": False}

        result = await call(
            client,
            "query_sql",
            query="SELECT 1.50::numeric AS d, date '2026-10-01' AS day, 'x%y' AS p,"
            " 'ab' LIKE 'a%' AS liked ;\n",
        )
        assert result["rows"] == [["1.50", "2026-10-01", "x%y", True]]

        result = await call(client, "query_sql", query="SELECT generate_series(1, 600) AS n")
        assert len(result["rows"]) == 500
        assert result["truncated"] is True


@pytest.mark.parametrize(
    ("statement", "message"),
    [
        (
            "INSERT INTO core.ai_calls (role_name, tool, arguments) VALUES ('x', 'y', '{}')",
            "syntax",
        ),
        ("SET statement_timeout = 0", "syntax"),
        (
            "WITH gone AS (DELETE FROM core.ai_calls RETURNING 1) SELECT * FROM gone",
            "permission denied",  # the role's grants refuse it first; the wrapper would too
        ),
        ("SELECT 1; SELECT 2", "syntax"),
        # Closing the wrapper and chaining statements: one prepared statement can't hold them.
        ("SELECT 1) q; DELETE FROM core.ai_calls; SELECT * FROM (SELECT 1", "multiple commands"),
        ("SELECT analytics.record_call('query_sql', '{}', 0)", "read-only transaction"),
        ("SELECT * FROM analytics.suggest_category('{}', gen_random_uuid())", "read-only"),
        ("SELECT * FROM finance.transactions", "permission denied"),
        (" ; ", "empty"),
    ],
)
async def test_query_sql_runs_only_one_read_only_query(
    home: Home, logins: dict[uuid.UUID, Login], statement: str, message: str
) -> None:
    login = logins[home.owner.user_id]
    async with connected(login) as client:
        assert message in await failure(client, "query_sql", query=statement)
    async with get_sessionmaker()() as session:
        calls = (await session.scalars(select(AiCall).where(AiCall.role_name == login.role))).all()
    assert [(c.tool, c.arguments, c.row_count) for c in calls] == [
        ("query_sql", {"query": statement}, None)
    ]


@pytest.mark.parametrize(
    ("statement", "message"),
    [
        (
            "INSERT INTO core.ai_calls (role_name, tool, arguments) VALUES ('x', 'y', '{}')",
            "syntax",
        ),
        ("DELETE FROM core.ai_calls", "syntax"),
        ("WITH gone AS (DELETE FROM core.ai_calls RETURNING 1) SELECT * FROM gone", "top level"),
        ("SELECT 1) q; DELETE FROM core.ai_calls; SELECT * FROM (SELECT 1", "multiple commands"),
    ],
)
def test_the_wrapper_alone_lets_no_write_through(
    migrated_database: str, statement: str, message: str
) -> None:
    """Even as the superuser, in a read-write transaction: the role and the read-only
    transaction are two more layers."""
    with psycopg.connect(migrated_database) as connection:
        with pytest.raises(psycopg.Error, match=message):
            connection.execute(wrap(statement), [501])
        connection.rollback()


async def test_query_sql_times_out(
    home: Home, logins: dict[uuid.UUID, Login], monkeypatch: pytest.MonkeyPatch
) -> None:
    assert server.QUERY_TIMEOUT == "5s"
    monkeypatch.setattr(server, "QUERY_TIMEOUT", "200ms")
    async with connected(logins[home.owner.user_id]) as client:
        error = await failure(client, "query_sql", query="SELECT pg_sleep(5)")
        assert "statement timeout" in error
        # The timeout was that call's own.
        assert (await call(client, "query_sql", query="SELECT 1 AS one"))["rows"] == [[1]]


# The audit.


async def test_every_call_is_audited(home: Home, logins: dict[uuid.UUID, Login]) -> None:
    login = logins[home.member.user_id]
    async with connected(login) as client:
        accounts = await call(client, "list_accounts")
        await add(home, "-3.00", 2, description="PINGO DOCE")
        await call(client, "search_transactions", text="pingo", limit=5)
        await call(client, "spending_summary", months=1, until="2026-10-01")
        await failure(client, "query_sql", query="DELETE FROM core.ai_calls")
        # Arguments the schema refuses never reach the tool.
        await failure(client, "spending_summary", months=99)
    async with get_sessionmaker()() as session:
        calls = (
            await session.scalars(
                select(AiCall).where(AiCall.role_name == login.role).order_by(AiCall.at, AiCall.id)
            )
        ).all()
    assert [(c.tool, c.arguments, c.row_count) for c in calls] == [
        ("list_accounts", {}, len(accounts["accounts"])),
        (
            "search_transactions",
            {
                "text": "pingo",
                "date_from": None,
                "date_to": None,
                "account_id": None,
                "category_id": None,
                "merchant_id": None,
                "kind": None,
                "uncategorized": False,
                "ai_suggested": False,
                "limit": 5,
            },
            1,
        ),
        ("spending_summary", {"months": 1, "until": "2026-10-01", "view": "personal"}, 0),
        ("query_sql", {"query": "DELETE FROM core.ai_calls"}, None),
    ]


# Suggestions: the one write.


async def suggest(
    login: Login, ids: list[uuid.UUID], category: uuid.UUID, *, read_only: bool = False
) -> tuple[int, int]:
    """analytics.suggest_category, called as the member's login."""
    connection = await psycopg.AsyncConnection.connect(login.dsn, autocommit=True)
    async with connection, connection.transaction():
        mode = "SET TRANSACTION READ ONLY" if read_only else "SET TRANSACTION READ WRITE"
        await connection.execute(mode)
        cursor = await connection.execute(
            "SELECT written, skipped FROM analytics.suggest_category(%s, %s)", [ids, category]
        )
        row = await cursor.fetchone()
    assert row is not None
    return row


async def assigned(ids: list[uuid.UUID]) -> dict[uuid.UUID, tuple[uuid.UUID, Source]]:
    async with get_sessionmaker()() as session:
        rows = await session.execute(
            select(
                CategoryAssignment.transaction_id,
                CategoryAssignment.category_id,
                CategoryAssignment.source,
            ).where(CategoryAssignment.transaction_id.in_(ids))
        )
    return {transaction: (category, source) for transaction, category, source in rows}


async def test_suggest_category_takes_only_what_an_ai_may_categorize(
    home: Home, logins: dict[uuid.UUID, Login], data: Data
) -> None:
    household = home.owner.household_id
    groceries, food = home.categories["Groceries"], home.categories["Food"]
    free = await add(home, "-12.00", 3)
    refund = await add(home, "4.00", 3)  # money in may take one too
    pending = await add(home, "-5.00", 3, status=TransactionStatus.PENDING)
    out = await add(home, "-70.00", 4)
    into = await add(home, "70.00", 4, account=home.private)
    decided = {
        source: await add(home, "-9.00", 5)
        for source in (Source.MANUAL, Source.RULE, Source.COUNTERPARTY)
    }
    earlier = await add(home, "-8.00", 6)
    await save(
        Transfer(household_id=household, outgoing_id=out, incoming_id=into, source=Source.AUTO),
        *(
            CategoryAssignment(
                household_id=household, transaction_id=transaction, category_id=food, source=source
            )
            for source, transaction in [*decided.items(), (Source.AI, earlier)]
        ),
    )
    hers = min(data.member_private)
    asked = [free, refund, pending, out, into, *decided.values(), earlier, hers, uuid.uuid4()]

    # Twice in the list counts once. The other member's private transaction isn't the owner's
    # to see, and a made-up ID is skipped like it.
    assert await suggest(logins[home.owner.user_id], [*asked, free], groceries) == (3, 8)

    found = await assigned(asked)
    assert {t for t, (_, source) in found.items() if source is Source.AI} == {free, refund, earlier}
    assert {found[t] for t in (free, refund, earlier)} == {(groceries, Source.AI)}
    assert {found[t] for t in decided.values()} == {(food, source) for source in decided}
    assert not {pending, out, into, hers} & set(found)

    # The member sees their own private account, and not the owner's.
    member = logins[home.member.user_id]
    assert await suggest(member, [hers, *data.owner_private], groceries) == (1, 3)
    assert (await assigned([hers]))[hers] == (groceries, Source.AI)


async def test_suggest_category_needs_a_usable_category_and_a_read_write_transaction(
    home: Home, logins: dict[uuid.UUID, Login], migrated_database: str
) -> None:
    owner = logins[home.owner.user_id]
    groceries, rent = home.categories["Groceries"], home.categories["Rent & mortgage"]
    free = await add(home, "-12.00", 3)
    async with get_sessionmaker()() as session, session.begin():
        await session.execute(
            update(Category).where(Category.id == rent).values(archived_at=date(2026, 10, 1))
        )
    elsewhere = (await make_home()).categories["Groceries"]

    for category, read_only, message in (
        (rent, False, "archived"),
        (elsewhere, False, "isn't the household's"),
        (uuid.uuid4(), False, "isn't the household's"),
        (groceries, True, "read-only transaction"),
    ):
        with pytest.raises(psycopg.Error, match=message):
            await suggest(owner, [free], category, read_only=read_only)
    # Only an AI login may call it: the app's own role is refused too.
    async with await psycopg.AsyncConnection.connect(migrated_database) as connection:
        with pytest.raises(psycopg.Error, match="not an AI login"):
            await connection.execute(
                "SELECT analytics.suggest_category(%s, %s)", [[free], groceries]
            )
    assert await assigned([free]) == {}


async def test_suggest_categories_takes_a_merchants_or_a_descriptions_spending(
    home: Home, logins: dict[uuid.UUID, Login]
) -> None:
    household = home.owner.household_id
    taxi, pharmacy = home.categories["Taxi & ride-hailing"], home.categories["Pharmacy"]
    gifts, rent = home.categories["Gifts & donations"], home.categories["Rent & mortgage"]
    bolt = Counterparty(household_id=household, name="Bolt")
    await save(bolt)
    rides = [await add(home, "-6.00", day) for day in (1, 2)]
    bolt_refund = await add(home, "6.00", 3)  # money in: a merchant's group is its spending
    bolt_manual = await add(home, "-7.00", 4)
    chemist = [
        await add(home, "-15.00", 5, description="COMPRA 1234 FARMÁCIA"),
        await add(home, "-3.50", 6, description="compra 98 farmacia "),
    ]
    bakery = await add(home, "-20.00", 7, description="COMPRA 55 PADARIA")
    await save(
        *(
            TransactionAnnotation(
                household_id=household, transaction_id=transaction, counterparty_id=bolt.id
            )
            for transaction in [*rides, bolt_refund, bolt_manual]
        ),
        CategoryAssignment(
            household_id=household,
            transaction_id=bolt_manual,
            category_id=gifts,
            source=Source.MANUAL,
        ),
    )
    everything = [*rides, bolt_refund, bolt_manual, *chemist, bakery]
    login = logins[home.owner.user_id]
    first = [
        {"category_id": str(taxi), "merchant_id": str(bolt.id)},
        {"category_id": str(pharmacy), "description": "compra farmacia"},
    ]

    async with connected(login) as client:
        result = await call(client, "suggest_categories", suggestions=first)
        assert [(r["written"], r["skipped"]) for r in result["results"]] == [(2, 0), (2, 0)]
        assert (result["written"], result["skipped"]) == (4, 0)
        overview = await call(client, "uncategorized_overview", view="household")
        assert [g["name"] for g in overview["groups"]] == ["compra padaria"]

        # Again: it replaces the AI's own suggestions. An example description works as well as
        # the group's name, and listed IDs skip what the user decided.
        again = await call(
            client,
            "suggest_categories",
            suggestions=[
                {"category_id": str(gifts), "merchant_id": str(bolt.id)},
                {"category_id": str(pharmacy), "description": "COMPRA 77 PADARIA"},
                {"category_id": str(taxi), "transaction_ids": [str(bolt_manual), str(bolt_refund)]},
            ],
        )
        assert [(r["written"], r["skipped"]) for r in again["results"]] == [(2, 0), (1, 0), (1, 1)]
        suggested = await call(client, "search_transactions", ai_suggested=True)
        assert suggested["matched"] == 6

        # All or nothing: an archived category fails the whole call.
        async with get_sessionmaker()() as session, session.begin():
            await session.execute(
                update(Category).where(Category.id == rent).values(archived_at=date(2026, 10, 1))
            )
        error = await failure(
            client,
            "suggest_categories",
            suggestions=[
                {"category_id": str(taxi), "merchant_id": str(bolt.id)},
                {"category_id": str(rent), "transaction_ids": [str(bakery)]},
            ],
        )
        assert "archived" in error
        for wrong in ({"category_id": str(taxi)}, {**first[0], "description": "bolt"}):
            assert "Give one of" in await failure(client, "suggest_categories", suggestions=[wrong])

    assert await assigned(everything) == {
        rides[0]: (gifts, Source.AI),
        rides[1]: (gifts, Source.AI),
        bolt_refund: (taxi, Source.AI),
        bolt_manual: (gifts, Source.MANUAL),
        chemist[0]: (pharmacy, Source.AI),
        chemist[1]: (pharmacy, Source.AI),
        bakery: (pharmacy, Source.AI),
    }
    async with get_sessionmaker()() as session:
        calls = (
            await session.scalars(
                select(AiCall)
                .where(AiCall.role_name == login.role, AiCall.tool == "suggest_categories")
                .order_by(AiCall.at, AiCall.id)
            )
        ).all()
    assert [c.row_count for c in calls] == [4, 4, None]
    assert calls[0].arguments == {"suggestions": first}


async def test_the_categorize_prompt_walks_through_the_tools() -> None:
    async with Client(build_server("postgresql://unused")) as client:
        [prompt] = (await client.list_prompts()).prompts
        assert prompt.name == "categorize_uncategorized"
        [message] = (await client.get_prompt(prompt.name)).messages
    text = getattr(message.content, "text", "")
    steps = ["uncategorized_overview", "list_categories", "suggest_categories"]
    assert sorted(steps, key=text.index) == steps


# Starting the server.


def test_the_server_starts_only_when_switched_on(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("HUBNISIO_DATABASE_URL", "postgresql://unused")
    for enabled, dsn_file, message in (
        ("false", None, "AI access is off"),
        ("true", None, "Set HUBNISIO_AI_DSN_FILE"),
        ("true", tmp_path / "missing", "Set HUBNISIO_AI_DSN_FILE"),
    ):
        monkeypatch.setenv("HUBNISIO_AI_ENABLED", enabled)
        # Set even when empty: a value in .env would count otherwise.
        monkeypatch.setenv("HUBNISIO_AI_DSN_FILE", str(dsn_file or ""))
        get_settings.cache_clear()
        assert main() == 1
        assert message in capsys.readouterr().err
    get_settings.cache_clear()


def test_the_server_refuses_a_login_that_is_not_a_members(
    migrated_database: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    dsn_file = tmp_path / "admin"
    dsn_file.write_text(migrated_database)
    monkeypatch.setenv("HUBNISIO_AI_ENABLED", "true")
    monkeypatch.setenv("HUBNISIO_AI_DSN_FILE", str(dsn_file))
    get_settings.cache_clear()
    assert main() == 1
    assert "isn't a member's AI login" in capsys.readouterr().err
    get_settings.cache_clear()


async def test_the_server_runs_over_stdio(
    home: Home, logins: dict[uuid.UUID, Login], tmp_path: Path
) -> None:
    """As Claude starts it: `python -m hubnisio.ai`, speaking MCP on stdin and stdout."""
    login = logins[home.owner.user_id]
    environment = {
        **os.environ,
        "HUBNISIO_AI_ENABLED": "true",
        "HUBNISIO_AI_DSN_FILE": str(tmp_path / login.role),
    }
    parameters = StdioServerParameters(
        command=sys.executable, args=["-m", "hubnisio.ai"], env=environment
    )
    async with Client(parameters) as client:
        assert {tool.name for tool in (await client.list_tools()).tools} == TOOLS
        for tool in (await client.list_tools()).tools:
            assert tool.annotations is not None, tool.name
            writes = tool.name == "suggest_categories"
            assert tool.annotations.read_only_hint is not writes, tool.name
        assert (await call(client, "list_accounts"))["accounts"]


def _decimal(value: str | None) -> Decimal | None:
    return None if value is None else Decimal(value)
