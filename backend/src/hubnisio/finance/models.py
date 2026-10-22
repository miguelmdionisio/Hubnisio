"""Finance tables (ADR-0007): provider connections, accounts, raw payloads, bank facts, and
the user layer.

Only the sync writes `transactions` and `balance_snapshots`. Everything people, rules or the
AI decide about a transaction (category, counterparty, notes, tags, transfer links) lives in
the user-layer tables at the end of this module, so a sync never overwrites it.
"""

import enum
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
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
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

# Finance foreign keys point at core tables (households, users). SQLAlchemy resolves them only
# if core's models are loaded too, which a process using only finance code (the worker) wouldn't.
from hubnisio.core import models as core_models  # noqa: F401
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


class CategoryKind(enum.StrEnum):
    EXPENSE = "expense"
    INCOME = "income"


class TransactionKind(enum.StrEnum):
    """What a transaction is. Derived from its sign unless it's a transfer or overridden."""

    EXPENSE = "expense"
    INCOME = "income"
    TRANSFER = "transfer"  # between the household's own accounts: not income or spending


class Source(enum.StrEnum):
    """Who decided something in the user layer. Precedence (ADR-0007): manual > rule >
    counterparty (a merchant's default category) > ai."""

    MANUAL = "manual"
    RULE = "rule"
    COUNTERPARTY = "counterparty"
    AI = "ai"
    BANK = "bank"  # taken from the bank's data, e.g. its merchant name
    AUTO = "auto"  # found by the hub's own matching, e.g. a transfer pair


class RuleMatch(enum.StrEnum):
    ALL = "all"
    ANY = "any"


class Overspend(enum.StrEnum):
    """What overspending a budget does to the next month (ADR-0007, "Budgets")."""

    FORGIVE = "forgive"  # the next month starts fresh
    CARRY = "carry"  # the overspend is taken from the next month


class Cadence(enum.StrEnum):
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    QUARTERLY = "quarterly"
    YEARLY = "yearly"


class RecurringStatus(enum.StrEnum):
    ACTIVE = "active"  # the next payment isn't late yet
    DORMANT = "dormant"  # a payment is late
    CANCELLED = "cancelled"  # three missed in a row, or the user said it stopped


class Review(enum.StrEnum):
    """What the user made of a detected series. Only confirmed ones count (ADR-0007)."""

    SUGGESTED = "suggested"
    CONFIRMED = "confirmed"
    DISMISSED = "dismissed"  # not recurring: never suggested again


class FxSource(enum.StrEnum):
    ECB = "ecb"  # ECB euro foreign exchange reference rates
    CURRENCY_API = "currency_api"  # fawazahmed0's currency-api, for currencies the ECB lacks


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


class FxRate(Base):
    """Public reference data, so global (no household): how many units of a currency one euro
    bought on a day. A euro amount is the amount divided by the rate (finance/fx/convert.py)."""

    __tablename__ = "fx_rates"
    __table_args__ = (
        CheckConstraint("rate > 0", name="rate_positive"),  # the rate is a divisor
        {"schema": SCHEMA},
    )

    quote_currency: Mapped[str] = mapped_column(String(3), primary_key=True)
    on: Mapped[date] = mapped_column(Date, primary_key=True)
    rate: Mapped[Decimal] = mapped_column(Numeric(20, 10))  # units of quote_currency per 1 EUR
    source: Mapped[FxSource] = mapped_column(_enum(FxSource, "fx_source"))
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# User layer: written by people, rules, matching and (later) the AI; never by the sync.


