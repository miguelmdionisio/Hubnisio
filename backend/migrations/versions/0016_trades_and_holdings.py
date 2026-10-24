"""Trades and holdings (ADR-0008, slice T2): instruments, global like `fx_rates`; an
investment account's order fills; and its portfolio snapshots, each with the holdings its sync
read. All bank facts, written only by the sync.

Revision ID: 0016
Revises: 0015
Create Date: 2026-10-24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0016"
down_revision: str | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "instruments",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("ticker", sa.String(length=40), nullable=False),
        sa.Column("isin", sa.String(length=12), nullable=True),
        sa.Column("name", sa.Text(), nullable=True),
        sa.Column("currency", sa.String(length=3), nullable=True),
        sa.Column("type", sa.String(length=32), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_instruments")),
        sa.UniqueConstraint("ticker", name=op.f("uq_instruments_ticker")),
        schema="finance",
    )
    op.create_table(
        "portfolio_snapshots",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("household_id", sa.Uuid(), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("sync_run_id", sa.Uuid(), nullable=True),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("total_value", sa.Numeric(precision=19, scale=4), nullable=False),
        sa.Column("cash", sa.Numeric(precision=19, scale=4), nullable=False),
        sa.Column("cash_in_pies", sa.Numeric(precision=19, scale=4), nullable=False),
        sa.Column("cash_reserved", sa.Numeric(precision=19, scale=4), nullable=False),
        sa.Column("investments_value", sa.Numeric(precision=19, scale=4), nullable=True),
        sa.Column("investments_cost", sa.Numeric(precision=19, scale=4), nullable=True),
        sa.Column("realised_result", sa.Numeric(precision=19, scale=4), nullable=True),
        sa.Column("unrealised_result", sa.Numeric(precision=19, scale=4), nullable=True),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["finance.accounts.id"],
            name=op.f("fk_portfolio_snapshots_account_id_accounts"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["household_id"],
            ["core.households.id"],
            name=op.f("fk_portfolio_snapshots_household_id_households"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["sync_run_id"],
            ["finance.sync_runs.id"],
            name=op.f("fk_portfolio_snapshots_sync_run_id_sync_runs"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_portfolio_snapshots")),
        schema="finance",
    )
    op.create_index(
        "ix_portfolio_snapshots_account_id_fetched_at",
        "portfolio_snapshots",
        ["account_id", "fetched_at"],
        unique=False,
        schema="finance",
    )
    op.create_table(
        "fills",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("household_id", sa.Uuid(), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("instrument_id", sa.Uuid(), nullable=False),
        sa.Column("fill_id", sa.BigInteger(), nullable=False),
        sa.Column("order_id", sa.BigInteger(), nullable=True),
        sa.Column("side", sa.String(length=4), nullable=False),
        sa.Column("fill_type", sa.String(length=32), nullable=False),
        sa.Column("order_type", sa.String(length=16), nullable=True),
        sa.Column("initiated_from", sa.String(length=32), nullable=True),
        sa.Column("filled_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("quantity", sa.Numeric(precision=24, scale=10), nullable=False),
        sa.Column("price", sa.Numeric(precision=24, scale=10), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=True),
        sa.Column("fx_rate", sa.Numeric(precision=20, scale=10), nullable=True),
        sa.Column("net_value", sa.Numeric(precision=19, scale=4), nullable=True),
        sa.Column("realised_result", sa.Numeric(precision=19, scale=4), nullable=True),
        sa.Column(
            "taxes",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'"),
            nullable=False,
        ),
        sa.Column("payload_id", sa.Uuid(), nullable=False),
        sa.Column(
            "first_seen_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "last_seen_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["finance.accounts.id"],
            name=op.f("fk_fills_account_id_accounts"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["household_id"],
            ["core.households.id"],
            name=op.f("fk_fills_household_id_households"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["instrument_id"],
            ["finance.instruments.id"],
            name=op.f("fk_fills_instrument_id_instruments"),
        ),
        sa.ForeignKeyConstraint(
            ["payload_id"],
            ["finance.provider_payloads.id"],
            name=op.f("fk_fills_payload_id_provider_payloads"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_fills")),
        sa.UniqueConstraint("account_id", "fill_id", name="uq_fills_account_id_fill_id"),
        schema="finance",
    )
    op.create_index(
        "ix_fills_account_id_filled_at",
        "fills",
        ["account_id", "filled_at"],
        unique=False,
        schema="finance",
    )
    op.create_index(
        op.f("ix_finance_fills_instrument_id"),
        "fills",
        ["instrument_id"],
        unique=False,
        schema="finance",
    )
    op.create_table(
        "holding_snapshots",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("household_id", sa.Uuid(), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("portfolio_snapshot_id", sa.Uuid(), nullable=False),
        sa.Column("instrument_id", sa.Uuid(), nullable=False),
        sa.Column("quantity", sa.Numeric(precision=24, scale=10), nullable=False),
        sa.Column("quantity_in_pies", sa.Numeric(precision=24, scale=10), nullable=True),
        sa.Column("average_price", sa.Numeric(precision=24, scale=10), nullable=True),
        sa.Column("current_price", sa.Numeric(precision=24, scale=10), nullable=True),
        sa.Column("currency", sa.String(length=3), nullable=True),
        sa.Column("value", sa.Numeric(precision=19, scale=4), nullable=True),
        sa.Column("cost", sa.Numeric(precision=19, scale=4), nullable=True),
        sa.Column("unrealised_result", sa.Numeric(precision=19, scale=4), nullable=True),
        sa.Column("fx_impact", sa.Numeric(precision=19, scale=4), nullable=True),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["finance.accounts.id"],
            name=op.f("fk_holding_snapshots_account_id_accounts"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["household_id"],
            ["core.households.id"],
            name=op.f("fk_holding_snapshots_household_id_households"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["instrument_id"],
            ["finance.instruments.id"],
            name=op.f("fk_holding_snapshots_instrument_id_instruments"),
        ),
        sa.ForeignKeyConstraint(
            ["portfolio_snapshot_id"],
            ["finance.portfolio_snapshots.id"],
            name=op.f("fk_holding_snapshots_portfolio_snapshot_id_portfolio_snapshots"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_holding_snapshots")),
        schema="finance",
    )
    op.create_index(
        op.f("ix_finance_holding_snapshots_instrument_id"),
        "holding_snapshots",
        ["instrument_id"],
        unique=False,
        schema="finance",
    )
    op.create_index(
        op.f("ix_finance_holding_snapshots_portfolio_snapshot_id"),
        "holding_snapshots",
        ["portfolio_snapshot_id"],
        unique=False,
        schema="finance",
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_finance_holding_snapshots_portfolio_snapshot_id"),
        table_name="holding_snapshots",
        schema="finance",
    )
    op.drop_index(
        op.f("ix_finance_holding_snapshots_instrument_id"),
        table_name="holding_snapshots",
        schema="finance",
    )
    op.drop_table("holding_snapshots", schema="finance")
    op.drop_index(op.f("ix_finance_fills_instrument_id"), table_name="fills", schema="finance")
    op.drop_index("ix_fills_account_id_filled_at", table_name="fills", schema="finance")
    op.drop_table("fills", schema="finance")
    op.drop_index(
        "ix_portfolio_snapshots_account_id_fetched_at",
        table_name="portfolio_snapshots",
        schema="finance",
    )
    op.drop_table("portfolio_snapshots", schema="finance")
    op.drop_table("instruments", schema="finance")
