"""The `analytics` views loaded into the app's own dataclasses, so the app's pure functions
compute the AI's figures and they match the pages (tests/test_ai.py checks it). The views are
already scoped to the member whose login runs the query."""

import uuid
from collections import defaultdict
from datetime import date
from decimal import Decimal
from typing import Any

from psycopg import AsyncConnection

from hubnisio.finance.budgets import BudgetSpec
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
