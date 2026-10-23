"""AI access (ADR-0006): a member's Postgres login reads the `analytics` views and nothing else,
never sees another member's private accounts, and gets the app's own figures."""

import uuid
from collections import defaultdict
from collections.abc import Sequence
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import psycopg
import pytest
from analytics_data import OCTOBER, SEPTEMBER, VIEWS, Data, Login, email_of
from households import Home, api
from psycopg import errors, sql
from psycopg.abc import QueryNoTemplate as Query
from sqlalchemy import select

from hubnisio.cli import ai_login
from hubnisio.core.db import get_sessionmaker
from hubnisio.core.models import AiCall, AiLogin
from hubnisio.finance import schemas
from hubnisio.finance.balances import BOOKED_FIRST, SPENDABLE_FIRST, latest_balances
from hubnisio.finance.budgets import BudgetSpec, budgets_for_month, compute_budgets
from hubnisio.finance.insights.spending import CategoryInfo, MonthlySums, monthly_sums
from hubnisio.finance.kinds import kind_is
from hubnisio.finance.models import (
    CategoryKind,
    Overspend,
    TransactionKind,
)
from hubnisio.finance.scoping import View, listed_account_ids
from hubnisio.finance.transactions_api import transactions_query

pytestmark = pytest.mark.anyio

ANALYTICS_VIEWS = {
    "accounts",
    "balances",
    "budget_limits",
    "budgets",
    "categories",
    "me",
    "merchants",
    "monthly_category_spend",
    "recurring_payments",
    "transactions",
    "visible_accounts",
}


def rows(login: Login, query: Query, params: Sequence[Any] = ()) -> list[tuple[Any, ...]]:
    """As the member's login, in its default (read-only) transaction."""
    with psycopg.connect(login.dsn, autocommit=True) as connection:
        return connection.execute(query, params).fetchall()


def ids(login: Login, query: Query) -> set[Any]:
    return {row[0] for row in rows(login, query)}


def admin_rows(
    database_url: str, query: Query, params: Sequence[Any] = ()
) -> list[tuple[Any, ...]]:
    with psycopg.connect(database_url, autocommit=True) as connection:
        return connection.execute(query, params).fetchall()


def refused(login: Login, statement: Query, error: type[psycopg.Error]) -> None:
    """The statement fails even in a read-write transaction."""
    with psycopg.connect(login.dsn) as connection:
        connection.execute("SET TRANSACTION READ WRITE")
        with pytest.raises(error):
            connection.execute(statement)
        connection.rollback()


# Loading the views into the app's own dataclasses, as the MCP server will.


def view_sums(login: Login, view: View) -> MonthlySums:
    sums = MonthlySums()
    for month, category_id, kind, eur, unconverted in rows(
        login,
        "SELECT month, category_id, kind, eur, unconverted"
        " FROM analytics.monthly_category_spend WHERE view = %s",
        [view],
    ):
        sums.add(month, category_id, TransactionKind(kind), eur, unconverted)
    return sums


def view_categories(login: Login) -> dict[uuid.UUID, CategoryInfo]:
    return {
        id_: CategoryInfo(id_, name, CategoryKind(kind), parent_id, position)
        for id_, name, kind, parent_id, position in rows(
            login, "SELECT id, name, kind, parent_id, position FROM analytics.categories"
        )
    }


def view_budgets(login: Login, view: View, month: date) -> schemas.BudgetsOut:
    limits: dict[uuid.UUID, list[tuple[date, Decimal]]] = defaultdict(list)
    for budget_id, starts_on, amount in rows(
        login, "SELECT budget_id, starts_on, amount FROM analytics.budget_limits"
    ):
        limits[budget_id].append((starts_on, amount))
    specs = [
        BudgetSpec(category_id, rollover, Overspend(overspend), limits[id_])
        for id_, category_id, rollover, overspend in rows(
            login, "SELECT id, category_id, rollover, overspend FROM analytics.budgets"
        )
    ]
    return compute_budgets(month, specs, view_categories(login), view_sums(login, view))


