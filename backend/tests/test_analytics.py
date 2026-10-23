"""AI access (ADR-0006): a member's Postgres login reads the `analytics` views and nothing else,
never sees another member's private accounts, and gets the app's own figures."""

import uuid
from collections import defaultdict
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import psycopg
import pytest
from households import Home, add, api
from psycopg import errors, sql
from psycopg.abc import QueryNoTemplate as Query
from sqlalchemy import delete, select, update
from sqlalchemy.dialects.postgresql import insert

from hubnisio.cli import ai_login, ai_role_name
from hubnisio.core.auth import Principal
from hubnisio.core.db import get_sessionmaker
from hubnisio.core.models import AiCall, AiLogin, Household, User
from hubnisio.core.settings import get_settings
from hubnisio.finance import schemas
from hubnisio.finance.balances import BOOKED_FIRST, SPENDABLE_FIRST, latest_balances
from hubnisio.finance.budgets import BudgetSpec, budgets_for_month, compute_budgets
from hubnisio.finance.insights.spending import CategoryInfo, MonthlySums, monthly_sums
from hubnisio.finance.kinds import kind_is
from hubnisio.finance.models import (
    Account,
    AccountOwner,
    AccountVisibility,
    BalanceSnapshot,
    Budget,
    BudgetLimit,
    Cadence,
    CategoryAssignment,
    CategoryKind,
    Counterparty,
    FxRate,
    FxSource,
    Overspend,
    RecurringSeries,
    RecurringStatus,
    Source,
    TransactionAnnotation,
    TransactionKind,
    TransactionStatus,
    Transfer,
)
from hubnisio.finance.scoping import View, listed_account_ids
from hubnisio.finance.transactions_api import transactions_query

pytestmark = pytest.mark.anyio

SEPTEMBER, OCTOBER = date(2026, 9, 1), date(2026, 10, 1)
VIEWS: tuple[View, ...] = ("personal", "household")
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


@dataclass(frozen=True)
class Login:
    role: str
    dsn: str