class Category(Base):
    """Two levels: groups (no parent) and the categories within them."""

    __tablename__ = "categories"
    __table_args__ = (
        Index("ix_categories_household_id_parent_id", "household_id", "parent_id"),
        {"schema": SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid7)
    household_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("core.households.id", ondelete="CASCADE")
    )
    # Null: the household's. Room for personal categories later (ADR-0005).
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("core.users.id", ondelete="CASCADE")
    )
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("finance.categories.id", ondelete="CASCADE")
    )
    name: Mapped[str] = mapped_column(String(60))
    kind: Mapped[CategoryKind] = mapped_column(_enum(CategoryKind, "category_kind"))
    position: Mapped[int] = mapped_column(SmallInteger, server_default=text("0"))
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Counterparty(Base):
    """A merchant, employer or person, under a clean name."""

    __tablename__ = "counterparties"
    __table_args__ = {"schema": SCHEMA}  # noqa: RUF012

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid7)
    household_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("core.households.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(100))
    default_category_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("finance.categories.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CounterpartyAlias(Base):
    """A name the bank uses (as a match key) and the counterparty it means."""

    __tablename__ = "counterparty_aliases"
    __table_args__ = {"schema": SCHEMA}  # noqa: RUF012

    household_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("core.households.id", ondelete="CASCADE"), primary_key=True
    )
    alias_key: Mapped[str] = mapped_column(Text, primary_key=True)
    counterparty_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("finance.counterparties.id", ondelete="CASCADE"), index=True
    )


class TransactionAnnotation(Base):
    """Everything about one transaction that isn't a bank fact or its category."""

    __tablename__ = "transaction_annotations"
    __table_args__ = {"schema": SCHEMA}  # noqa: RUF012

    transaction_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("finance.transactions.id", ondelete="CASCADE"), primary_key=True
    )
    household_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("core.households.id", ondelete="CASCADE")
    )
    counterparty_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("finance.counterparties.id", ondelete="SET NULL"), index=True
    )
    counterparty_source: Mapped[Source | None] = mapped_column(_enum(Source, "source"))
    # Overrides the kind the sign implies, e.g. a deposit to a broker the hub doesn't sync yet.
    kind_override: Mapped[TransactionKind | None] = mapped_column(
        _enum(TransactionKind, "transaction_kind")
    )
    kind_source: Mapped[Source | None] = mapped_column(_enum(Source, "source"))
    note: Mapped[str | None] = mapped_column(Text)
    tags: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default=text("'{}'"))
    # Recomputed by every rules run; kept apart so a run never touches tags added by hand.
    rule_tags: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default=text("'{}'"))
    # The recurring series it belongs to, found by detection (finance/recurring).
    recurring_series_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("finance.recurring_series.id", ondelete="SET NULL"), index=True
    )
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Rule(Base):
    """Ordered conditions and actions; the format is defined in categorize/rules.py."""

    __tablename__ = "rules"
    __table_args__ = {"schema": SCHEMA}  # noqa: RUF012

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid7)
    household_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("core.households.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(100))
    position: Mapped[int] = mapped_column(Integer)
    enabled: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    match: Mapped[RuleMatch] = mapped_column(_enum(RuleMatch, "rule_match"))
    conditions: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)
    actions: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)
    stop_processing: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CategoryAssignment(Base):
    """A transaction's category. One row per transaction for now; the table allows several,
    so splits can come later without a schema change (ADR-0007)."""

    __tablename__ = "category_assignments"
    __table_args__ = {"schema": SCHEMA}  # noqa: RUF012

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid7)
    household_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("core.households.id", ondelete="CASCADE")
    )
    transaction_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("finance.transactions.id", ondelete="CASCADE"), index=True
    )
    category_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("finance.categories.id", ondelete="CASCADE"), index=True
    )
    amount: Mapped[Decimal | None] = mapped_column(Money)  # null: the whole transaction
    source: Mapped[Source] = mapped_column(_enum(Source, "source"))
    rule_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("finance.rules.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Transfer(Base):
    """Money moving between two of the household's accounts: not income, not spending."""

    __tablename__ = "transfers"
    __table_args__ = {"schema": SCHEMA}  # noqa: RUF012

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid7)
    household_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("core.households.id", ondelete="CASCADE")
    )
    outgoing_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("finance.transactions.id", ondelete="CASCADE"), unique=True
    )
    incoming_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("finance.transactions.id", ondelete="CASCADE"), unique=True
    )
    source: Mapped[Source] = mapped_column(_enum(Source, "source"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class TransferDismissal(Base):
    """A pair the user unlinked: transfer matching never links it again."""

    __tablename__ = "transfer_dismissals"
    __table_args__ = {"schema": SCHEMA}  # noqa: RUF012

    outgoing_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("finance.transactions.id", ondelete="CASCADE"), primary_key=True
    )
    incoming_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("finance.transactions.id", ondelete="CASCADE"), primary_key=True
    )
    household_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("core.households.id", ondelete="CASCADE")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Budget(Base):
    """A monthly limit on an expense category or group (ADR-0007, "Budgets"). Its amounts are
    in `budget_limits`; what's spent is computed on read (finance/budgets.py)."""

    __tablename__ = "budgets"
    __table_args__ = {"schema": SCHEMA}  # noqa: RUF012

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid7)
    household_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("core.households.id", ondelete="CASCADE"), index=True
    )
    category_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("finance.categories.id", ondelete="CASCADE"), unique=True
    )
    # Whether money left over carries into the next month.
    rollover: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    overspend: Mapped[Overspend] = mapped_column(
        _enum(Overspend, "overspend"), server_default=Overspend.FORGIVE
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class BudgetLimit(Base):
    """A budget's amount in euros from a month on, until its next row: changing a budget
    "from this month" keeps past months as they were."""

    __tablename__ = "budget_limits"
    __table_args__ = (
        CheckConstraint("amount >= 0", name="amount_not_negative"),
        CheckConstraint("extract(day from starts_on) = 1", name="starts_on_first_of_month"),
        {"schema": SCHEMA},
    )

    budget_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("finance.budgets.id", ondelete="CASCADE"), primary_key=True
    )
    starts_on: Mapped[date] = mapped_column(Date, primary_key=True)
    amount: Mapped[Decimal] = mapped_column(Money)


