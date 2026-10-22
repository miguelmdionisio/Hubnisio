"""Add recurring series, found by detection, and each transaction's link to one.

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-22
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _enum(name: str) -> postgresql.ENUM:
    return postgresql.ENUM(name=name, schema="finance", create_type=False)


def upgrade() -> None:
    bind = op.get_bind()
    postgresql.ENUM(
        "weekly", "monthly", "quarterly", "yearly", name="cadence", schema="finance"
    ).create(bind)
    postgresql.ENUM(
        "active", "dormant", "cancelled", name="recurring_status", schema="finance"
    ).create(bind)
    postgresql.ENUM(
        "suggested", "confirmed", "dismissed", name="recurring_review", schema="finance"
    ).create(bind)
    op.create_table(
        "recurring_series",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("household_id", sa.Uuid(), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("counterparty_id", sa.Uuid(), nullable=True),
        sa.Column("match_key", sa.Text(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("custom_name", sa.String(length=100), nullable=True),
        sa.Column("cadence", _enum("cadence"), nullable=False),
        sa.Column("kind", _enum("transaction_kind"), nullable=False),
        sa.Column("expected_amount", sa.Numeric(precision=19, scale=4), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("amount_varies", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("occurrences", sa.Integer(), nullable=False),
        sa.Column("first_seen_on", sa.Date(), nullable=False),
        sa.Column("last_seen_on", sa.Date(), nullable=False),
        sa.Column("next_expected_on", sa.Date(), nullable=False),
        sa.Column("previous_amount", sa.Numeric(precision=19, scale=4), nullable=True),
        sa.Column("amount_changed_on", sa.Date(), nullable=True),
        sa.Column("status", _enum("recurring_status"), nullable=False),
        sa.Column("review", _enum("recurring_review"), server_default="suggested", nullable=False),
        sa.Column("cancelled_on", sa.Date(), nullable=True),
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
            ["account_id"],
            ["finance.accounts.id"],
            name=op.f("fk_recurring_series_account_id_accounts"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["counterparty_id"],
            ["finance.counterparties.id"],
            name=op.f("fk_recurring_series_counterparty_id_counterparties"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["household_id"],
            ["core.households.id"],
            name=op.f("fk_recurring_series_household_id_households"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_recurring_series")),
        schema="finance",
    )
    op.create_index(
        "ix_finance_recurring_series_account_id",
        "recurring_series",
        ["account_id"],
        unique=False,
        schema="finance",
    )
    op.create_index(
        "ix_finance_recurring_series_household_id",
        "recurring_series",
        ["household_id"],
        unique=False,
        schema="finance",
    )
    op.add_column(
        "transaction_annotations",
        sa.Column("recurring_series_id", sa.Uuid(), nullable=True),
        schema="finance",
    )
    op.create_foreign_key(
        op.f("fk_transaction_annotations_recurring_series_id_recurring_series"),
        "transaction_annotations",
        "recurring_series",
        ["recurring_series_id"],
        ["id"],
        source_schema="finance",
        referent_schema="finance",
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_finance_transaction_annotations_recurring_series_id",
        "transaction_annotations",
        ["recurring_series_id"],
        unique=False,
        schema="finance",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_finance_transaction_annotations_recurring_series_id",
        table_name="transaction_annotations",
        schema="finance",
    )
    op.drop_constraint(
        op.f("fk_transaction_annotations_recurring_series_id_recurring_series"),
        "transaction_annotations",
        schema="finance",
        type_="foreignkey",
    )
    op.drop_column("transaction_annotations", "recurring_series_id", schema="finance")
    op.drop_index(
        "ix_finance_recurring_series_household_id",
        table_name="recurring_series",
        schema="finance",
    )
    op.drop_index(
        "ix_finance_recurring_series_account_id", table_name="recurring_series", schema="finance"
    )
    op.drop_table("recurring_series", schema="finance")
    op.execute("DROP TYPE finance.recurring_review")
    op.execute("DROP TYPE finance.recurring_status")
    op.execute("DROP TYPE finance.cadence")
