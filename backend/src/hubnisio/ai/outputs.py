"""What the tools return, where the app has no schema of its own. Amounts are signed (negative =
money out) unless a field says "spent"; euro amounts are rounded to cents."""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel

from hubnisio.finance import schemas
from hubnisio.finance.models import (
    AccountVisibility,
    Cadence,
    CategoryKind,
    RecurringStatus,
    Review,
    Source,
    TransactionKind,
    TransactionStatus,
)
from hubnisio.finance.scoping import View


class Category(BaseModel):
    id: uuid.UUID
    name: str
    kind: CategoryKind
    group_id: uuid.UUID  # the group, or the category itself if it's a group
    group: str
    archived: bool


class Categories(BaseModel):
    categories: list[Category]  # each group first, then its categories


class Account(BaseModel):
    id: uuid.UUID
    name: str
    institution: str | None
    currency: str
    account_type: str | None  # the bank's code: CACC current, SVGS savings, CARD, LOAN, …
    visibility: AccountVisibility  # private: only its owners see it
    is_owner: bool
    is_pot: bool  # a shared pot: left out of the personal view
    pot_category_id: uuid.UUID | None  # money moved into the pot is spending here, personally
    include_in_net_worth: bool


class Accounts(BaseModel):
    accounts: list[Account]


class Transaction(BaseModel):
    id: uuid.UUID
    account_id: uuid.UUID
    account: str
    status: TransactionStatus
    occurred_on: date
    amount: Decimal
    currency: str
    eur_amount: Decimal | None  # None: no exchange rate for its day
    kind: TransactionKind
    in_mine: bool  # counts in the personal view (pot moves count there in the pot's category)
    description: str | None
    bank_counterparty: str | None  # as the bank sent it
    merchant_id: uuid.UUID | None
    merchant: str | None
    category_id: uuid.UUID | None
    category: str | None
    group: str | None
    category_source: Source | None  # manual > rule > counterparty (merchant default) > ai
    tags: list[str]  # added by hand
    rule_tags: list[str]  # added by rules
    note: str | None


class Transactions(BaseModel):
    matched: int  # every transaction that matches; at most `limit` are listed
    transactions: list[Transaction]  # newest first


class RecurringPayment(BaseModel):
    id: uuid.UUID
    name: str
    account_id: uuid.UUID
    account: str
    merchant_id: uuid.UUID | None
    cadence: Cadence
    kind: TransactionKind
    expected_amount: Decimal
    currency: str
    amount_varies: bool
    occurrences: int
    first_seen_on: date
    last_seen_on: date
    next_expected_on: date
    previous_amount: Decimal | None  # before the last price change
    amount_changed_on: date | None
    status: RecurringStatus  # today
    review: Review  # only confirmed ones count in upcoming payments


class RecurringPayments(BaseModel):
    payments: list[RecurringPayment]  # active first, then by next expected date


class AccountBalance(BaseModel):
    account_id: uuid.UUID
    name: str
    currency: str
    # The bank's latest balance, spendable first: what the Accounts page shows.
    balance: Decimal | None
    balance_type: str | None  # ISO 20022: ITAV interim available, CLBD closing booked, …
    fetched_at: datetime | None
    in_net_worth: bool  # counts in this view's net worth
    # Today's balance as net worth counts it: the latest booked balance, moved by the booked
    # transactions since its date (as_of).
    balance_today: Decimal | None
    balance_today_eur: Decimal | None  # None: no balance, or no exchange rate for today
    as_of: date | None


class Balances(BaseModel):
    view: View
    net_worth: Decimal  # today, in euros: the accounts with in_net_worth
    accounts: list[AccountBalance]  # every account that isn't hidden
    unconverted: int  # accounts in net worth left out: no exchange rate for today


Every = Literal["day", "week", "month"]


class NetWorthHistory(BaseModel):
    view: View
    every: Every
    total: Decimal  # today, in euros
    points: list[schemas.NetWorthPoint]  # oldest first: each day, Sunday or month end, and today
    accounts: list[schemas.NetWorthAccount]  # those in net worth, with their balance today
    unconverted: int  # account-days of the daily series left out: no exchange rate


class UncategorizedGroup(BaseModel):
    merchant_id: uuid.UUID | None  # set when the transactions have a merchant
    name: str  # the merchant, else the description without digits
    transactions: int
    spent: Decimal  # euros, positive = spent
    first_on: date
    last_on: date
    examples: list[str]  # up to 3 descriptions, the most frequent first


class UncategorizedOverview(BaseModel):
    view: View
    groups: list[UncategorizedGroup]  # the most spent first
    group_count: int  # every group, listed or not
    transactions: int
    spent: Decimal  # euros, positive = spent
    unconverted: int  # transactions left out: no exchange rate for their day


class QueryResult(BaseModel):
    columns: list[str]
    rows: list[list[Any]]  # numbers with decimals come as strings, dates as ISO strings
    truncated: bool  # the query returned more rows than are listed


class SuggestionResult(BaseModel):
    category_id: uuid.UUID
    merchant_id: uuid.UUID | None
    description: str | None
    written: int  # transactions that now have the suggestion
    # Asked for but left alone: not booked, a transfer, not the user's to see, or already
    # categorized by the user, a rule or a merchant's default.
    skipped: int


class Suggested(BaseModel):
    results: list[SuggestionResult]  # one per suggestion, in order
    written: int
    skipped: int
