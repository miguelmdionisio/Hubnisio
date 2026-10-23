"""Let an owner mark an account as a shared pot, with a category for contributions.

Revision ID: 0010
Revises: 0009
Create Date: 2026-10-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "accounts",
        sa.Column("is_pot", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        schema="finance",
    )
    op.add_column(
        "accounts", sa.Column("pot_category_id", sa.Uuid(), nullable=True), schema="finance"
    )
    op.create_foreign_key(
        op.f("fk_accounts_pot_category_id_categories"),
        "accounts",
        "categories",
        ["pot_category_id"],
        ["id"],
        source_schema="finance",
        referent_schema="finance",
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f("fk_accounts_pot_category_id_categories"),
        "accounts",
        schema="finance",
        type_="foreignkey",
    )
    op.drop_column("accounts", "pot_category_id", schema="finance")
    op.drop_column("accounts", "is_pot", schema="finance")
