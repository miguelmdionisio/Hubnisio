"""Add daily exchange rates into EUR.

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-22
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    postgresql.ENUM("ecb", "currency_api", name="fx_source", schema="finance").create(op.get_bind())
    op.create_table(
        "fx_rates",
        sa.Column("quote_currency", sa.String(length=3), nullable=False),
        sa.Column("on", sa.Date(), nullable=False),
        sa.Column("rate", sa.Numeric(precision=20, scale=10), nullable=False),
        sa.Column(
            "source",
            postgresql.ENUM(name="fx_source", schema="finance", create_type=False),
            nullable=False,
        ),
        sa.Column(
            "fetched_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("rate > 0", name=op.f("ck_fx_rates_rate_positive")),
        sa.PrimaryKeyConstraint("quote_currency", "on", name="pk_fx_rates"),
        schema="finance",
    )


def downgrade() -> None:
    op.drop_table("fx_rates", schema="finance")
    op.execute("DROP TYPE finance.fx_source")