@pytest.fixture
async def logins(
    home: Home, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[dict[uuid.UUID, Login]]:
    """An AI login for each member, made by the CLI command."""
    monkeypatch.setenv("HUBNISIO_AI_SECRETS_DIR", str(tmp_path))
    get_settings.cache_clear()
    result: dict[uuid.UUID, Login] = {}
    for principal in (home.owner, home.member):
        assert await ai_login(await email_of(principal), revoke=False) == 0
        role = ai_role_name(principal.user_id)
        result[principal.user_id] = Login(role, (tmp_path / role).read_text().strip())
    yield result
    get_settings.cache_clear()


async def email_of(principal: Principal) -> str:
    async with get_sessionmaker()() as session:
        email = await session.scalar(select(User.email).where(User.id == principal.user_id))
    assert email is not None
    return email


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


# The data: the cases the views must agree with the app on.


@dataclass(frozen=True)
class Data:
    hers: uuid.UUID  # the member's private account
    hidden: uuid.UUID  # the owner's, hidden
    owner_private: set[uuid.UUID]  # transactions on the owner's private account
    member_private: set[uuid.UUID]  # on the member's


async def new_account(
    home: Home, name: str, owner: Principal, visibility: AccountVisibility, *, hidden: bool = False
) -> uuid.UUID:
    async with get_sessionmaker()() as session, session.begin():
        account = Account(
            household_id=home.owner.household_id,
            institution_name="Revolut",
            currency="EUR",
            display_name=name,
            visibility=visibility,
            hidden_at=datetime(2026, 10, 1, tzinfo=UTC) if hidden else None,
        )
        session.add(account)
        await session.flush()
        session.add(AccountOwner(account_id=account.id, user_id=owner.user_id))
    return account.id


async def save(*items: Any) -> None:
    async with get_sessionmaker()() as session, session.begin():
        session.add_all(items)


@pytest.fixture
async def data(home: Home) -> AsyncIterator[Data]:
    """Removed afterwards: the FX tests look at every currency in use, and these are fake."""
    yield await populate(home)
    async with get_sessionmaker()() as session, session.begin():
        await session.execute(delete(Household).where(Household.id == home.owner.household_id))
        await session.execute(delete(FxRate).where(FxRate.quote_currency == "XTQ"))


async def populate(home: Home) -> Data:
    household = home.owner.household_id
    food, groceries = home.categories["Food"], home.categories["Groceries"]
    rent = home.categories["Rent & mortgage"]
    hers = await new_account(home, "Rui privado", home.member, AccountVisibility.PRIVATE)
    theirs = await new_account(home, "Rui", home.member, AccountVisibility.SHARED)
    hidden = await new_account(home, "Antiga", home.owner, AccountVisibility.SHARED, hidden=True)
    merchant = Counterparty(household_id=household, name="Pingo")
    async with get_sessionmaker()() as session, session.begin():
        await session.execute(
            update(Account)
            .where(Account.id == home.savings)
            .values(is_pot=True, pot_category_id=rent)
        )
        # fx_rates is global: a test-only currency, its rate the same in every test.
        await session.execute(
            insert(FxRate)
            .values(quote_currency="XTQ", on=OCTOBER, rate=Decimal(4), source=FxSource.ECB)
            .on_conflict_do_nothing(index_elements=["quote_currency", "on"])
        )
        session.add(merchant)

    # The owner's shared account.
    weekly = await add(home, "-50.00", 3, description="PINGO DOCE")
    rent_paid = await add(home, "-1200.00", 1)
    rent_back = await add(home, "600.00", 2)  # a repayment: lowers Rent
    await add(home, "2000.00", 1)
    await add(home, "-30.00", 4)
    overridden = await add(home, "-20.00", 5)  # uncategorized, overridden to income
    overridden_category = await add(home, "-15.00", 6)  # in Groceries, overridden to income
    foreign = await add(home, "-40.00", 7, currency="XTQ")  # 10 euros
    await add(home, "-7.00", 8, currency="XTN")  # no rate
    await add(home, "-5.00", 9, status=TransactionStatus.PENDING)
    lone_transfer = await add(home, "-60.00", 10)  # overridden to a transfer
    september = await add(home, "-80.00", 0, on=date(2026, 9, 15))
    # Into the pot and back; to the owner's private account; the member's into the pot.
    to_pot = await add(home, "-300.00", 12)
    into_pot = await add(home, "300.00", 12, account=home.savings)
    from_pot = await add(home, "-50.00", 20, account=home.savings)
    back = await add(home, "50.00", 20)
    to_private = await add(home, "-100.00", 15)
    on_private = await add(home, "100.00", 15, account=home.private)
    their_out = await add(home, "-200.00", 5, account=theirs)
    their_in = await add(home, "200.00", 5, account=home.savings)
    # The pot's own spending, the private accounts, the member's shared one, a hidden one.
    pot_spends = await add(home, "-120.00", 14, account=home.savings)
    private_groceries = await add(home, "-75.00", 16, account=home.private)
    private_big = await add(home, "-999.00", 17, account=home.private)
    hers_one = await add(home, "-44.00", 18, account=hers)
    hers_two = await add(home, "-6.00", 19, account=hers)
    their_groceries = await add(home, "-25.00", 6, account=theirs)
    await add(home, "-10.00", 0, on=date(2026, 9, 3), account=hidden)

    def categorized(
        transaction: uuid.UUID, category: uuid.UUID, source: Source = Source.MANUAL
    ) -> CategoryAssignment:
        return CategoryAssignment(
            household_id=household, transaction_id=transaction, category_id=category, source=source
        )

    def annotated(transaction: uuid.UUID, **fields: Any) -> TransactionAnnotation:
        return TransactionAnnotation(household_id=household, transaction_id=transaction, **fields)

    def override(transaction: uuid.UUID, kind: TransactionKind) -> TransactionAnnotation:
        return annotated(transaction, kind_override=kind, kind_source=Source.MANUAL)

    def paired(outgoing: uuid.UUID, incoming: uuid.UUID) -> Transfer:
        return Transfer(
            household_id=household, outgoing_id=outgoing, incoming_id=incoming, source=Source.AUTO
        )

    await save(
        categorized(weekly, groceries),
        categorized(rent_paid, rent, Source.RULE),
        categorized(rent_back, rent),
        categorized(overridden_category, groceries),
        categorized(foreign, groceries),
        categorized(september, groceries),
        categorized(pot_spends, groceries),
        categorized(private_groceries, groceries),
        categorized(their_groceries, groceries),
        categorized(to_pot, groceries),  # ignored in Mine: the pot's category wins
        annotated(weekly, counterparty_id=merchant.id, tags=["food"], note="weekly shop"),
        override(overridden, TransactionKind.INCOME),
        override(overridden_category, TransactionKind.INCOME),
        override(lone_transfer, TransactionKind.TRANSFER),
        annotated(private_groceries, counterparty_id=merchant.id),
        annotated(hers_one, counterparty_id=merchant.id),
        annotated(hers_two, counterparty_id=merchant.id),
        paired(to_pot, into_pot),
        paired(from_pot, back),
        paired(to_private, on_private),
        paired(their_out, their_in),
    )
    await save(
        *(
            BalanceSnapshot(
                household_id=household,
                account_id=account,
                balance_type=balance_type,
                amount=Decimal(amount),
                currency="EUR",
                reference_date=date(2026, 10, day),
                fetched_at=datetime(2026, 10, day, 12, tzinfo=UTC),
            )
            for account, balance_type, amount, day in (
                (home.shared, "ITAV", "500.00", 20),
                (home.shared, "CLBD", "520.00", 20),
                (home.shared, "ITAV", "600.00", 21),
                (home.shared, "CLBD", "610.00", 21),
                (home.shared, "XXXX", "1.00", 21),
                (home.private, "CLBD", "100.00", 21),
                (home.savings, "ITAV", "180.00", 21),
                (hers, "ITAV", "44.00", 21),
                (hidden, "CLBD", "10.00", 21),
            )
        ),
        *(
            RecurringSeries(
                household_id=household,
                account_id=account,
                match_key=name.lower(),
                name=name,
                cadence=Cadence.MONTHLY,
                kind=TransactionKind.EXPENSE,
                expected_amount=Decimal("-9.99"),
                currency="EUR",
                occurrences=3,
                first_seen_on=date(2026, 8, 1),
                last_seen_on=date(2026, 10, 1),
                next_expected_on=date(2026, 11, 1),
                status=RecurringStatus.ACTIVE,
            )
            for account, name in (
                (home.shared, "Netflix"),
                (home.private, "Gym"),
                (hers, "Spotify"),
            )
        ),
    )
    # The overall budget, a group's and a sub-limit inside it, changed from October on.
    overall = Budget(household_id=household, category_id=None, rollover=True)
    group = Budget(household_id=household, category_id=food, overspend=Overspend.CARRY)
    sub = Budget(household_id=household, category_id=groceries, rollover=True)
    await save(overall, group, sub)
    await save(
        BudgetLimit(budget_id=overall.id, starts_on=SEPTEMBER, amount=Decimal(1000)),
        BudgetLimit(budget_id=group.id, starts_on=SEPTEMBER, amount=Decimal(200)),
        BudgetLimit(budget_id=group.id, starts_on=OCTOBER, amount=Decimal(150)),
        BudgetLimit(budget_id=sub.id, starts_on=SEPTEMBER, amount=Decimal(100)),
    )
    return Data(
        hers=hers,
        hidden=hidden,
        owner_private={on_private, private_groceries, private_big},
        member_private={hers_one, hers_two},
    )


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
