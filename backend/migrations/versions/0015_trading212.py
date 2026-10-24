"""Trading 212 as a provider (ADR-0008, slice T1): investment accounts, and connections that
hold the name of an API key's file instead of a bank consent.

Revision ID: 0015
Revises: 0014
Create Date: 2026-10-24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Not usable in this transaction, and nothing here uses it.
    op.execute("ALTER TYPE finance.provider ADD VALUE IF NOT EXISTS 'trading212'")
    op.add_column(
        "accounts",
        sa.Column("is_investment", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        schema="finance",
    )
    op.add_column(
        "connections", sa.Column("key_file", sa.String(length=100), nullable=True), schema="finance"
    )
    # A broker has no country to link it by.
    op.alter_column(
        "connections",
        "institution_country",
        existing_type=sa.String(length=2),
        nullable=True,
        schema="finance",
    )


def downgrade() -> None:
    # Trading 212 connections stay, with an empty country. Postgres can't drop an enum value,
    # so `trading212` stays in finance.provider; the upgrade adds it only if it's missing.
    op.execute(
        "UPDATE finance.connections SET institution_country = '' WHERE institution_country IS NULL"
    )
    op.alter_column(
        "connections",
        "institution_country",
        existing_type=sa.String(length=2),
        nullable=False,
        schema="finance",
    )
    op.drop_column("connections", "key_file", schema="finance")
    op.drop_column("accounts", "is_investment", schema="finance")
