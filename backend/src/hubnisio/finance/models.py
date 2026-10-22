"""Finance tables (ADR-0007): provider connections, accounts, raw payloads and bank facts.

Only the sync writes `transactions` and `balance_snapshots`. Everything people, rules or the
AI decide about a transaction lives in separate tables (the user layer, added later), so a
sync never overwrites it.
"""

import enum
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from hubnisio.core.db import Base

SCHEMA = "finance"
# Signed amounts; 4 decimal places leaves room for currencies and FX beyond cents.
Money = Numeric(19, 4)


def _enum(python_enum: type[enum.StrEnum], name: str) -> Enum:
    return Enum(
        python_enum,
        name=name,
        schema=SCHEMA,
        values_callable=lambda members: [member.value for member in members],
    )


class ProviderName(enum.StrEnum):
    ENABLE_BANKING = "enable_banking"


class ConnectionStatus(enum.StrEnum):
    PENDING = "pending"  # authorization started; waiting for the bank to redirect back
    ACTIVE = "active"
    EXPIRED = "expired"  # consent ran out or the bank ended it; needs re-linking
    REVOKED = "revoked"  # closed by the user
    FAILED = "failed"  # authorization didn't complete


class AccountVisibility(enum.StrEnum):
    SHARED = "shared"  # every household member
    PRIVATE = "private"  # the account's owners only


class TransactionStatus(enum.StrEnum):
    BOOKED = "booked"
    PENDING = "pending"


class SyncStatus(enum.StrEnum):
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class Connection(Base):
    """One provider consent, owned by the user who gave it (PSD2 consent is personal)."""

    __tablename__ = "connections"
    __table_args__ = {"schema": SCHEMA}  # noqa: RUF012

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid7)
    household_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("core.households.id", ondelete="CASCADE")
    )
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("core.users.id", ondelete="CASCADE"))
    provider: Mapped[ProviderName] = mapped_column(_enum(ProviderName, "provider"))
    institution_name: Mapped[str] = mapped_column(String(100))
    institution_country: Mapped[str] = mapped_column(String(2))
    status: Mapped[ConnectionStatus] = mapped_column(_enum(ConnectionStatus, "connection_status"))
    # Encrypted with core.crypto; null until authorization completes.
    session_id_encrypted: Mapped[str | None] = mapped_column(Text)
    # SHA-256 of the `state` sent to the bank; lets the callback (even reloaded) find this row.
    auth_state_hash: Mapped[str | None] = mapped_column(String(64), unique=True)
    valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Account(Base):
    """A real bank account, stored once per household however many connections reach it."""

    __tablename__ = "accounts"
    __table_args__ = (
        Index(
            "uq_accounts_household_id_identification_hash",
            "household_id",
            "identification_hash",
            unique=True,
            postgresql_where=text("identification_hash IS NOT NULL"),
        ),
        Index(
            "uq_accounts_household_id_iban",
            "household_id",
            "iban",
            unique=True,
            postgresql_where=text("iban IS NOT NULL"),
        ),
        {"schema": SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid7)
    household_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("core.households.id", ondelete="CASCADE")
    )
    # Enable Banking's identification_hash: stable across sessions, unlike account UIDs.
    identification_hash: Mapped[str | None] = mapped_column(Text)
    iban: Mapped[str | None] = mapped_column(String(34))
    institution_name: Mapped[str] = mapped_column(String(100))
    holder_name: Mapped[str | None] = mapped_column(Text)
    product: Mapped[str | None] = mapped_column(Text)
    currency: Mapped[str] = mapped_column(String(3))
    cash_account_type: Mapped[str | None] = mapped_column(String(4))  # CACC, CARD, SVGS, ...
    display_name: Mapped[str | None] = mapped_column(String(100))
    visibility: Mapped[AccountVisibility] = mapped_column(
        _enum(AccountVisibility, "account_visibility"), server_default=AccountVisibility.SHARED
    )
    include_in_net_worth: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AccountOwner(Base):
    """Who owns an account; a joint account has two owners (ADR-0005)."""

    __tablename__ = "account_owners"
    __table_args__ = {"schema": SCHEMA}  # noqa: RUF012

    account_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("finance.accounts.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("core.users.id", ondelete="CASCADE"), primary_key=True
    )


class ProviderAccount(Base):
    """How a connection refers to an account. UIDs change with every new session."""

    __tablename__ = "provider_accounts"
    __table_args__ = (
        UniqueConstraint(
            "connection_id", "account_id", name="uq_provider_accounts_connection_id_account_id"
        ),
        {"schema": SCHEMA},
    )

    connection_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("finance.connections.id", ondelete="CASCADE"), primary_key=True
    )
    provider_account_uid: Mapped[str] = mapped_column(Text, primary_key=True)
    account_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("finance.accounts.id", ondelete="CASCADE")
    )


