"""The MCP server's tools (ADR-0006). They read the `analytics` views as the member's own login,
so they see what the member sees in the app, and compute figures with the app's own functions.

Each call opens its own connection. Its reads run in a READ ONLY transaction; then the call is
recorded in core.ai_calls through `analytics.record_call`, which needs a read-write one. A call
that fails is recorded too, without a row count. The one write is `suggest_categories`, which
runs in a read-write transaction and writes through `analytics.suggest_category`: the login may
only read `analytics` and call those two functions.
"""

import uuid
from collections import Counter, defaultdict
from collections.abc import Awaitable, Callable, Sequence
from datetime import date, timedelta
from decimal import Decimal
from typing import Annotated, Any, LiteralString, Self, cast

import psycopg
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.mcpserver.prompts import Prompt
from mcp.types import ToolAnnotations
from psycopg import sql
from psycopg.abc import QueryNoTemplate
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from pydantic import BaseModel, Field, model_validator
from pydantic_core import to_jsonable_python

from hubnisio.ai import outputs, views
from hubnisio.ai.views import Connection
from hubnisio.finance import schemas
from hubnisio.finance.budgets import compute_budgets, first_month
from hubnisio.finance.insights.net_worth import compute_net_worth, series_start
from hubnisio.finance.insights.spending import (
    cash_flow,
    cents,
    month_start,
    months_until,
    spending_by_group,
)
from hubnisio.finance.models import Cadence, RecurringStatus, Review, TransactionKind
from hubnisio.finance.recurring.detect import description_key, status_on
from hubnisio.finance.scoping import View

QUERY_ROWS = 500
QUERY_TIMEOUT = "5s"

INSTRUCTIONS = """\
Hubnisio is the user's personal finance hub: their bank accounts, with categories, merchants, \
budgets and recurring payments. These tools read it as the user, so they see only what the \
user may see in the app. They change nothing but category suggestions (suggest_categories), \
which the user reviews in the app.

- Amounts are signed: negative is money out. Fields named "spent" are positive when spent.
- Totals are in euros, at the exchange rate on each transaction's day.
- Spending counts booked transactions that aren't transfers between the household's own \
accounts. Money in with an expense category (a refund, or someone paying the user back) lowers \
that category's spending.
- view: "personal" (the default, as on the app's pages) counts the user's own accounts. A \
shared pot is left out, and money the user moves into it counts as spending in the pot's \
category. "household" counts every account the user can see, the pot's spending included.
- Prefer the specific tools; query_sql is for what they don't answer.
"""

Months = Annotated[int, Field(ge=1, le=36, description="How many months, ending with until's.")]
Limit = Annotated[int, Field(ge=1, le=200)]
ViewArgument = Annotated[
    View,
    Field(description="personal: the user's own accounts (the default); household: all."),
]

# What a merchant or description in a suggestion stands for: the group's spending as
# uncategorized_overview counts it (household view), plus what an AI suggested for before.
SUGGESTABLE: LiteralString = (
    "t.status = 'booked' AND t.kind = 'expense'"
    " AND (t.category_id IS NULL OR t.category_source = 'ai')"
)

CATEGORIZE_PROMPT = """\
Categorize the user's spending that has no category yet, as suggestions they review in the app.

1. Call uncategorized_overview with view "household" and limit 200: what has no category, \
grouped by merchant, else by the description without digits, the most spent first.
2. Call list_categories for the categories you can use. Only expense categories fit spending.
3. Go through the groups in order. Where the merchant or description makes the category clear, \
suggest it with suggest_categories: the group's merchant_id, or its name as description when it \
has no merchant. Send several groups in one call. To look closer (amounts, dates, notes), use \
search_transactions with merchant_id or text.
4. Leave a group out rather than guess: a person's name, a transfer with no detail, a payment \
processor that could be anything. The user categorizes those by hand.
5. Finish with a short report: how many transactions you suggested a category for, by \
category, and the largest groups you left for the user.

Suggestions never replace a category the user, a rule or a merchant's default set. The user \
sees each one marked as suggested by AI, and picking a category replaces it.
"""


