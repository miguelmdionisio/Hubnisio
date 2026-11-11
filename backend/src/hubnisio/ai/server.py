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
from hubnisio.finance.fx.convert import RateTable
from hubnisio.finance.insights.investments import compute_investments
from hubnisio.finance.insights.net_worth import compute_net_worth, series_start
from hubnisio.finance.insights.returns import compute_returns, tables_needed
from hubnisio.finance.insights.spending import (
    cash_flow,
    cents,
    month_start,
    months_until,
    spending_by_group,
)
from hubnisio.finance.models import Cadence, RecurringStatus, Review, TransactionKind
from hubnisio.finance.prices.table import PriceTable
from hubnisio.finance.recurring.detect import description_key, status_on
from hubnisio.finance.scoping import View
from hubnisio.health.body_api import Period as BodyPeriod
from hubnisio.health.insights import sleep as sleep_insights
from hubnisio.health.insights.body import Body, body
from hubnisio.health.insights.curves import CURVE_DURATIONS
from hubnisio.health.insights.performance import Performance, performance
from hubnisio.health.insights.performance import Period as PerformancePeriod
from hubnisio.health.insights.recovery import Recovery, recovery
from hubnisio.health.insights.training import current_form
from hubnisio.health.recovery_api import Period as RecoveryPeriod
from hubnisio.health.sleep_api import NIGHT_WINDOW, NightOut, SleepNight, SleepTrends
from hubnisio.health.sleep_api import Nights as SleepNights
from hubnisio.health.training_api import Period as TrainingPeriod
from hubnisio.health.training_api import Training, training

QUERY_ROWS = 500
QUERY_TIMEOUT = "5s"