# Security.


async def test_a_login_reads_only_the_analytics_views(
    home: Home, logins: dict[uuid.UUID, Login], migrated_database: str
) -> None:
    login = logins[home.member.user_id]
    views = admin_rows(
        migrated_database,
        "SELECT c.relname, c.reloptions FROM pg_class c"
        " JOIN pg_namespace n ON n.oid = c.relnamespace"
        " WHERE n.nspname = 'analytics' AND c.relkind = 'v'",
    )
    assert {name for name, _ in views} == ANALYTICS_VIEWS
    for name, options in views:
        assert "security_barrier=true" in options, name
        rows(login, sql.SQL("SELECT count(*) FROM analytics.{}").format(sql.Identifier(name)))

    others = admin_rows(
        migrated_database,
        "SELECT table_schema, table_name FROM information_schema.tables"
        " WHERE table_schema NOT IN ('analytics', 'information_schema', 'pg_catalog')",
    )
    assert {schema for schema, _ in others} >= {"core", "finance", "procrastinate", "public"}
    for schema, table in others:
        query = sql.SQL("SELECT 1 FROM {}.{} LIMIT 1").format(
            sql.Identifier(schema), sql.Identifier(table)
        )
        with pytest.raises(errors.InsufficientPrivilege):
            rows(login, query)


async def test_a_login_writes_nothing(home: Home, logins: dict[uuid.UUID, Login]) -> None:
    login = logins[home.member.user_id]
    [settings] = rows(
        login,
        "SELECT current_setting('transaction_read_only'), current_setting('statement_timeout'),"
        " current_setting('search_path')",
    )
    assert settings == ("on", "30s", "analytics")
    with pytest.raises(errors.ReadOnlySqlTransaction):
        rows(login, "CREATE TEMP TABLE scratch (id int)")

    # The grants hold in a read-write transaction too.
    refused(login, "UPDATE finance.transactions SET amount = 0", errors.InsufficientPrivilege)
    refused(
        login,
        "INSERT INTO core.ai_calls (role_name, tool, arguments) VALUES ('x', 'y', '{}')",
        errors.InsufficientPrivilege,
    )
    refused(login, "CREATE TABLE analytics.notes (id int)", errors.InsufficientPrivilege)
    refused(login, "CREATE TABLE public.notes (id int)", errors.InsufficientPrivilege)
    refused(login, "CREATE VIEW analytics.mine AS SELECT 1", errors.InsufficientPrivilege)
    # The views aren't updatable, and the group may only read them anyway.
    for name in ANALYTICS_VIEWS:
        for privilege in ("INSERT", "UPDATE", "DELETE", "TRUNCATE"):
            [(granted,)] = rows(
                login,
                "SELECT has_table_privilege(%s, %s, %s)",
                [login.role, f"analytics.{name}", privilege],
            )
            assert granted is False, (name, privilege)


async def test_record_call_writes_the_login_and_nothing_else_can(
    home: Home, logins: dict[uuid.UUID, Login], migrated_database: str
) -> None:
    login = logins[home.member.user_id]
    with psycopg.connect(login.dsn) as connection:
        connection.execute("SET TRANSACTION READ WRITE")
        connection.execute(
            "SELECT analytics.record_call('search_transactions', '{\"q\": \"pingo\"}', 3)"
        )
    async with get_sessionmaker()() as session:
        calls = (await session.scalars(select(AiCall).where(AiCall.role_name == login.role))).all()
    assert [(c.tool, c.arguments, c.row_count) for c in calls] == [
        ("search_transactions", {"q": "pingo"}, 3)
    ]

    # Not in a read-only transaction, so a read-only query can't call it.
    with pytest.raises(errors.ReadOnlySqlTransaction):
        rows(login, "SELECT analytics.record_call('query_sql', '{}', 0)")
    # Not for a role that isn't an AI login, superuser included.
    with pytest.raises(errors.InsufficientPrivilege, match="is not an AI login"):
        admin_rows(migrated_database, "SELECT analytics.record_call('x', '{}', 0)")
    [(public,)] = admin_rows(
        migrated_database,
        "SELECT has_function_privilege("
        "'public', 'analytics.record_call(text, jsonb, integer)', 'EXECUTE')",
    )
    assert public is False