class Suggestion(BaseModel):
    """A category for some transactions: by ID, or a group from uncategorized_overview."""

    category_id: uuid.UUID
    transaction_ids: Annotated[list[uuid.UUID] | None, Field(min_length=1, max_length=500)] = None
    merchant_id: Annotated[
        uuid.UUID | None,
        Field(description="A merchant: its spending without a category."),
    ] = None
    description: Annotated[
        str | None,
        Field(
            max_length=200,
            description="A group's name from uncategorized_overview, when it has no merchant: "
            "the spending without a category or merchant whose description reads the same "
            "without digits.",
        ),
    ] = None

    @model_validator(mode="after")
    def _one_target(self) -> Self:
        targets = (self.transaction_ids, self.merchant_id, self.description)
        if sum(target is not None for target in targets) != 1:
            raise ValueError("Give one of transaction_ids, merchant_id and description.")
        return self


class Tools:
    """The tools, each run as the member login in `dsn`."""

    def __init__(self, dsn: str) -> None:
        self._dsn = dsn

    async def list_categories(self, include_archived: bool = False) -> outputs.Categories:
        """The categories a transaction can have, in two levels: groups and the categories in
        them. Expense categories count as spending, income ones as income."""

        async def read(db: Connection) -> tuple[outputs.Categories, int]:
            found = [
                outputs.Category.model_validate(row)
                for row in await _dicts(
                    db,
                    "SELECT c.id, c.name, c.kind, c.group_id, c.group_name AS group,"
                    " c.archived_at IS NOT NULL AS archived"
                    " FROM analytics.categories c JOIN analytics.categories g ON g.id = c.group_id"
                    " WHERE %s OR c.archived_at IS NULL"
                    " ORDER BY g.position, g.name, c.parent_id IS NOT NULL, c.position, c.name",
                    [include_archived],
                )
            ]
            return outputs.Categories(categories=found), len(found)

        return await self._call("list_categories", {"include_archived": include_archived}, read)

    async def list_accounts(self) -> outputs.Accounts:
        """The user's accounts, as the Accounts page lists them. Hidden accounts are left out,
        though their past transactions still count in spending."""

        async def read(db: Connection) -> tuple[outputs.Accounts, int]:
            found = [
                outputs.Account.model_validate(row)
                for row in await _dicts(
                    db,
                    "SELECT id, name, institution, currency, account_type, visibility, is_owner,"
                    " is_pot, pot_category_id, include_in_net_worth"
                    " FROM analytics.accounts WHERE NOT hidden ORDER BY institution, name",
                )
            ]
            return outputs.Accounts(accounts=found), len(found)

        return await self._call("list_accounts", {}, read)

    async def search_transactions(
        self,
        text: Annotated[
            str | None,
            Field(
                max_length=100,
                description="Matches the description, the bank's counterparty, the merchant "
                "or the note.",
            ),
        ] = None,
        date_from: date | None = None,
        date_to: date | None = None,
        account_id: uuid.UUID | None = None,
        category_id: Annotated[
            uuid.UUID | None, Field(description="A category, or a group with its categories.")
        ] = None,
        merchant_id: uuid.UUID | None = None,
        kind: TransactionKind | None = None,
        uncategorized: Annotated[
            bool, Field(description="Only those without a category, transfers left out.")
        ] = False,
        ai_suggested: Annotated[
            bool, Field(description="Only those whose category an AI suggested.")
        ] = False,
        limit: Limit = 50,
    ) -> outputs.Transactions:
        """Transactions on the user's accounts, booked and pending, newest first: what the
        Transactions page lists, with the same filters."""
        arguments = {
            "text": text,
            "date_from": date_from,
            "date_to": date_to,
            "account_id": account_id,
            "category_id": category_id,
            "merchant_id": merchant_id,
            "kind": kind,
            "uncategorized": uncategorized,
            "ai_suggested": ai_suggested,
            "limit": limit,
        }
        conditions: list[LiteralString] = ["true"]
        params: list[Any] = []
        if text and text.strip():
            pattern = f"%{_escape_like(text.strip())}%"
            conditions.append(
                "(t.description ILIKE %s OR t.bank_counterparty ILIKE %s"
                " OR t.merchant ILIKE %s OR t.note ILIKE %s)"
            )
            params += [pattern] * 4
        filters: list[tuple[Any, LiteralString]] = [
            (date_from, "t.occurred_on >= %s"),
            (date_to, "t.occurred_on <= %s"),
            (account_id, "t.account_id = %s"),
            (merchant_id, "t.merchant_id = %s"),
            (None if kind is None else kind.value, "t.kind = %s"),
        ]
        for value, condition in filters:
            if value is not None:
                conditions.append(condition)
                params.append(value)
        if category_id is not None:
            conditions.append("(t.category_id = %s OR t.group_id = %s)")
            params += [category_id, category_id]
        if uncategorized:
            conditions.append("t.category_id IS NULL AND t.kind <> 'transfer'")
        if ai_suggested:
            conditions.append("t.category_source = 'ai'")
        query = sql.SQL(
            "SELECT t.id, t.account_id, a.name AS account, t.status, t.occurred_on, t.amount,"
            " t.currency, t.eur_amount, t.kind, t.in_mine, t.description, t.bank_counterparty,"
            " t.merchant_id, t.merchant, t.category_id, t.category, t.group_name AS group,"
            " t.category_source, t.tags, t.rule_tags, t.note, count(*) OVER () AS matched"
            " FROM analytics.transactions t JOIN analytics.accounts a ON a.id = t.account_id"
            " WHERE {} ORDER BY t.occurred_on DESC, t.id DESC LIMIT %s"
        ).format(_all(conditions))

        async def read(db: Connection) -> tuple[outputs.Transactions, int]:
            rows = await _dicts(db, query, [*params, limit])
            found = [
                outputs.Transaction.model_validate(row | {"eur_amount": _cents(row["eur_amount"])})
                for row in rows
            ]
            matched = rows[0]["matched"] if rows else 0
            return outputs.Transactions(matched=matched, transactions=found), len(found)

        return await self._call("search_transactions", arguments, read)

    async def spending_summary(
        self, months: Months = 12, until: date | None = None, view: ViewArgument = "personal"
    ) -> schemas.Spending:
        """Spending per month by expense group and category, plus uncategorized spending: the
        app's spending chart. Each amount list follows `months`. until: a day in the last month
        (default: this month)."""

        async def read(db: Connection) -> tuple[schemas.Spending, int]:
            window = months_until(until or date.today(), months)
            sums = await views.monthly_sums(db, view, window[0], window[-1])
            result = spending_by_group(sums, await views.categories(db), window)
            return result, len(result.groups)

        arguments = {"months": months, "until": until, "view": view}
        return await self._call("spending_summary", arguments, read)

    async def cashflow(
        self, months: Months = 12, until: date | None = None, view: ViewArgument = "personal"
    ) -> schemas.CashFlow:
        """Income, spending and their difference per month: the app's cash flow. until: a day
        in the last month (default: this month)."""

        async def read(db: Connection) -> tuple[schemas.CashFlow, int]:
            window = months_until(until or date.today(), months)
            sums = await views.monthly_sums(db, view, window[0], window[-1])
            result = cash_flow(sums, await views.categories(db), window)
            return result, len(result.months)

        arguments = {"months": months, "until": until, "view": view}
        return await self._call("cashflow", arguments, read)

    async def budget_status(
        self,
        month: Annotated[
            date | None, Field(description="A day in the month (default: this month).")
        ] = None,
        view: ViewArgument = "personal",
    ) -> schemas.BudgetsOut:
        """The month's budgets, as the Budgets page shows them: the overall budget (all
        spending) and those on a group or category, each with its limit, what carried in from
        earlier months, spent and remaining. A budget on a category inside a budgeted group is
        a sub-limit, listed under the group."""

        async def read(db: Connection) -> tuple[schemas.BudgetsOut, int]:
            first = month_start(month or date.today())
            specs = await views.budget_specs(db)
            sums = await views.monthly_sums(db, view, first_month(specs, first), first)
            result = compute_budgets(first, specs, await views.categories(db), sums)
            return result, len(result.budgets) + (result.overall is not None)

        return await self._call("budget_status", {"month": month, "view": view}, read)

    async def recurring_payments(
        self, include_suggested: bool = False
    ) -> outputs.RecurringPayments:
        """Recurring payments and income the app detected. Only those the user confirmed count
        (in upcoming payments); include_suggested adds those waiting for review."""
        reviews = [Review.CONFIRMED, *([Review.SUGGESTED] if include_suggested else [])]

        async def read(db: Connection) -> tuple[outputs.RecurringPayments, int]:
            today = date.today()
            found: list[outputs.RecurringPayment] = []
            for row in await _dicts(
                db,
                "SELECT r.id, r.name, r.account_id, a.name AS account, r.merchant_id, r.cadence,"
                " r.kind, r.expected_amount, r.currency, r.amount_varies, r.occurrences,"
                " r.first_seen_on, r.last_seen_on, r.next_expected_on, r.previous_amount,"
                " r.amount_changed_on, r.review, r.cancelled_on"
                " FROM analytics.recurring_payments r"
                " JOIN analytics.accounts a ON a.id = r.account_id"
                " WHERE r.review = ANY(%s)",
                [[str(review) for review in reviews]],
            ):
                state = status_on(
                    Cadence(row["cadence"]), row["next_expected_on"], today, row["cancelled_on"]
                )
                found.append(outputs.RecurringPayment.model_validate(row | {"status": state}))
            order = list(RecurringStatus)
            found.sort(key=lambda p: (order.index(p.status), p.next_expected_on, p.name))
            return outputs.RecurringPayments(payments=found), len(found)

        return await self._call(
            "recurring_payments", {"include_suggested": include_suggested}, read
        )

    async def balances(self, view: ViewArgument = "personal") -> outputs.Balances:
        """Each account's latest balance from the bank (hidden accounts left out), and net worth
        today in euros: the accounts that count in the view, at their booked balance moved by
        the transactions booked since."""

        async def read(db: Connection) -> tuple[outputs.Balances, int]:
            today = date.today()
            inputs = await views.balance_inputs(db)
            counted = await views.net_worth_accounts(db, view)
            rates = await views.rate_table(db, inputs.currencies, today, today)
            # Every account's balance today, and net worth from those the view counts.
            today_balances = {
                account.id: account
                for account in compute_net_worth(inputs, rates, today, today).accounts
            }
            worth = compute_net_worth(inputs.only(counted), rates, today, today)
            found = [
                outputs.AccountBalance.model_validate(
                    row
                    | {
                        "in_net_worth": row["account_id"] in counted,
                        "balance_today": today_balances[row["account_id"]].balance,
                        "balance_today_eur": today_balances[row["account_id"]].balance_eur,
                    }
                )
                for row in await _dicts(
                    db,
                    "SELECT a.id AS account_id, a.name,"
                    " coalesce(b.currency, a.currency) AS currency,"
                    " b.balance, b.balance_type, b.fetched_at,"
                    " coalesce(b.reference_date, b.fetched_at::date) AS as_of"
                    " FROM analytics.accounts a"
                    " LEFT JOIN analytics.balances b ON b.account_id = a.id"
                    " WHERE NOT a.hidden ORDER BY a.institution, a.name",
                )
            ]
            result = outputs.Balances(
                view=view, net_worth=worth.total, accounts=found, unconverted=worth.unconverted
            )
            return result, len(found)

        return await self._call("balances", {"view": view}, read)

    async def net_worth_history(
        self,
        date_from: Annotated[
            date | None,
            Field(
                description="The first day. The series never starts before every account's "
                "history does."
            ),
        ] = None,
        every: Annotated[
            outputs.Every,
            Field(description="day: every day; week: each Sunday; month: each month's last day."),
        ] = "week",
        view: ViewArgument = "personal",
    ) -> outputs.NetWorthHistory:
        """Net worth in euros over time: the app's net worth chart. It counts the accounts in
        the view's net worth, each at its latest booked balance moved by the booked
        transactions in between, converted at each day's exchange rate. The series starts on
        the first day every account has data for (a bank sends a few months at first), or
        date_from if later, and its last point is today. Also each account's balance today."""

        async def read(db: Connection) -> tuple[outputs.NetWorthHistory, int]:
            today = date.today()
            inputs = (await views.balance_inputs(db)).only(await views.net_worth_accounts(db, view))
            start = series_start(inputs, today, date_from)
            rates = await views.rate_table(db, inputs.currencies, start, today)
            worth = compute_net_worth(inputs, rates, start, today)
            points = [
                point
                for point in worth.points
                if point.on == today or _ends_period(point.on, every)
            ]
            result = outputs.NetWorthHistory(
                view=view,
                every=every,
                total=worth.total,
                points=points,
                accounts=worth.accounts,
                unconverted=worth.unconverted,
            )
            return result, len(points)

        arguments = {"date_from": date_from, "every": every, "view": view}
        return await self._call("net_worth_history", arguments, read)

    async def uncategorized_overview(
        self,
        date_from: date | None = None,
        date_to: date | None = None,
        view: ViewArgument = "personal",
        limit: Limit = 50,
    ) -> outputs.UncategorizedOverview:
        """Spending without a category, grouped by merchant where the transactions have one,
        else by their description without digits, the most spent first, with up to three
        example descriptions each. Its total is the spending summary's uncategorized. A group
        goes to suggest_categories by its merchant_id, or by its name as description."""
        conditions: list[LiteralString] = ["t.status = 'booked'"]
        params: list[Any] = []
        if view == "personal":
            # As monthly_sums counts it: a move to or from a shared pot takes the pot's
            # category, so it's uncategorized only if the pot has none.
            conditions.append(
                "t.in_mine AND ((NOT t.pot_move AND t.category_id IS NULL AND t.kind = 'expense')"
                " OR (t.pot_move AND pot.pot_category_id IS NULL AND t.amount <= 0))"
            )
        else:
            conditions.append("t.category_id IS NULL AND t.kind = 'expense'")
        filters: list[tuple[Any, LiteralString]] = [
            (date_from, "t.occurred_on >= %s"),
            (date_to, "t.occurred_on <= %s"),
        ]
        for value, condition in filters:
            if value is not None:
                conditions.append(condition)
                params.append(value)
        query = sql.SQL(
            "SELECT t.merchant_id, t.merchant, t.description, t.bank_counterparty, t.eur_amount,"
            " t.occurred_on FROM analytics.transactions t"
            " LEFT JOIN analytics.accounts pot ON pot.id = t.transfer_account_id AND pot.is_pot"
            " WHERE {}"
        ).format(_all(conditions))

        async def read(db: Connection) -> tuple[outputs.UncategorizedOverview, int]:
            rows = await _dicts(db, query, params)
            by_key: dict[tuple[uuid.UUID | None, str], list[dict[str, Any]]] = defaultdict(list)
            for row in rows:
                if row["merchant_id"] is not None:
                    by_key[(row["merchant_id"], row["merchant"])].append(row)
                else:
                    by_key[(None, _description_group(row) or "(no description)")].append(row)
            groups: list[outputs.UncategorizedGroup] = []
            for (merchant_id, name), members in by_key.items():
                texts = Counter(m["description"] or m["bank_counterparty"] for m in members)
                groups.append(
                    outputs.UncategorizedGroup(
                        merchant_id=merchant_id,
                        name=name,
                        transactions=len(members),
                        spent=cents(-_converted_sum(members)),
                        first_on=min(m["occurred_on"] for m in members),
                        last_on=max(m["occurred_on"] for m in members),
                        examples=[text for text, _ in texts.most_common(3) if text],
                    )
                )
            groups.sort(key=lambda g: (-g.spent, -g.transactions, g.name))
            result = outputs.UncategorizedOverview(
                view=view,
                groups=groups[:limit],
                group_count=len(groups),
                transactions=len(rows),
                spent=cents(-_converted_sum(rows)),
                unconverted=sum(1 for row in rows if row["eur_amount"] is None),
            )
            return result, len(result.groups)

        arguments = {"date_from": date_from, "date_to": date_to, "view": view, "limit": limit}
        return await self._call("uncategorized_overview", arguments, read)

    async def suggest_categories(
        self, suggestions: Annotated[list[Suggestion], Field(min_length=1, max_length=100)]
    ) -> outputs.Suggested:
        """Suggest a category for transactions: the only change these tools can make. Each
        suggestion names a category from list_categories, and either transaction IDs or a group
        from uncategorized_overview (its merchant_id, or its name as description when it has no
        merchant). A suggestion counts at once; the app shows it as suggested by AI, and the
        user can change it. It never replaces a category the user, a rule or a merchant's
        default set, and pending transactions and transfers are skipped. Suggesting again
        replaces an earlier AI suggestion. The suggestions in a call are saved together, or none
        if one fails (an archived category, say)."""

        async def write(db: Connection) -> tuple[outputs.Suggested, int]:
            results: list[outputs.SuggestionResult] = []
            for suggestion in suggestions:
                ids = await _suggestion_targets(db, suggestion)
                written = skipped = 0
                if ids:
                    cursor = await db.execute(
                        "SELECT written, skipped FROM analytics.suggest_category(%s, %s)",
                        [ids, suggestion.category_id],
                    )
                    # The function always returns its one row.
                    written, skipped = cast(tuple[int, int], await cursor.fetchone())
                results.append(
                    outputs.SuggestionResult(
                        category_id=suggestion.category_id,
                        merchant_id=suggestion.merchant_id,
                        description=suggestion.description,
                        written=written,
                        skipped=skipped,
                    )
                )
            result = outputs.Suggested(
                results=results,
                written=sum(r.written for r in results),
                skipped=sum(r.skipped for r in results),
            )
            return result, result.written

        arguments = {"suggestions": [s.model_dump(exclude_none=True) for s in suggestions]}
        return await self._call("suggest_categories", arguments, write, read_only=False)

    async def query_sql(
        self, query: Annotated[str, Field(description="One PostgreSQL query.")]
    ) -> outputs.QueryResult:
        """A read-only SQL query over the analytics views, for what the other tools don't
        answer. It runs as `SELECT * FROM (<query>) q LIMIT 500` in a read-only transaction
        with a 5-second timeout, so it must be a single query that returns rows.

        The views (bare names work): me, accounts, visible_accounts, transactions,
        monthly_category_spend, categories, merchants, budgets, budget_limits,
        recurring_payments, balances, daily_movements, account_connections, fx_rates.
        Each has a comment saying what it holds, e.g.
        `SELECT obj_description('analytics.transactions'::regclass)`; their columns are in
        information_schema.columns. Prefer monthly_category_spend for monthly totals: it
        counts as the app does."""

        async def read(db: Connection) -> tuple[outputs.QueryResult, int]:
            wrapped = wrap(query)
            await db.execute("SELECT set_config('statement_timeout', %s, true)", [QUERY_TIMEOUT])
            cursor = await db.execute(wrapped, [QUERY_ROWS + 1])
            columns = [column.name for column in cursor.description or []]
            rows = await cursor.fetchall()
            listed = [list(row) for row in rows[:QUERY_ROWS]]
            result = outputs.QueryResult(
                columns=columns,
                rows=to_jsonable_python(listed, fallback=str),
                truncated=len(rows) > QUERY_ROWS,
            )
            return result, len(listed)

        return await self._call("query_sql", {"query": query}, read)

    async def _call[T](
        self,
        tool: str,
        arguments: dict[str, Any],
        run: Callable[[Connection], Awaitable[tuple[T, int]]],
        *,
        read_only: bool = True,
    ) -> T:
        """`run` (giving the result and its row count) in a read-only transaction, unless the
        tool writes, then the audit record."""
        try:
            connection = await psycopg.AsyncConnection.connect(self._dsn, autocommit=True)
        except psycopg.OperationalError as error:
            raise ToolError(f"Can't connect to the hub as this member: {error}") from error
        async with connection:
            try:
                async with connection.transaction():
                    await connection.execute(
                        "SET TRANSACTION READ ONLY" if read_only else "SET TRANSACTION READ WRITE"
                    )
                    result, row_count = await run(connection)
            except Exception as error:
                await _record(connection, tool, arguments, None)
                if isinstance(error, psycopg.Error):
                    raise ToolError(str(error)) from error
                raise
            await _record(connection, tool, arguments, row_count)
        return result


