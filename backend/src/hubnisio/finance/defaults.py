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
    ("Income", INCOME, ["Salary", "Refunds", "Interest", "Dividends", "Other income"]),
]

# A `set_category` action names its category as (group, category); seeding puts in its ID.
RULES: list[dict[str, Any]] = [
    {
        # Revolut moves money between its own currency accounts with unequal amounts, so
        # transfer matching (equal amounts) can't pair them.
        "name": "Currency exchanges between Revolut accounts are transfers",
        "match": RuleMatch.ALL,
        "conditions": [{"field": "bank_code", "op": "is", "value": "EXCHANGE"}],
        "actions": [{"type": "set_kind", "kind": "transfer"}],
    },
    # Trading 212's cash movements and dividends (ADR-0008): its types, prefixed T212_.
    {
        "name": "Trading 212 dividends",
        "match": RuleMatch.ALL,
        "conditions": [{"field": "bank_code", "op": "is", "value": "T212_DIVIDEND"}],
        "actions": [{"type": "set_category", "category": ("Income", "Dividends")}],
    },
    {
        "name": "Trading 212 interest",
        "match": RuleMatch.ANY,
        "conditions": [
            {"field": "bank_code", "op": "is", "value": "T212_INTEREST_ON_FREE_CASH"},
            {"field": "bank_code", "op": "is", "value": "T212_LENDING_INTEREST"},
        ],
        "actions": [{"type": "set_category", "category": ("Income", "Interest")}],
    },
    {
        "name": "Trading 212 fees",
        "match": RuleMatch.ALL,
        "conditions": [{"field": "bank_code", "op": "is", "value": "T212_FEE"}],
        "actions": [{"type": "set_category", "category": ("Bills & fees", "Bank fees")}],
    },
    {
        "name": "Transfers between Trading 212 accounts are transfers",
        "match": RuleMatch.ALL,
        "conditions": [{"field": "bank_code", "op": "is", "value": "T212_TRANSFER"}],
        "actions": [{"type": "set_kind", "kind": "transfer"}],
    },
    {
        # Money moves only to and from the member's own accounts. Pairing still links the
        # bank's side when the hub has it (it runs first); this covers the ones it doesn't,
        # e.g. from before a bank's history starts.
        "name": "Trading 212 deposits and withdrawals are transfers",
        "match": RuleMatch.ANY,
        "conditions": [
            {"field": "bank_code", "op": "is", "value": "T212_DEPOSIT"},
            {"field": "bank_code", "op": "is", "value": "T212_WITHDRAW"},
        ],
        "actions": [{"type": "set_kind", "kind": "transfer"}],
    },
]


async def seed_household(session: AsyncSession, household_id: uuid.UUID) -> None:
    """Give a new household the default categories and rules. The caller commits."""
    ids: dict[tuple[str, str], uuid.UUID] = {}
    for group_position, (group_name, kind, children) in enumerate(CATEGORIES):
        group = Category(
            household_id=household_id, name=group_name, kind=kind, position=group_position
        )
        session.add(group)
        await session.flush()
        categories = [
            Category(
                household_id=household_id,
                parent_id=group.id,
                name=name,
                kind=kind,
                position=position,
            )
            for position, name in enumerate(children)
        ]
        session.add_all(categories)
        await session.flush()
        ids.update(((group_name, category.name), category.id) for category in categories)
    session.add_all(
        Rule(
            household_id=household_id,
            position=position,
            **{**rule, "actions": [_action(action, ids) for action in rule["actions"]]},
        )
        for position, rule in enumerate(RULES)
    )


def _action(action: dict[str, Any], ids: dict[tuple[str, str], uuid.UUID]) -> dict[str, Any]:
    if action["type"] != "set_category":
        return action
    return {"type": "set_category", "category_id": str(ids[action["category"]])}
