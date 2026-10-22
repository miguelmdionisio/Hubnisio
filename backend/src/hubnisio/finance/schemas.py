"""Request and response models of the finance API. Money is sent as decimal strings."""

import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, Field

from hubnisio.finance.categorize.rules import Action, Condition
from hubnisio.finance.models import (
    AccountVisibility,
    CategoryKind,
    ConnectionStatus,
    RuleMatch,
    Source,
    TransactionKind,
    TransactionStatus,
)


class Bank(BaseModel):
    name: str
    country: str
    logo: str | None
    beta: bool


class StartConnection(BaseModel):
    institution_name: str = Field(min_length=1, max_length=100)
    country: str = Field(pattern=r"^[A-Z]{2}$")


class StartedConnection(BaseModel):
    url: str  # send the browser here


class CompleteConnection(BaseModel):
    code: str = Field(min_length=1)
    state: str = Field(min_length=1)


class ConnectionOut(BaseModel):
    id: uuid.UUID
    institution_name: str
    institution_country: str
    status: ConnectionStatus
    valid_until: datetime | None
    days_left: int | None  # days until the consent expires; warn from 14
    last_synced_at: datetime | None
    syncing: bool
    last_error: str | None  # error code of the latest finished sync, if it failed
    account_ids: list[uuid.UUID]


class SyncQueued(BaseModel):
    queued: bool  # false when a sync was already waiting


class Balance(BaseModel):
    balance_type: str
    amount: Decimal
    currency: str
    fetched_at: datetime


class AccountOut(BaseModel):
    id: uuid.UUID
    name: str
    institution_name: str
    iban_masked: str | None
    currency: str
    cash_account_type: str | None
    visibility: AccountVisibility
    include_in_net_worth: bool
    is_owner: bool
    balance: Balance | None


class AccountUpdate(BaseModel):
    display_name: str | None = Field(default=None, max_length=100)
    visibility: AccountVisibility | None = None
    include_in_net_worth: bool | None = None


class TransactionCategory(BaseModel):
    id: uuid.UUID
    name: str
    group_name: str | None
    source: Source  # manual, rule, counterparty or ai


class TransactionCounterparty(BaseModel):
    id: uuid.UUID
    name: str
    source: Source | None


class TransactionTransfer(BaseModel):
    id: uuid.UUID
    other_transaction_id: uuid.UUID
    other_account_id: uuid.UUID
    other_account_name: str
    source: Source


class TransactionOut(BaseModel):
    id: uuid.UUID
    account_id: uuid.UUID
    status: TransactionStatus
    occurred_on: date
    booking_date: date | None
    value_date: date | None
    amount: Decimal
    currency: str
    original_amount: Decimal | None
    original_currency: str | None
    counterparty_name: str | None  # as the bank sent it
    description: str | None
    reference: str | None
    mcc: str | None
    bank_code: str | None
    # The user layer.
    kind: TransactionKind
    kind_source: Source | None  # set when the kind isn't just the sign
    category: TransactionCategory | None
    counterparty: TransactionCounterparty | None
    transfer: TransactionTransfer | None
    note: str | None
    tags: list[str]  # added by hand
    rule_tags: list[str]  # added by rules


class TransactionPage(BaseModel):
    items: list[TransactionOut]
    next_cursor: str | None


class TransactionUpdate(BaseModel):
    """Only the fields sent change. `null` hands a field back to the automatic layer
    (category, counterparty, kind) or clears it (note)."""

    category_id: uuid.UUID | None = None
    counterparty_id: uuid.UUID | None = None
    kind: TransactionKind | None = None
    note: str | None = Field(default=None, max_length=2000)
    tags: list[str] | None = Field(default=None, max_length=20)


class ApplyToCounterparty(BaseModel):
    """Offered after a category is set by hand: make it the counterparty's default too."""

    counterparty_id: uuid.UUID
    counterparty_name: str
    category_id: uuid.UUID
    other_transactions: int


class TransactionUpdated(BaseModel):
    transaction: TransactionOut
    offer: ApplyToCounterparty | None


class TransferLink(BaseModel):
    outgoing_id: uuid.UUID
    incoming_id: uuid.UUID


# Categories, counterparties, rules


class CategoryOut(BaseModel):
    id: uuid.UUID
    name: str
    kind: CategoryKind
    position: int
    archived: bool
    transactions: int  # visible transactions in it (a group's own count excludes children)


class CategoryGroupOut(CategoryOut):
    children: list[CategoryOut]


class CategoryCreate(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    parent_id: uuid.UUID | None = None  # none: a new group
    kind: CategoryKind | None = None  # groups only; categories take their group's kind


class CategoryUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=60)
    parent_id: uuid.UUID | None = None  # categories only: move to another group
    position: int | None = Field(default=None, ge=0, le=1000)
    archived: bool | None = None


class CounterpartyOut(BaseModel):
    id: uuid.UUID
    name: str
    default_category_id: uuid.UUID | None
    transactions: int
    aliases: list[str]


class CounterpartyUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    default_category_id: uuid.UUID | None = None  # null clears it


class CounterpartyMerge(BaseModel):
    into_id: uuid.UUID


class RuleIn(BaseModel):
    """The format of conditions and actions is described in categorize/rules.py."""

    name: str = Field(min_length=1, max_length=100)
    enabled: bool = True
    match: RuleMatch = RuleMatch.ALL
    conditions: list[Condition] = Field(min_length=1)
    actions: list[Action] = Field(min_length=1)
    stop_processing: bool = False


class RuleOut(RuleIn):
    id: uuid.UUID
    position: int


class RuleOrder(BaseModel):
    ids: list[uuid.UUID]


class RulePreviewIn(BaseModel):
    match: RuleMatch = RuleMatch.ALL
    conditions: list[Condition] = Field(min_length=1)


class RulePreview(BaseModel):
    matches: int
    examples: list[TransactionOut]


class RunResult(BaseModel):
    processed: int
    categorized: int
    counterparties_created: int


# Insights: amounts in euros, rounded to cents.


class SpendingCategory(BaseModel):
    id: uuid.UUID
    name: str
    amounts: list[Decimal]  # one per month; positive = spent, net of refunds


class SpendingGroup(SpendingCategory):
    categories: list[SpendingCategory]  # biggest first


class Spending(BaseModel):
    months: list[date]  # the first day of each month, oldest first
    groups: list[SpendingGroup]  # expense groups with any spending, biggest first
    uncategorized: list[Decimal]  # expenses without a category, per month
    unconverted: int  # transactions left out: no exchange rate for their day


class CashFlowMonth(BaseModel):
    month: date
    income: Decimal
    spending: Decimal
    net: Decimal


class CashFlow(BaseModel):
    months: list[CashFlowMonth]  # oldest first
    unconverted: int


class NetWorthPoint(BaseModel):
    on: date
    amount: Decimal


class NetWorthAccount(BaseModel):
    id: uuid.UUID
    name: str
    currency: str
    balance: Decimal | None  # today, in the account's currency; None: no balance yet
    balance_eur: Decimal | None  # None: no balance, or no exchange rate
    as_of: date | None  # the date of the bank's latest balance


class NetWorthOut(BaseModel):
    total: Decimal  # today
    points: list[NetWorthPoint]  # daily, oldest first
    accounts: list[NetWorthAccount]  # the accounts included in net worth
    unconverted: int  # account-days left out: no exchange rate
