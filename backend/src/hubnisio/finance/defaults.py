"""What a new household starts with: a category tree and rules, all editable.

Migration 0004 seeds existing households from a frozen copy of these; change both together
only if existing households should get the change too (in a new migration).
"""

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from hubnisio.finance.models import Category, CategoryKind, Rule, RuleMatch

EXPENSE = CategoryKind.EXPENSE
INCOME = CategoryKind.INCOME

# Groups and the categories in them.
CATEGORIES: list[tuple[str, CategoryKind, list[str]]] = [
    (
        "Housing",
        EXPENSE,
        ["Rent & mortgage", "Utilities", "Internet & phone", "Home & garden", "Home insurance"],
    ),
    ("Food", EXPENSE, ["Groceries", "Restaurants", "Cafés & snacks", "Food delivery"]),
    (
        "Transport",
        EXPENSE,
        [
            "Fuel",
            "Public transport",
            "Taxi & ride-hailing",
            "Parking & tolls",
            "Car maintenance",
            "Car insurance",
        ],
    ),
    ("Shopping", EXPENSE, ["Clothing", "Electronics", "Household items", "Online shopping"]),
    ("Health", EXPENSE, ["Pharmacy", "Doctors & dentist", "Sport & fitness", "Health insurance"]),
    (
        "Leisure",
        EXPENSE,
        ["Entertainment", "Subscriptions", "Travel", "Hobbies", "Events & tickets"],
    ),
    ("Bills & fees", EXPENSE, ["Bank fees", "Taxes", "Other insurance"]),
    ("Personal", EXPENSE, ["Personal care", "Gifts & donations", "Education"]),
    ("Family", EXPENSE, ["Children", "Pets"]),
    ("Cash", EXPENSE, ["Cash withdrawals"]),
    ("Income", INCOME, ["Salary", "Refunds", "Interest", "Other income"]),
]

RULES: list[dict[str, Any]] = [
    {
        # Revolut moves money between its own currency accounts with unequal amounts, so
        # transfer matching (equal amounts) can't pair them.
        "name": "Currency exchanges between Revolut accounts are transfers",
        "match": RuleMatch.ALL,
        "conditions": [{"field": "bank_code", "op": "is", "value": "EXCHANGE"}],
        "actions": [{"type": "set_kind", "kind": "transfer"}],
    },
]


async def seed_household(session: AsyncSession, household_id: uuid.UUID) -> None:
    """Give a new household the default categories and rules. The caller commits."""
    for group_position, (group_name, kind, children) in enumerate(CATEGORIES):
        group = Category(
            household_id=household_id, name=group_name, kind=kind, position=group_position
        )
        session.add(group)
        await session.flush()
        session.add_all(
            Category(
                household_id=household_id,
                parent_id=group.id,
                name=name,
                kind=kind,
                position=position,
            )
            for position, name in enumerate(children)
        )
    session.add_all(
        Rule(household_id=household_id, position=position, **rule)
        for position, rule in enumerate(RULES)
    )