INSTRUCTIONS = """\
Hubnisio is the user's personal finance hub: their bank accounts, with categories, merchants, \
budgets and recurring payments, and their investments. These tools read it as the user, so they \
see only what the user may see in the app. They change nothing but category suggestions \
(suggest_categories), which the user reviews in the app.

- Amounts are signed: negative is money out. Fields named "spent" are positive when spent.
- Totals are in euros, at the exchange rate on each transaction's day. Investment figures are \
in the investment account's currency.
- Spending counts booked transactions that aren't transfers between the household's own \
accounts. Money in with an expense category (a refund, or someone paying the user back) lowers \
that category's spending.
- view: "personal" (the default, as on the app's pages) counts the user's own accounts. A \
shared pot is left out, and money the user moves into it counts as spending in the pot's \
category. "household" counts every account the user can see, the pot's spending included.
- Prefer the specific tools; query_sql is for what they don't answer.

Health (the health_* tools) is the user's own data from their Garmin watch: activities, \
training load, sleep, recovery, performance and body. Nobody else's, not even another member \
of the household. Units: seconds, metres, m/s, bpm, watts and kg unless a field says \
otherwise; days are the user's local dates. Race predictions, VO2max, critical power and \
speed are estimates from the user's own efforts, not results. Training load is Hubnisio's \
own hrTSS-style score from heart rate, so it differs from Garmin's.
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
        the transactions booked since. An investment account counts at its cash plus its
        holdings at today's prices."""

        async def read(db: Connection) -> tuple[outputs.Balances, int]:
            today = date.today()
            inputs = await views.balance_inputs(db)
            counted = await views.net_worth_accounts(db, view)
            prices = await views.price_table(db, inputs.instrument_ids, today, today)
            rates = await views.rate_table(db, inputs.currencies | prices.currencies, today, today)
            # Every account's balance today, and net worth from those the view counts.
            today_balances = {
                account.id: account
                for account in compute_net_worth(inputs, rates, prices, today, today).accounts
            }
            worth = compute_net_worth(inputs.only(counted), rates, prices, today, today)
            found = [
                outputs.AccountBalance.model_validate(
                    row
                    | {
                        "in_net_worth": row["account_id"] in counted,
                        "balance_today": today_balances[row["account_id"]].balance,
                        "balance_today_eur": today_balances[row["account_id"]].balance_eur,
                        "as_of": today_balances[row["account_id"]].as_of,
                    }
                )
                for row in await _dicts(
                    db,
                    "SELECT a.id AS account_id, a.name,"
                    " coalesce(b.currency, a.currency) AS currency,"
                    " b.balance, b.balance_type, b.fetched_at"
                    " FROM analytics.accounts a"
                    " LEFT JOIN analytics.balances b ON b.account_id = a.id"
                    " WHERE NOT a.hidden ORDER BY a.institution, a.name",
                )
            ]
            result = outputs.Balances(
                view=view,
                net_worth=worth.total,
                accounts=found,
                unconverted=worth.unconverted,
                unpriced=worth.unpriced,
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
        transactions in between, converted at each day's exchange rate. An investment account
        counts at its cash plus its holdings at each day's prices, rebuilt from its trades;
        unpriced counts the holding-days left out for want of a price. The series starts on
        the first day every account has data for (a bank sends a few months at first), or
        date_from if later, and its last point is today. Also each account's balance today."""

        async def read(db: Connection) -> tuple[outputs.NetWorthHistory, int]:
            today = date.today()
            inputs = (await views.balance_inputs(db)).only(await views.net_worth_accounts(db, view))
            start = series_start(inputs, today, date_from)
            prices = await views.price_table(db, inputs.instrument_ids, start, today)
            rates = await views.rate_table(db, inputs.currencies | prices.currencies, start, today)
            worth = compute_net_worth(inputs, rates, prices, start, today)
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
                unpriced=worth.unpriced,
            )
            return result, len(points)

        arguments = {"date_from": date_from, "every": every, "view": view}
        return await self._call("net_worth_history", arguments, read)

    async def investments(
        self,
        date_from: Annotated[
            date | None,
            Field(description="The returns' first day (default: each account's first movement)."),
        ] = None,
        date_to: Annotated[
            date | None, Field(description="The returns' last day (default: today).")
        ] = None,
        months: Months = 12,
        every: Annotated[
            outputs.Every,
            Field(
                description="The value against net deposits: day, week (each Sunday) or month "
                "(each month's last day)."
            ),
        ] = "month",
    ) -> outputs.Investments:
        """Investment accounts (Trading 212), as the Investments page shows them. Each one's
        value, cash, cost and result at its latest sync; its holdings with their weights; its
        dividends and interest per month, the last `months` months; and the check of the value
        rebuilt from trades and daily prices, which net worth uses, against the broker's.

        Then its returns over the period (date_from to date_to): the result, the change in
        value less net deposits, broken down into price movements (realised on what was sold,
        unrealised on what's held at the end), dividends, interest, and fees and taxes; the
        time-weighted return (how the investments did, whatever the timing of money in and
        out) and the money-weighted return (the XIRR: what the money earned, given when it
        came in), over the period and, for a year or more, a year's equivalent; and the value
        against net deposits since the account opened. Returns are fractions: 0.05 is 5%. A
        gap says why a return is missing. unpriced counts the holding-days left out for want
        of a price."""
        if date_from is not None and date_to is not None and date_from > date_to:
            raise ToolError("date_to is before date_from.")

        async def read(db: Connection) -> tuple[outputs.Investments, int]:
            today = date.today()
            window = months_until(today, months)
            accounts = await views.investment_inputs(db, window)
            portfolios = [a.portfolio for a in accounts if a.portfolio is not None]
            prices, rates = PriceTable({}, {}), RateTable({})
            if days := [portfolio.on for portfolio in portfolios]:
                instruments = {i for portfolio in portfolios for i in portfolio.instrument_ids}
                prices = await views.price_table(db, instruments, min(days), max(days))
                wanted = {portfolio.currency for portfolio in portfolios} | prices.currencies
                rates = await views.rate_table(db, wanted, min(days), max(days))
            overview = compute_investments(accounts, window, prices, rates)

            inputs = await views.returns_inputs(db, accounts)
            prices, rates = PriceTable({}, {}), RateTable({})
            if (needed := tables_needed(inputs, today, date_from, date_to)) is not None:
                instruments, wanted, first, last = needed
                prices = await views.price_table(db, instruments, first, last)
                rates = await views.rate_table(db, wanted | prices.currencies, first, last)
            returns = compute_returns(inputs, prices, rates, today, date_from, date_to).accounts
            for account in returns:
                account.points = [
                    point
                    for point in account.points
                    if point.on == account.date_to or _ends_period(point.on, every)
                ]
            result = outputs.Investments(
                months=window, every=every, accounts=overview.accounts, returns=returns
            )
            return result, len(result.accounts)

        arguments = {"date_from": date_from, "date_to": date_to, "months": months, "every": every}
        return await self._call("investments", arguments, read)

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

    async def health_training(
        self,
        days: Annotated[
            TrainingPeriod,
            Field(description='The period ending today: "90", "180", "365" days, or "all".'),
        ] = TrainingPeriod.QUARTER,
    ) -> Training:
        """The user's training, as the Training page shows it. Per day, the load (an
        hrTSS-style score from heart rate), fitness (its 42-day average), fatigue (7-day) and
        form (fitness less fatigue) with its band; the summary with the ramp (fitness gained
        over 4 weeks, per week); hours per week by sport; the intensity split (time in zones 1
        and 2, 3, and 4 and 5) by sport; and totals per month, newest first. Fitness is
        computed over all history; the period only crops what is listed."""

        async def read(db: Connection) -> tuple[Training, int]:
            today = await views.health_today(db)
            result = training(await views.activity_rows(db), today, days)
            return result, len(result.points)

        return await self._call("health_training", {"days": days}, read)

    async def health_sleep(
        self,
        nights: Annotated[
            SleepNights, Field(description="How many nights the trends cover: 30, 90 or 365.")
        ] = SleepNights.MONTH,
        on: Annotated[
            date | None,
            Field(description="The night to detail: the day it ends (default: the latest)."),
        ] = None,
    ) -> outputs.HealthSleep:
        """The user's sleep, as the Sleep page shows it. trends: the nights up to the latest
        one, each with time slept and per stage (s), Garmin's need (min) and score, bed and
        wake time (minutes from the wake day's midnight, negative before it); the schedule's
        averages and spread; hours slept against the next morning's HRV; the score by weekday
        (0 is Monday). A night the watch wasn't worn is a gap, not zero. night: one night, with
        its stages against a typical night's shares, the 7-night average, sleep debt (need less
        slept, negative when ahead), and its heart rate, HRV, respiration and SpO2 as averages,
        lows and highs (without the overnight readings the page draws)."""

        async def read(db: Connection) -> tuple[outputs.HealthSleep, int]:
            days = await views.night_days(db)
            count = int(nights)
            end = days[-1] if days else date.today()
            start = end - timedelta(days=count - 1)
            hrv = await views.hrv_nights(db, start + timedelta(days=1), end + timedelta(days=1))
            trends = sleep_insights.trends(
                await views.nights(db, start, end),
                end,
                count,
                {day: row.last_night_avg for day, row in hrv.items()},
            )
            result = outputs.HealthSleep(
                trends=SleepTrends.model_validate(trends),
                night=await _sleep_night(db, days, on),
            )
            return result, result.trends.nights_worn

        return await self._call("health_sleep", {"nights": nights, "on": on}, read)

    async def health_recovery(
        self,
        days: Annotated[
            RecoveryPeriod, Field(description="The days ending today: 30, 90 or 365.")
        ] = RecoveryPeriod.QUARTER,
    ) -> Recovery:
        """The user's recovery, as the Recovery page shows it: overnight HRV (ms) against
        their normal range (the 60 nights before, mean ± 0.75 SD) with its 7-day average and
        swing; resting heart rate (bpm) and its 7-day average; Body Battery at waking, charged
        and drained (0 to 100); stress (0 to 100, and seconds per level); and today's signals
        (HRV, resting heart rate, sleep, Body Battery, form), each ok or not. A day without
        data is a gap."""

        async def read(db: Connection) -> tuple[Recovery, int]:
            today = await views.health_today(db)
            facts = await views.recovery_facts(db, today, days.value)
            form = current_form(await views.activity_rows(db), today)
            return recovery(facts, today, days.value, form), len(facts)

        return await self._call("health_recovery", {"days": days}, read)

    async def health_performance(
        self,
        period: Annotated[
            PerformancePeriod,
            Field(description="season (this calendar year), 90d or all, to today."),
        ] = "season",
    ) -> Performance:
        """The user's performance, as the Performance page shows it: the period's best
        power, pace and heart rate per duration; critical power (W) and W' (J), critical speed
        (m/s) and D' (m), and the swim threshold, from those bests; the VO2max trend
        (Hubnisio's own, from runs); race predictions from VO2max and from a recent race-length
        effort, which are estimates, not results; easy-run efficiency (speed per heartbeat);
        the bike's bests and climbs; and records (run and swim distances, bike durations,
        triathlons). Times in s, speeds in m/s, distances in m."""

        async def read(db: Connection) -> tuple[Performance, int]:
            today = await views.health_today(db)
            rows = await views.activity_facts(db)
            result = performance(
                rows,
                today,
                period,
                zone3_floor=await views.run_zone3_floor(db),
                weight_kg=await views.latest_weight(db, today),
            )
            return result, len(rows)

        return await self._call("health_performance", {"period": period}, read)

    async def health_body(
        self,
        days: Annotated[
            BodyPeriod, Field(description='The days ending today: "90", "365", or "all".')
        ] = BodyPeriod.YEAR,
    ) -> Body:
        """The user's body, as the Body page shows it: weigh-ins (kg; a day's latest counts)
        with BMI and body fat (%), the change over the period and against their goal, and
        Garmin's fitness age against their age."""

        async def read(db: Connection) -> tuple[Body, int]:
            today = await views.health_today(db)
            weigh_ins, readings, goal = await views.body_facts(db)
            window = None if days is BodyPeriod.ALL else int(days.value)
            return body(weigh_ins, readings, goal, today, window), len(weigh_ins)

        return await self._call("health_body", {"days": days}, read)

    async def health_activities(
        self,
        activity_id: Annotated[
            int | None,
            Field(description="One activity, in full: the other arguments are then ignored."),
        ] = None,
        sport: Annotated[
            str | None,
            Field(
                max_length=48,
                description="Part of Garmin's type key: running, trail_running, cycling, "
                "lap_swimming, open_water_swimming, multi_sport, strength_training, …",
            ),
        ] = None,
        date_from: date | None = None,
        date_to: date | None = None,
        text: Annotated[str | None, Field(max_length=100, description="Part of the name.")] = None,
        limit: Limit = 50,
    ) -> outputs.HealthActivitiesResult:
        """The user's activities, newest first: Garmin's summary of each, with Hubnisio's
        load and VO2max estimate. With activity_id, that one activity in full instead
        (detail): every summary field, what Hubnisio derived from its file (time moving, the
        heart-rate reference, time in zones, best power, heart rate and speed per duration,
        best efforts by distance, graded pace, efficiency and decoupling, climbs) and its
        laps. A multisport activity (a triathlon) is a parent whose legs are activities of
        their own. Units: s, m, m/s, bpm, W."""
        arguments = {
            "activity_id": activity_id,
            "sport": sport,
            "date_from": date_from,
            "date_to": date_to,
            "text": text,
            "limit": limit,
        }
        if activity_id is not None:

            async def detail(db: Connection) -> tuple[outputs.HealthActivitiesResult, int]:
                rows = await _dicts(
                    db,
                    "SELECT * FROM analytics.health_activities WHERE activity_id = %s",
                    [activity_id],
                )
                if not rows:
                    raise ToolError(f"No activity {activity_id}.")
                laps = await _dicts(
                    db,
                    "SELECT * FROM analytics.health_activity_laps WHERE activity_id = %s"
                    " ORDER BY lap_index",
                    [activity_id],
                )
                found = outputs.HealthActivityDetail.model_validate(
                    rows[0]
                    | {
                        "curve_durations_s": list(CURVE_DURATIONS),
                        "laps": [outputs.HealthLap.model_validate(lap) for lap in laps],
                    }
                )
                return outputs.HealthActivitiesResult(matched=1, activities=[], detail=found), 1

            return await self._call("health_activities", arguments, detail)

        conditions: list[LiteralString] = ["true"]
        params: list[Any] = []
        filters: list[tuple[Any, LiteralString]] = [
            (sport and f"%{_escape_like(sport.strip())}%", "sport ILIKE %s"),
            (text and text.strip() and f"%{_escape_like(text.strip())}%", "name ILIKE %s"),
            (date_from, "day >= %s"),
            (date_to, "day <= %s"),
        ]
        for value, condition in filters:
            if value:
                conditions.append(condition)
                params.append(value)
        query = sql.SQL(
            "SELECT *, count(*) OVER () AS matched FROM analytics.health_activities"
            " WHERE {} ORDER BY started_at DESC, activity_id DESC LIMIT %s"
        ).format(_all(conditions))

        async def search(db: Connection) -> tuple[outputs.HealthActivitiesResult, int]:
            rows = await _dicts(db, query, [*params, limit])
            found = [outputs.HealthActivity.model_validate(row) for row in rows]
            matched = rows[0]["matched"] if rows else 0
            result = outputs.HealthActivitiesResult(matched=matched, activities=found)
            return result, len(found)

        return await self._call("health_activities", arguments, search)

    async def query_sql(
        self, query: Annotated[str, Field(description="One PostgreSQL query.")]
    ) -> outputs.QueryResult:
        """A read-only SQL query over the analytics views, for what the other tools don't
        answer. It runs as `SELECT * FROM (<query>) q LIMIT 500` in a read-only transaction
        with a 5-second timeout, so it must be a single query that returns rows.

        The views (bare names work): me, accounts, visible_accounts, transactions,
        monthly_category_spend, categories, merchants, budgets, budget_limits,
        recurring_payments, balances, daily_movements, account_connections, fx_rates,
        portfolios, holdings, fills, instruments, instrument_prices; and the user's own
        health: health_connection, health_activities, health_activity_laps,
        health_daily_summaries, health_sleeps, health_hrv_nights, health_wake_battery,
        health_heart_rate_zones, health_weights, health_weight_goal, health_fitness_ages.
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
        tools.investments,
        tools.uncategorized_overview,
        tools.health_training,
        tools.health_sleep,
        tools.health_recovery,
        tools.health_performance,
        tools.health_activities,
        tools.health_body,
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


async def _sleep_night(db: Connection, days: list[date], on: date | None) -> SleepNight:
    """The Sleep page's night, from the night's summary alone: the overnight readings stay out
    of the views (ADR-0009, "As built in H9")."""
    day = on or (days[-1] if days else None)
    if day is None:
        return SleepNight(day=None, night=None, previous_day=None, next_day=None)
    previous_day, next_day = sleep_insights.neighbours(days, day)
    rows = await views.nights(db, day - timedelta(days=NIGHT_WINDOW), day)
    hrv = await views.hrv_nights(db, day, day)
    found = sleep_insights.night_detail(rows, day, hrv_night=hrv.get(day))
    night = NightOut.model_validate(found) if found else None
    return SleepNight(day=day, night=night, previous_day=previous_day, next_day=next_day)


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
