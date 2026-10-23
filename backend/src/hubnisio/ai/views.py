"""The `analytics` views loaded into the app's own dataclasses, so the app's pure functions
compute the AI's figures and they match the pages (tests/test_ai.py checks it). The views are
already scoped to the member whose login runs the query."""

import uuid
from collections import defaultdict
from collections.abc import Iterable
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from psycopg import AsyncConnection

from hubnisio.finance.budgets import BudgetSpec
from hubnisio.finance.fx.convert import BASE_CURRENCY, MAX_RATE_AGE_DAYS, RateTable
from hubnisio.finance.insights.net_worth import Anchor, IncludedAccount, NetWorthInputs
from hubnisio.finance.insights.spending import CategoryInfo, MonthlySums, month_start
from hubnisio.finance.models import CategoryKind, Overspend, TransactionKind
from hubnisio.finance.scoping import View

Connection = AsyncConnection[tuple[Any, ...]]


async def monthly_sums(connection: Connection, view: View, first: date, last: date) -> MonthlySums:
    """What `monthly_sums` gives for the months from `first`'s to `last`'s."""
    cursor = await connection.execute(
        "SELECT month, category_id, kind, eur, unconverted FROM analytics.monthly_category_spend"
        " WHERE view = %s AND month BETWEEN %s AND %s",
        [view, month_start(first), month_start(last)],
    )
    sums = MonthlySums()
    for month, category_id, kind, eur, unconverted in await cursor.fetchall():
        sums.add(month, category_id, TransactionKind(kind), eur, unconverted)
    return sums


async def categories(connection: Connection) -> dict[uuid.UUID, CategoryInfo]:
    """What `household_categories` gives: archived categories too."""
    cursor = await connection.execute(
        "SELECT id, name, kind, parent_id, position FROM analytics.categories"
    )
    return {
        id_: CategoryInfo(id_, name, CategoryKind(kind), parent_id, position)
        for id_, name, kind, parent_id, position in await cursor.fetchall()
    }


async def budget_specs(connection: Connection) -> list[BudgetSpec]:
    """The budgets `budgets_for_month` computes: the overall one and those on a category."""
    limits: dict[uuid.UUID, list[tuple[date, Decimal]]] = defaultdict(list)
    cursor = await connection.execute(
        "SELECT budget_id, starts_on, amount FROM analytics.budget_limits"
    )
    for budget_id, starts_on, amount in await cursor.fetchall():
        limits[budget_id].append((starts_on, amount))
    cursor = await connection.execute(
        "SELECT id, category_id, rollover, overspend FROM analytics.budgets"
    )
    return [
        BudgetSpec(category_id, rollover, Overspend(overspend), limits[id_])
        for id_, category_id, rollover, overspend in await cursor.fetchall()
    ]


async def balance_inputs(connection: Connection) -> NetWorthInputs:
    """What `load_inputs` gives, for every account that isn't hidden; `only` with
    `net_worth_accounts` narrows it to a view's net worth."""
    cursor = await connection.execute(
        "SELECT a.id, a.name, a.currency, b.booked_balance, b.booked_currency,"
        " coalesce(b.reference_date, b.fetched_at::date)"
        " FROM analytics.accounts a LEFT JOIN analytics.balances b ON b.account_id = a.id"
        " WHERE NOT a.hidden ORDER BY a.institution, a.name"
    )
    inputs = NetWorthInputs(accounts=[], anchors={})
    for id_, name, currency, amount, anchor_currency, on in await cursor.fetchall():
        inputs.accounts.append(IncludedAccount(id_, name, currency))
        if amount is not None:
            inputs.anchors[id_] = Anchor(amount, anchor_currency, on)
    if not inputs.anchors:
        return inputs

    daily: dict[uuid.UUID, dict[date, Decimal]] = defaultdict(dict)
    cursor = await connection.execute(
        "SELECT account_id, occurred_on, amount FROM analytics.daily_movements"
        " WHERE account_id = ANY(%s)",
        [list(inputs.anchors)],
    )
    for account_id, on, amount in await cursor.fetchall():
        daily[account_id][on] = amount
    inputs.daily = dict(daily)
    cursor = await connection.execute(
        "SELECT connection_id, account_id FROM analytics.account_connections"
        " WHERE account_id = ANY(%s)",
        [list(daily)],
    )
    inputs.links = [
        (connection_id, account_id) for connection_id, account_id in await cursor.fetchall()
    ]
    return inputs


async def net_worth_accounts(connection: Connection, view: View) -> set[uuid.UUID]:
    """The accounts net worth counts in `view`, as `listed_counted_account_ids` and
    `include_in_net_worth` give them."""
    cursor = await connection.execute(
        "SELECT id FROM analytics.accounts WHERE NOT hidden AND include_in_net_worth"
        " AND (%s = 'household' OR (is_owner AND NOT is_pot))",
        [view],
    )
    return {id_ for (id_,) in await cursor.fetchall()}


async def rate_table(
    connection: Connection, currencies: Iterable[str], first: date, last: date
) -> RateTable:
    """What `RateTable.load` gives."""
    wanted = {currency for currency in currencies if currency != BASE_CURRENCY}
    rates: dict[str, list[tuple[date, Decimal]]] = {currency: [] for currency in wanted}
    if wanted:
        cursor = await connection.execute(
            "SELECT currency, rate_date, rate FROM analytics.fx_rates"
            " WHERE currency = ANY(%s) AND rate_date BETWEEN %s AND %s ORDER BY rate_date",
            [list(wanted), first - timedelta(days=MAX_RATE_AGE_DAYS), last],
        )
        for currency, on, rate in await cursor.fetchall():
            rates[currency].append((on, rate))
    return RateTable(rates)
