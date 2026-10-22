"""Add the finance user layer: categories, counterparties, rules, annotations, transfers.

Seeds every existing household with the default categories and rules. The seed data is a
frozen copy of hubnisio/finance/defaults.py as of this migration.

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-22
"""

import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


ENUMS = {
    "category_kind": ("expense", "income"),
    "transaction_kind": ("expense", "income", "transfer"),
    "source": ("manual", "rule", "counterparty", "ai", "bank", "auto"),
    "rule_match": ("all", "any"),
}

CATEGORIES = [
    (
        "Housing",
        "expense",
        ["Rent & mortgage", "Utilities", "Internet & phone", "Home & garden", "Home insurance"],
    ),
    ("Food", "expense", ["Groceries", "Restaurants", "Cafés & snacks", "Food delivery"]),
    (
        "Transport",
        "expense",
        [
            "Fuel",
            "Public transport",
            "Taxi & ride-hailing",
            "Parking & tolls",
            "Car maintenance",
            "Car insurance",
        ],
    ),
    ("Shopping", "expense", ["Clothing", "Electronics", "Household items", "Online shopping"]),
    ("Health", "expense", ["Pharmacy", "Doctors & dentist", "Sport & fitness", "Health insurance"]),
    (
        "Leisure",
        "expense",
        ["Entertainment", "Subscriptions", "Travel", "Hobbies", "Events & tickets"],
    ),
    ("Bills & fees", "expense", ["Bank fees", "Taxes", "Other insurance"]),
    ("Personal", "expense", ["Personal care", "Gifts & donations", "Education"]),
    ("Family", "expense", ["Children", "Pets"]),
    ("Cash", "expense", ["Cash withdrawals"]),
    ("Income", "income", ["Salary", "Refunds", "Interest", "Other income"]),
]
RULES = [
    {
        "name": "Currency exchanges between Revolut accounts are transfers",
        "match": "all",
        "conditions": [{"field": "bank_code", "op": "is", "value": "EXCHANGE"}],
        "actions": [{"type": "set_kind", "kind": "transfer"}],
    },
]


