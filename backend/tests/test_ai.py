"""The MCP server (ADR-0006): each tool gives the app's own figures for the same member and view,
query_sql runs one read-only query and nothing else, and every call is audited."""

import os
import sys
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import psycopg
import pytest
from analytics_data import OCTOBER, SEPTEMBER, VIEWS, Data, Login
from households import Home, add, api
from mcp import Client, StdioServerParameters
from sqlalchemy import select, update

from hubnisio.ai import server
from hubnisio.ai.__main__ import main
from hubnisio.ai.server import build_server, wrap
from hubnisio.core.auth import Principal
from hubnisio.core.db import get_sessionmaker
from hubnisio.core.models import AiCall
from hubnisio.core.settings import get_settings
from hubnisio.finance import schemas
from hubnisio.finance.budgets import budgets_for_month
from hubnisio.finance.insights.net_worth import net_worth
from hubnisio.finance.insights.spending import household_categories
from hubnisio.finance.insights_api import get_cash_flow, get_spending
from hubnisio.finance.models import Category, CategoryAssignment, Counterparty, Review, Source
from hubnisio.finance.recurring_api import list_recurring
from hubnisio.finance.scoping import listed_account_ids

pytestmark = pytest.mark.anyio

TOOLS = {
    "balances",
    "budget_status",
    "cashflow",
    "list_accounts",
    "list_categories",
    "query_sql",
    "recurring_payments",
    "search_transactions",
    "spending_summary",
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
            assert tool.annotations is not None and tool.annotations.read_only_hint, tool.name
        assert (await call(client, "list_accounts"))["accounts"]


def _decimal(value: str | None) -> Decimal | None:
    return None if value is None else Decimal(value)