def wrap(query: str) -> sql.Composed:
    """`SELECT * FROM (<query>) q LIMIT %s`: only a query fits there. Executed with its
    parameter, psycopg sends it as one prepared statement, so nothing can be chained after it
    either. A trailing semicolon is dropped, and % signs are escaped, as psycopg reads %s
    placeholders anywhere in the text."""
    statement = query.strip()
    while statement.endswith(";"):
        statement = statement[:-1].rstrip()
    if not statement:
        raise ToolError("The query is empty.")
    # The member's own query, run as their read-only login.
    own = sql.SQL(cast(LiteralString, statement.replace("%", "%%")))
    return sql.SQL("SELECT * FROM (\n{}\n) q LIMIT %s").format(own)


def build_server(dsn: str) -> MCPServer:
    """The server, with every tool connecting as the member login in `dsn`."""
    server = MCPServer("hubnisio", instructions=INSTRUCTIONS)
    tools = Tools(dsn)
    read_only = ToolAnnotations(read_only_hint=True, open_world_hint=False)
    for tool in (
        tools.list_categories,
        tools.list_accounts,
        tools.search_transactions,
        tools.spending_summary,
        tools.cashflow,
        tools.budget_status,
        tools.recurring_payments,
        tools.balances,
        tools.net_worth_history,
        tools.uncategorized_overview,
        tools.query_sql,
    ):
        server.add_tool(tool, annotations=read_only)
    # It writes, but only suggestions the user reviews; the same call again changes nothing.
    server.add_tool(
        tools.suggest_categories,
        annotations=ToolAnnotations(
            read_only_hint=False,
            destructive_hint=False,
            idempotent_hint=True,
            open_world_hint=False,
        ),
    )
    server.add_prompt(
        Prompt.from_function(
            categorize_uncategorized,
            description="Suggest categories for the spending that has none, merchant by merchant.",
        )
    )
    return server