class SyncRun(Base):
    """One fetch of one account through one connection."""

    __tablename__ = "sync_runs"
    __table_args__ = {"schema": SCHEMA}  # noqa: RUF012

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid7)
    household_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("core.households.id", ondelete="CASCADE")
    )
    # Connections are never deleted while their data exists: closing one marks it revoked.
    connection_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("finance.connections.id"))
    account_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("finance.accounts.id", ondelete="CASCADE")
    )
    trigger: Mapped[str] = mapped_column(String(16))  # initial, scheduled, user
    strategy: Mapped[str] = mapped_column(String(16))  # default, longest
    date_from: Mapped[date | None] = mapped_column(Date)
    date_to: Mapped[date | None] = mapped_column(Date)
    status: Mapped[SyncStatus] = mapped_column(_enum(SyncStatus, "sync_status"))
    error_code: Mapped[str | None] = mapped_column(String(64))
    transactions_seen: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    transactions_added: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ProviderPayload(Base):
    """Every provider response, append-only. Normalization can be re-run from these rows."""

    __tablename__ = "provider_payloads"
    __table_args__ = (
        Index("ix_provider_payloads_account_id_fetched_at", "account_id", "fetched_at"),
        {"schema": SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid7)
    household_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("core.households.id", ondelete="CASCADE")
    )
    connection_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("finance.connections.id"))
    account_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("finance.accounts.id", ondelete="CASCADE")
    )
    sync_run_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("finance.sync_runs.id"))
    kind: Mapped[str] = mapped_column(String(32))  # session, balances, transactions
    request: Mapped[dict[str, Any]] = mapped_column(JSONB)
    response: Mapped[dict[str, Any]] = mapped_column(JSONB)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Transaction(Base):
    """A transaction as the bank reports it. Identity rules are in ADR-0007."""

    __tablename__ = "transactions"
    __table_args__ = (
        # Booked with a bank reference: the reference is the identity.
        Index(
            "uq_transactions_account_id_entry_reference",
            "account_id",
            "entry_reference",
            unique=True,
            postgresql_where=text("status = 'booked' AND entry_reference IS NOT NULL"),
        ),
        # Booked without one: fingerprint plus an index that tells identical twins apart.
        Index(
            "uq_transactions_account_id_fingerprint",
            "account_id",
            "fingerprint",
            "occurrence_index",
            unique=True,
            postgresql_where=text("status = 'booked' AND entry_reference IS NULL"),
        ),
        Index("ix_transactions_account_id_occurred_on", "account_id", "occurred_on", "id"),
        {"schema": SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid7)
    household_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("core.households.id", ondelete="CASCADE")
    )
    account_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("finance.accounts.id", ondelete="CASCADE")
    )
    status: Mapped[TransactionStatus] = mapped_column(
        _enum(TransactionStatus, "transaction_status")
    )
    # Null when the bank sends none, or sends the same one twice in a fetch.
    entry_reference: Mapped[str | None] = mapped_column(Text)
    fingerprint: Mapped[str] = mapped_column(String(64))
    occurrence_index: Mapped[int] = mapped_column(SmallInteger)
    amount: Mapped[Decimal] = mapped_column(Money)  # negative = money out
    currency: Mapped[str] = mapped_column(String(3))
    # The original-currency amount of a cross-currency payment, when the bank gives it.
    original_amount: Mapped[Decimal | None] = mapped_column(Money)
    original_currency: Mapped[str | None] = mapped_column(String(3))
    # Booking date, else transaction date, else value date: the date lists and reports use.
    occurred_on: Mapped[date] = mapped_column(Date)
    booking_date: Mapped[date | None] = mapped_column(Date)
    value_date: Mapped[date | None] = mapped_column(Date)
    transaction_date: Mapped[date | None] = mapped_column(Date)
    counterparty_name: Mapped[str | None] = mapped_column(Text)
    counterparty_iban: Mapped[str | None] = mapped_column(String(34))
    description: Mapped[str | None] = mapped_column(Text)
    reference: Mapped[str | None] = mapped_column(Text)
    mcc: Mapped[str | None] = mapped_column(String(4))
    bank_transaction_code: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    balance_after: Mapped[Decimal | None] = mapped_column(Money)
    # The latest payload that reported this transaction.
    payload_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("finance.provider_payloads.id"))
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class BalanceSnapshot(Base):
    """A bank-reported balance at one sync: the source of truth for balances."""

    __tablename__ = "balance_snapshots"
    __table_args__ = (
        Index("ix_balance_snapshots_account_id_fetched_at", "account_id", "fetched_at"),
        {"schema": SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid7)
    household_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("core.households.id", ondelete="CASCADE")
    )
    account_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("finance.accounts.id", ondelete="CASCADE")
    )
    sync_run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("finance.sync_runs.id", ondelete="SET NULL")
    )
    balance_type: Mapped[str] = mapped_column(String(4))  # CLBD, ITAV, ...
    amount: Mapped[Decimal] = mapped_column(Money)
    currency: Mapped[str] = mapped_column(String(3))
    reference_date: Mapped[date | None] = mapped_column(Date)
    last_change_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
