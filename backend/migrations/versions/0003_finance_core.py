"""Create the finance core: connections, accounts, raw payloads, transactions (ADR-0007).

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-22
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "accounts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("household_id", sa.Uuid(), nullable=False),
        sa.Column("identification_hash", sa.Text(), nullable=True),
        sa.Column("iban", sa.String(length=34), nullable=True),
        sa.Column("institution_name", sa.String(length=100), nullable=False),
        sa.Column("holder_name", sa.Text(), nullable=True),
        sa.Column("product", sa.Text(), nullable=True),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("cash_account_type", sa.String(length=4), nullable=True),
        sa.Column("display_name", sa.String(length=100), nullable=True),
        sa.Column(
            "visibility",
            sa.Enum("shared", "private", name="account_visibility", schema="finance"),
            server_default="shared",
            nullable=False,
        ),
        sa.Column(
            "include_in_net_worth", sa.Boolean(), server_default=sa.text("true"), nullable=False
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
            name="fk_accounts_household_id_households",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_accounts"),
        schema="finance",
    )
    op.create_index(
        "uq_accounts_household_id_iban",
        "accounts",
        ["household_id", "iban"],
        unique=True,
        schema="finance",
        postgresql_where=sa.text("iban IS NOT NULL"),
    )
    op.create_index(
        "uq_accounts_household_id_identification_hash",
        "accounts",
        ["household_id", "identification_hash"],
        unique=True,
        schema="finance",
        postgresql_where=sa.text("identification_hash IS NOT NULL"),
    )
    op.create_table(
        "connections",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("household_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column(
            "provider", sa.Enum("enable_banking", name="provider", schema="finance"), nullable=False
        ),
        sa.Column("institution_name", sa.String(length=100), nullable=False),
        sa.Column("institution_country", sa.String(length=2), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "pending",
                "active",
                "expired",
                "revoked",
                "failed",
                name="connection_status",
                schema="finance",
            ),
            nullable=False,
        ),
        sa.Column("session_id_encrypted", sa.Text(), nullable=True),
        sa.Column("auth_state_hash", sa.String(length=64), nullable=True),
        sa.Column("valid_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["household_id"],
            ["core.households.id"],
            name="fk_connections_household_id_households",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["core.users.id"], name="fk_connections_user_id_users", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_connections"),
        sa.UniqueConstraint("auth_state_hash", name="uq_connections_auth_state_hash"),
        schema="finance",
    )
    op.create_table(
        "account_owners",
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["finance.accounts.id"],
            name="fk_account_owners_account_id_accounts",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["core.users.id"],
            name="fk_account_owners_user_id_users",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("account_id", "user_id", name="pk_account_owners"),
        schema="finance",
    )
    op.create_table(
        "provider_accounts",
        sa.Column("connection_id", sa.Uuid(), nullable=False),
        sa.Column("provider_account_uid", sa.Text(), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["finance.accounts.id"],
            name="fk_provider_accounts_account_id_accounts",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["connection_id"],
            ["finance.connections.id"],
            name="fk_provider_accounts_connection_id_connections",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "connection_id", "provider_account_uid", name="pk_provider_accounts"
        ),
        sa.UniqueConstraint(
            "connection_id", "account_id", name="uq_provider_accounts_connection_id_account_id"
        ),
        schema="finance",
    )
    op.create_table(
        "sync_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("household_id", sa.Uuid(), nullable=False),
        sa.Column("connection_id", sa.Uuid(), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("trigger", sa.String(length=16), nullable=False),
        sa.Column("strategy", sa.String(length=16), nullable=False),
        sa.Column("date_from", sa.Date(), nullable=True),
        sa.Column("date_to", sa.Date(), nullable=True),
        sa.Column(
            "status",
            sa.Enum("running", "succeeded", "failed", name="sync_status", schema="finance"),
            nullable=False,
        ),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("transactions_seen", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("transactions_added", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["finance.accounts.id"],
            name="fk_sync_runs_account_id_accounts",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["connection_id"],
            ["finance.connections.id"],
            name="fk_sync_runs_connection_id_connections",
        ),
        sa.ForeignKeyConstraint(
            ["household_id"],
            ["core.households.id"],
            name="fk_sync_runs_household_id_households",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_sync_runs"),
        schema="finance",
    )
    op.create_table(
        "balance_snapshots",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("household_id", sa.Uuid(), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("sync_run_id", sa.Uuid(), nullable=True),
        sa.Column("balance_type", sa.String(length=4), nullable=False),
        sa.Column("amount", sa.Numeric(precision=19, scale=4), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("reference_date", sa.Date(), nullable=True),
        sa.Column("last_change_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "fetched_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["finance.accounts.id"],
            name="fk_balance_snapshots_account_id_accounts",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["household_id"],
            ["core.households.id"],
            name="fk_balance_snapshots_household_id_households",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["sync_run_id"],
            ["finance.sync_runs.id"],
            name="fk_balance_snapshots_sync_run_id_sync_runs",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_balance_snapshots"),
        schema="finance",
    )
    op.create_index(
        "ix_balance_snapshots_account_id_fetched_at",
        "balance_snapshots",
        ["account_id", "fetched_at"],
        unique=False,
        schema="finance",
    )
    op.create_table(
        "provider_payloads",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("household_id", sa.Uuid(), nullable=False),
        sa.Column("connection_id", sa.Uuid(), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=True),
        sa.Column("sync_run_id", sa.Uuid(), nullable=True),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("request", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("response", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "fetched_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["finance.accounts.id"],
            name="fk_provider_payloads_account_id_accounts",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["connection_id"],
            ["finance.connections.id"],
            name="fk_provider_payloads_connection_id_connections",
        ),
        sa.ForeignKeyConstraint(
            ["household_id"],
            ["core.households.id"],
            name="fk_provider_payloads_household_id_households",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["sync_run_id"],
            ["finance.sync_runs.id"],
            name="fk_provider_payloads_sync_run_id_sync_runs",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_provider_payloads"),
        schema="finance",
    )
    op.create_index(
        "ix_provider_payloads_account_id_fetched_at",
        "provider_payloads",
        ["account_id", "fetched_at"],
        unique=False,
        schema="finance",
    )
    op.create_table(
        "transactions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("household_id", sa.Uuid(), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column(
            "status",
            sa.Enum("booked", "pending", name="transaction_status", schema="finance"),
            nullable=False,
        ),
        sa.Column("entry_reference", sa.Text(), nullable=True),
        sa.Column("fingerprint", sa.String(length=64), nullable=False),
        sa.Column("occurrence_index", sa.SmallInteger(), nullable=False),
        sa.Column("amount", sa.Numeric(precision=19, scale=4), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("original_amount", sa.Numeric(precision=19, scale=4), nullable=True),
        sa.Column("original_currency", sa.String(length=3), nullable=True),
        sa.Column("occurred_on", sa.Date(), nullable=False),
        sa.Column("booking_date", sa.Date(), nullable=True),
        sa.Column("value_date", sa.Date(), nullable=True),
        sa.Column("transaction_date", sa.Date(), nullable=True),
        sa.Column("counterparty_name", sa.Text(), nullable=True),
        sa.Column("counterparty_iban", sa.String(length=34), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("reference", sa.Text(), nullable=True),
        sa.Column("mcc", sa.String(length=4), nullable=True),
        sa.Column("bank_transaction_code", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("balance_after", sa.Numeric(precision=19, scale=4), nullable=True),
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
            name="fk_transactions_account_id_accounts",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["household_id"],
            ["core.households.id"],
            name="fk_transactions_household_id_households",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["payload_id"],
            ["finance.provider_payloads.id"],
            name="fk_transactions_payload_id_provider_payloads",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_transactions"),
        schema="finance",
    )
    op.create_index(
        "ix_transactions_account_id_occurred_on",
        "transactions",
        ["account_id", "occurred_on", "id"],
        unique=False,
        schema="finance",
    )
    op.create_index(
        "uq_transactions_account_id_entry_reference",
        "transactions",
        ["account_id", "entry_reference"],
        unique=True,
        schema="finance",
        postgresql_where=sa.text("status = 'booked' AND entry_reference IS NOT NULL"),
    )
    op.create_index(
        "uq_transactions_account_id_fingerprint",
        "transactions",
        ["account_id", "fingerprint", "occurrence_index"],
        unique=True,
        schema="finance",
        postgresql_where=sa.text("status = 'booked' AND entry_reference IS NULL"),
    )


def downgrade() -> None:
    op.drop_table("transactions", schema="finance")
    op.drop_table("provider_payloads", schema="finance")
    op.drop_table("balance_snapshots", schema="finance")
    op.drop_table("sync_runs", schema="finance")
    op.drop_table("provider_accounts", schema="finance")
    op.drop_table("account_owners", schema="finance")
    op.drop_table("connections", schema="finance")
    op.drop_table("accounts", schema="finance")
    for enum_type in (
        "transaction_status",
        "sync_status",
        "connection_status",
        "account_visibility",
        "provider",
    ):
        op.execute(f"DROP TYPE finance.{enum_type}")
