"""Let an owner hide an account: out of lists, net worth and the sync, its history kept.

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "accounts",
        sa.Column("hidden_at", sa.DateTime(timezone=True), nullable=True),
        schema="finance",
    )


def downgrade() -> None:
    op.drop_column("accounts", "hidden_at", schema="finance")
