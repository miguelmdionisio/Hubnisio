"""Add budgets: a monthly limit per category, with rollover and overspend settings.

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-22
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    postgresql.ENUM("forgive", "carry", name="overspend", schema="finance").create(op.get_bind())
    op.create_table(
        "budgets",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("household_id", sa.Uuid(), nullable=False),
        sa.Column("category_id", sa.Uuid(), nullable=False),
        sa.Column("rollover", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column(
            "overspend",
            postgresql.ENUM(name="overspend", schema="finance", create_type=False),
            server_default="forgive",
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["category_id"],
            ["finance.categories.id"],
            name=op.f("fk_budgets_category_id_categories"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["household_id"],
            ["core.households.id"],
            name=op.f("fk_budgets_household_id_households"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_budgets")),
        sa.UniqueConstraint("category_id", name=op.f("uq_budgets_category_id")),
        schema="finance",
    )
    op.create_index(
        "ix_finance_budgets_household_id",
        "budgets",
        ["household_id"],
        unique=False,
        schema="finance",
    )
    op.create_table(
        "budget_limits",
        sa.Column("budget_id", sa.Uuid(), nullable=False),
        sa.Column("starts_on", sa.Date(), nullable=False),
        sa.Column("amount", sa.Numeric(precision=19, scale=4), nullable=False),
        sa.CheckConstraint("amount >= 0", name=op.f("ck_budget_limits_amount_not_negative")),
        sa.CheckConstraint(
            "extract(day from starts_on) = 1",
            name=op.f("ck_budget_limits_starts_on_first_of_month"),
        ),
        sa.ForeignKeyConstraint(
            ["budget_id"],
            ["finance.budgets.id"],
            name=op.f("fk_budget_limits_budget_id_budgets"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("budget_id", "starts_on", name=op.f("pk_budget_limits")),
        schema="finance",
    )


def downgrade() -> None:
    op.drop_table("budget_limits", schema="finance")
    op.drop_index("ix_finance_budgets_household_id", table_name="budgets", schema="finance")
    op.drop_table("budgets", schema="finance")
    op.execute("DROP TYPE finance.overspend")