async def test_a_member_cannot_act_as_another(home: Home, logins: dict[uuid.UUID, Login]) -> None:
    login, other = logins[home.member.user_id], logins[home.owner.user_id]
    for statement in (
        sql.SQL("SET ROLE {}").format(sql.Identifier(other.role)),
        sql.SQL("SELECT set_config('role', {}, false)").format(sql.Literal(other.role)),
        sql.SQL("SET SESSION AUTHORIZATION {}").format(sql.Identifier(other.role)),
        sql.SQL("SELECT set_config('session_authorization', {}, false)").format(
            sql.Literal(other.role)
        ),
    ):
        with pytest.raises(errors.InsufficientPrivilege):
            rows(login, statement)

    # Its group is allowed, and changes nothing: the views follow the session's login.
    with psycopg.connect(login.dsn, autocommit=True) as connection:
        connection.execute("SET ROLE hub_ai")
        assert connection.execute("SELECT user_id FROM analytics.me").fetchall() == [
            (home.member.user_id,)
        ]


async def test_no_view_shows_another_members_private_accounts(
    home: Home, logins: dict[uuid.UUID, Login], data: Data
) -> None:
    for principal, own, others, their_rows in (
        (home.owner, home.private, data.hers, data.member_private),
        (home.member, data.hers, home.private, data.owner_private),
    ):
        login = logins[principal.user_id]
        assert ids(login, "SELECT user_id FROM analytics.me") == {principal.user_id}
        for query in (
            "SELECT account_id FROM analytics.visible_accounts",
            "SELECT id FROM analytics.accounts",
            "SELECT account_id FROM analytics.transactions",
            "SELECT account_id FROM analytics.balances",
            "SELECT account_id FROM analytics.recurring_payments",
        ):
            seen = ids(login, query)
            assert own in seen, query
            assert others not in seen, query
        assert ids(login, "SELECT transfer_account_id FROM analytics.transactions") <= ids(
            login, "SELECT id FROM analytics.accounts"
        ) | {None}
        assert not ids(login, "SELECT id FROM analytics.transactions") & their_rows
    # Pingo: the owner's shared and private payments; for the member, the shared and her own.
    for principal, count in ((home.owner, 2), (home.member, 3)):
        assert rows(logins[principal.user_id], "SELECT transactions FROM analytics.merchants") == [
            (count,)
        ]
    # Hidden accounts keep their history but have no balance.
    login = logins[home.owner.user_id]
    assert rows(login, "SELECT hidden FROM analytics.accounts WHERE id = %s", [data.hidden]) == [
        (True,)
    ]
    assert data.hidden in ids(login, "SELECT account_id FROM analytics.transactions")
    assert data.hidden not in ids(login, "SELECT account_id FROM analytics.balances")


async def test_revoking_a_login_cuts_it_off(
    home: Home, logins: dict[uuid.UUID, Login], tmp_path: Path, migrated_database: str
) -> None:
    login = logins[home.member.user_id]
    email = await email_of(home.member)
    assert await ai_login(email, revoke=False) == 1  # one login per member
    assert await ai_login("nobody@example.com", revoke=False) == 1
    with psycopg.connect(login.dsn) as connection:
        connection.execute("SET TRANSACTION READ WRITE")
        connection.execute("SELECT analytics.record_call('list_accounts', '{}', 1)")

    open_session = psycopg.connect(login.dsn, autocommit=True)
    try:
        assert await ai_login(email, revoke=True) == 0
        with pytest.raises(psycopg.OperationalError):
            open_session.execute("SELECT 1 FROM analytics.me")
    finally:
        open_session.close()
    with pytest.raises(psycopg.OperationalError):
        psycopg.connect(login.dsn)
    assert not (tmp_path / login.role).exists()
    assert (
        admin_rows(migrated_database, "SELECT 1 FROM pg_roles WHERE rolname = %s", [login.role])
        == []
    )
    async with get_sessionmaker()() as session:
        assert await session.get(AiLogin, login.role) is None
        # The audit outlives the login.
        assert await session.scalar(select(AiCall.tool).where(AiCall.role_name == login.role)) == (
            "list_accounts"
        )
    assert await ai_login(email, revoke=True) == 1