def categorize_uncategorized() -> str:
    return CATEGORIZE_PROMPT


async def _record(
    connection: Connection, tool: str, arguments: dict[str, Any], row_count: int | None
) -> None:
    """The call in core.ai_calls: who, which tool, its arguments and the row count, never the
    data returned (ADR-0006)."""
    async with connection.transaction():
        await connection.execute("SET TRANSACTION READ WRITE")
        await connection.execute(
            "SELECT analytics.record_call(%s, %s, %s::integer)",
            [tool, Jsonb(to_jsonable_python(arguments)), row_count],
        )


async def _dicts(
    db: Connection, query: QueryNoTemplate, params: Sequence[Any] = ()
) -> list[dict[str, Any]]:
    cursor = db.cursor(row_factory=dict_row)
    await cursor.execute(query, params)
    return await cursor.fetchall()


async def _suggestion_targets(db: Connection, suggestion: Suggestion) -> list[uuid.UUID]:
    """The transactions a suggestion names. The function decides which of them it may take."""
    if suggestion.transaction_ids is not None:
        return suggestion.transaction_ids
    if suggestion.merchant_id is not None:
        cursor = await db.execute(
            sql.SQL(
                "SELECT t.id FROM analytics.transactions t WHERE t.merchant_id = %s AND {}"
            ).format(sql.SQL(SUGGESTABLE)),
            [suggestion.merchant_id],
        )
        return [id_ for (id_,) in await cursor.fetchall()]
    wanted = description_key(suggestion.description)
    if not wanted:
        return []
    rows = await _dicts(
        db,
        sql.SQL(
            "SELECT t.id, t.description, t.bank_counterparty FROM analytics.transactions t"
            " WHERE t.merchant_id IS NULL AND {}"
        ).format(sql.SQL(SUGGESTABLE)),
    )
    return [row["id"] for row in rows if _description_group(row) == wanted]


def _description_group(row: dict[str, Any]) -> str:
    """A transaction's group in uncategorized_overview when it has no merchant."""
    return description_key(row["description"]) or description_key(row["bank_counterparty"])


def _all(conditions: Sequence[LiteralString]) -> sql.Composed:
    return sql.SQL(" AND ").join(sql.SQL(condition) for condition in conditions)


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _ends_period(day: date, every: outputs.Every) -> bool:
    if every == "week":
        return day.weekday() == 6
    if every == "month":
        return (day + timedelta(days=1)).day == 1
    return True


def _cents(amount: Decimal | None) -> Decimal | None:
    return cents(amount) if amount is not None else None


def _converted_sum(rows: Sequence[dict[str, Any]]) -> Decimal:
    return sum((row["eur_amount"] for row in rows if row["eur_amount"] is not None), Decimal())