def upgrade() -> None:
    bind = op.get_bind()
    for name, values in ENUMS.items():
        postgresql.ENUM(*values, name=name, schema="finance").create(bind)

    op.create_table(
        "categories",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("household_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("parent_id", sa.Uuid(), nullable=True),
        sa.Column("name", sa.String(length=60), nullable=False),
        sa.Column(
            "kind",
            postgresql.ENUM(name="category_kind", schema="finance", create_type=False),
            nullable=False,
        ),
        sa.Column("position", sa.SmallInteger(), server_default=sa.text("0"), nullable=False),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["household_id"],
            ["core.households.id"],
            name="fk_categories_household_id_households",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["parent_id"],
            ["finance.categories.id"],
            name="fk_categories_parent_id_categories",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["core.users.id"],
            name="fk_categories_user_id_users",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_categories"),
        schema="finance",
    )
    op.create_index(
        "ix_categories_household_id_parent_id",
        "categories",
        ["household_id", "parent_id"],
        unique=False,
        schema="finance",
    )
    op.create_table(
        "rules",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("household_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column(
            "match",
            postgresql.ENUM(name="rule_match", schema="finance", create_type=False),
            nullable=False,
        ),
        sa.Column("conditions", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("actions", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("stop_processing", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["household_id"],
            ["core.households.id"],
            name="fk_rules_household_id_households",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_rules"),
        schema="finance",
    )
    op.create_index(
        "ix_finance_rules_household_id",
        "rules",
        ["household_id"],
        unique=False,
        schema="finance",
    )
    op.create_table(
        "counterparties",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("household_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("default_category_id", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["default_category_id"],
            ["finance.categories.id"],
            name="fk_counterparties_default_category_id_categories",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["household_id"],
            ["core.households.id"],
            name="fk_counterparties_household_id_households",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_counterparties"),
        schema="finance",
    )
    op.create_index(
        "ix_finance_counterparties_household_id",
        "counterparties",
        ["household_id"],
        unique=False,
        schema="finance",
    )
    op.create_table(
        "counterparty_aliases",
        sa.Column("household_id", sa.Uuid(), nullable=False),
        sa.Column("alias_key", sa.Text(), nullable=False),
        sa.Column("counterparty_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["counterparty_id"],
            ["finance.counterparties.id"],
            name="fk_counterparty_aliases_counterparty_id_counterparties",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["household_id"],
            ["core.households.id"],
            name="fk_counterparty_aliases_household_id_households",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("household_id", "alias_key", name="pk_counterparty_aliases"),
        schema="finance",
    )
    op.create_index(
        "ix_finance_counterparty_aliases_counterparty_id",
        "counterparty_aliases",
        ["counterparty_id"],
        unique=False,
        schema="finance",
    )
    op.create_table(
        "category_assignments",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("household_id", sa.Uuid(), nullable=False),
        sa.Column("transaction_id", sa.Uuid(), nullable=False),
        sa.Column("category_id", sa.Uuid(), nullable=False),
        sa.Column("amount", sa.Numeric(precision=19, scale=4), nullable=True),
        sa.Column(
            "source",
            postgresql.ENUM(name="source", schema="finance", create_type=False),
            nullable=False,
        ),
        sa.Column("rule_id", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["category_id"],
            ["finance.categories.id"],
            name="fk_category_assignments_category_id_categories",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["household_id"],
            ["core.households.id"],
            name="fk_category_assignments_household_id_households",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["rule_id"],
            ["finance.rules.id"],
            name="fk_category_assignments_rule_id_rules",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["transaction_id"],
            ["finance.transactions.id"],
            name="fk_category_assignments_transaction_id_transactions",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_category_assignments"),
        schema="finance",
    )
    op.create_index(
        "ix_finance_category_assignments_category_id",
        "category_assignments",
        ["category_id"],
        unique=False,
        schema="finance",
    )
    op.create_index(
        "ix_finance_category_assignments_transaction_id",
        "category_assignments",
        ["transaction_id"],
        unique=False,
        schema="finance",
    )
    op.create_table(
        "transaction_annotations",
        sa.Column("transaction_id", sa.Uuid(), nullable=False),
        sa.Column("household_id", sa.Uuid(), nullable=False),
        sa.Column("counterparty_id", sa.Uuid(), nullable=True),
        sa.Column(
            "counterparty_source",
            postgresql.ENUM(name="source", schema="finance", create_type=False),
            nullable=True,
        ),
        sa.Column(
            "kind_override",
            postgresql.ENUM(name="transaction_kind", schema="finance", create_type=False),
            nullable=True,
        ),
        sa.Column(
            "kind_source",
            postgresql.ENUM(name="source", schema="finance", create_type=False),
            nullable=True,
        ),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column(
            "tags", postgresql.ARRAY(sa.Text()), server_default=sa.text("'{}'"), nullable=False
        ),
        sa.Column(
            "rule_tags", postgresql.ARRAY(sa.Text()), server_default=sa.text("'{}'"), nullable=False
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["counterparty_id"],
            ["finance.counterparties.id"],
            name="fk_transaction_annotations_counterparty_id_counterparties",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["household_id"],
            ["core.households.id"],
            name="fk_transaction_annotations_household_id_households",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["transaction_id"],
            ["finance.transactions.id"],
            name="fk_transaction_annotations_transaction_id_transactions",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("transaction_id", name="pk_transaction_annotations"),
        schema="finance",
    )
    op.create_index(
        "ix_finance_transaction_annotations_counterparty_id",
        "transaction_annotations",
        ["counterparty_id"],
        unique=False,
        schema="finance",
    )
    op.create_table(
        "transfer_dismissals",
        sa.Column("outgoing_id", sa.Uuid(), nullable=False),
        sa.Column("incoming_id", sa.Uuid(), nullable=False),
        sa.Column("household_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["household_id"],
            ["core.households.id"],
            name="fk_transfer_dismissals_household_id_households",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["incoming_id"],
            ["finance.transactions.id"],
            name="fk_transfer_dismissals_incoming_id_transactions",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["outgoing_id"],
            ["finance.transactions.id"],
            name="fk_transfer_dismissals_outgoing_id_transactions",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("outgoing_id", "incoming_id", name="pk_transfer_dismissals"),
        schema="finance",
    )
    op.create_table(
        "transfers",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("household_id", sa.Uuid(), nullable=False),
        sa.Column("outgoing_id", sa.Uuid(), nullable=False),
        sa.Column("incoming_id", sa.Uuid(), nullable=False),
        sa.Column(
            "source",
            postgresql.ENUM(name="source", schema="finance", create_type=False),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["household_id"],
            ["core.households.id"],
            name="fk_transfers_household_id_households",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["incoming_id"],
            ["finance.transactions.id"],
            name="fk_transfers_incoming_id_transactions",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["outgoing_id"],
            ["finance.transactions.id"],
            name="fk_transfers_outgoing_id_transactions",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_transfers"),
        sa.UniqueConstraint("incoming_id", name="uq_transfers_incoming_id"),
        sa.UniqueConstraint("outgoing_id", name="uq_transfers_outgoing_id"),
        schema="finance",
    )

    _seed_existing_households()


def _seed_existing_households() -> None:
    categories = sa.table(
        "categories",
        sa.column("id", sa.Uuid()),
        sa.column("household_id", sa.Uuid()),
        sa.column("parent_id", sa.Uuid()),
        sa.column("name", sa.String()),
        sa.column(
            "kind", postgresql.ENUM(name="category_kind", schema="finance", create_type=False)
        ),
        sa.column("position", sa.SmallInteger()),
        schema="finance",
    )
    rules = sa.table(
        "rules",
        sa.column("id", sa.Uuid()),
        sa.column("household_id", sa.Uuid()),
        sa.column("name", sa.String()),
        sa.column("position", sa.Integer()),
        sa.column("match", postgresql.ENUM(name="rule_match", schema="finance", create_type=False)),
        sa.column("conditions", postgresql.JSONB()),
        sa.column("actions", postgresql.JSONB()),
        schema="finance",
    )
    households = op.get_bind().execute(sa.text("SELECT id FROM core.households")).scalars().all()
    for household_id in households:
        rows = []
        for group_position, (group, kind, children) in enumerate(CATEGORIES):
            group_id = uuid.uuid7()
            rows.append(
                {
                    "id": group_id,
                    "household_id": household_id,
                    "parent_id": None,
                    "name": group,
                    "kind": kind,
                    "position": group_position,
                }
            )
            rows.extend(
                {
                    "id": uuid.uuid7(),
                    "household_id": household_id,
                    "parent_id": group_id,
                    "name": name,
                    "kind": kind,
                    "position": position,
                }
                for position, name in enumerate(children)
            )
        op.bulk_insert(categories, rows)
        op.bulk_insert(
            rules,
            [
                {"id": uuid.uuid7(), "household_id": household_id, "position": position, **rule}
                for position, rule in enumerate(RULES)
            ],
        )


def downgrade() -> None:
    op.drop_table("transfers", schema="finance")
    op.drop_table("transfer_dismissals", schema="finance")
    op.drop_index(
        "ix_finance_transaction_annotations_counterparty_id",
        table_name="transaction_annotations",
        schema="finance",
    )
    op.drop_table("transaction_annotations", schema="finance")
    op.drop_index(
        "ix_finance_category_assignments_transaction_id",
        table_name="category_assignments",
        schema="finance",
    )
    op.drop_index(
        "ix_finance_category_assignments_category_id",
        table_name="category_assignments",
        schema="finance",
    )
    op.drop_table("category_assignments", schema="finance")
    op.drop_index(
        "ix_finance_counterparty_aliases_counterparty_id",
        table_name="counterparty_aliases",
        schema="finance",
    )
    op.drop_table("counterparty_aliases", schema="finance")
    op.drop_index(
        "ix_finance_counterparties_household_id",
        table_name="counterparties",
        schema="finance",
    )
    op.drop_table("counterparties", schema="finance")
    op.drop_index("ix_finance_rules_household_id", table_name="rules", schema="finance")
    op.drop_table("rules", schema="finance")
    op.drop_index("ix_categories_household_id_parent_id", table_name="categories", schema="finance")
    op.drop_table("categories", schema="finance")
    for name in ENUMS:
        op.execute(f"DROP TYPE finance.{name}")
