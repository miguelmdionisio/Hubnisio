"""Let a budget have no category: the household's overall budget, on all spending.

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        "budgets", "category_id", existing_type=sa.Uuid(), nullable=True, schema="finance"
    )
    # The unique on category_id treats nulls as distinct, so one overall budget needs its own.
    op.create_index(
        "uq_budgets_household_id_overall",
        "budgets",
        ["household_id"],
        unique=True,
        schema="finance",
        postgresql_where=sa.text("category_id IS NULL"),
    )


def downgrade() -> None:
    # Its limits go with it (ON DELETE CASCADE).
    op.execute("DELETE FROM finance.budgets WHERE category_id IS NULL")
    op.drop_index(
        "uq_budgets_household_id_overall",
        table_name="budgets",
        schema="finance",
        postgresql_where=sa.text("category_id IS NULL"),
    )
    op.alter_column(
        "budgets", "category_id", existing_type=sa.Uuid(), nullable=False, schema="finance"
    )