# Agreement with the app.


@pytest.mark.usefixtures("data")
async def test_monthly_category_spend_agrees_with_monthly_sums(
    home: Home, logins: dict[uuid.UUID, Login]
) -> None:
    async with get_sessionmaker()() as session:
        for principal in (home.owner, home.member):
            for view in VIEWS:
                app = await monthly_sums(session, principal, SEPTEMBER, OCTOBER, view=view)
                sums = view_sums(logins[principal.user_id], view)
                assert dict(sums.by_category) == dict(app.by_category), (principal, view)
                assert dict(sums.uncategorized) == dict(app.uncategorized), (principal, view)
                assert sums.unconverted == app.unconverted, (principal, view)

    # The pot example, for the owner: in Mine the 300 moved in, less 50 back, is Rent.
    owner = view_sums(logins[home.owner.user_id], "personal")
    rent = home.categories["Rent & mortgage"]
    assert owner.by_category[(OCTOBER, rent)] == Decimal("-1200.00") + 600 - 300 + 50
    assert owner.unconverted == 1  # the XTN payment


@pytest.mark.usefixtures("data")
async def test_the_kind_agrees_with_the_app(home: Home, logins: dict[uuid.UUID, Login]) -> None:
    async with get_sessionmaker()() as session:
        for principal in (home.owner, home.member):
            login = logins[principal.user_id]
            for kind in TransactionKind:
                query = transactions_query(principal).where(kind_is(kind))
                expected = {row.Transaction.id for row in await session.execute(query)}
                assert expected, kind
                assert (
                    ids(
                        login,
                        sql.SQL("SELECT id FROM analytics.transactions WHERE kind = {}").format(
                            sql.Literal(kind.value)
                        ),
                    )
                    == expected
                ), (principal, kind)
            async with api(principal) as client:
                response = await client.get("/api/finance/transactions", params={"limit": 200})
            listed = {item["id"]: item["kind"] for item in response.json()["items"]}
            assert {
                str(id_): kind
                for id_, kind in rows(login, "SELECT id, kind FROM analytics.transactions")
            } == listed


@pytest.mark.usefixtures("data")
async def test_budgets_and_balances_agree_with_the_app(
    home: Home, logins: dict[uuid.UUID, Login]
) -> None:
    async with get_sessionmaker()() as session:
        for principal in (home.owner, home.member):
            login = logins[principal.user_id]
            for view in VIEWS:
                app = await budgets_for_month(session, principal, OCTOBER, view=view)
                assert app.overall is not None and app.budgets
                assert view_budgets(login, view, OCTOBER) == app, (principal, view)

            listed = list(await session.scalars(listed_account_ids(principal)))
            spendable = await latest_balances(session, listed, SPENDABLE_FIRST)
            booked = await latest_balances(session, listed, BOOKED_FIRST)
            expected = {
                account: (
                    snapshot.amount,
                    snapshot.balance_type,
                    snapshot.currency,
                    booked[account].amount,
                    booked[account].balance_type,
                    booked[account].currency,
                    booked[account].reference_date,
                    snapshot.fetched_at,
                )
                for account, snapshot in spendable.items()
            }
            assert {
                row[0]: row[1:]
                for row in rows(
                    login,
                    "SELECT account_id, balance, balance_type, currency, booked_balance,"
                    " booked_balance_type, booked_currency, reference_date, fetched_at"
                    " FROM analytics.balances",
                )
            } == expected