class RecurringSeries(Base):
    """Payments (or income) that repeat on a cadence, found by detection (ADR-0007). Detection
    rewrites everything but the user's choices: `review`, `custom_name`, `cancelled_on`."""

    __tablename__ = "recurring_series"
    __table_args__ = {"schema": SCHEMA}  # noqa: RUF012

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid7)
    household_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("core.households.id", ondelete="CASCADE"), index=True
    )
    # One account's payments, so the series has that account's visibility.
    account_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("finance.accounts.id", ondelete="CASCADE"), index=True
    )
    counterparty_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("finance.counterparties.id", ondelete="SET NULL")
    )
    match_key: Mapped[str] = mapped_column(Text)  # what its transactions were grouped by
    name: Mapped[str] = mapped_column(String(100))
    custom_name: Mapped[str | None] = mapped_column(String(100))
    cadence: Mapped[Cadence] = mapped_column(_enum(Cadence, "cadence"))
    kind: Mapped[TransactionKind] = mapped_column(_enum(TransactionKind, "transaction_kind"))
    expected_amount: Mapped[Decimal] = mapped_column(Money)  # signed, like transactions
    currency: Mapped[str] = mapped_column(String(3))
    amount_varies: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    occurrences: Mapped[int] = mapped_column(Integer)
    first_seen_on: Mapped[date] = mapped_column(Date)
    last_seen_on: Mapped[date] = mapped_column(Date)
    next_expected_on: Mapped[date] = mapped_column(Date)
    # The latest price change: the amount before it, and when the new one first appeared.
    previous_amount: Mapped[Decimal | None] = mapped_column(Money)
    amount_changed_on: Mapped[date | None] = mapped_column(Date)
    status: Mapped[RecurringStatus] = mapped_column(_enum(RecurringStatus, "recurring_status"))
    review: Mapped[Review] = mapped_column(
        _enum(Review, "recurring_review"), server_default=Review.SUGGESTED
    )
    cancelled_on: Mapped[date | None] = mapped_column(Date)  # set by the user
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
