"""Request and response models of the finance API. Money is sent as decimal strings."""

import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, Field

from hubnisio.finance.models import AccountVisibility, ConnectionStatus, TransactionStatus


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


class TransactionOut(BaseModel):
    id: uuid.UUID
    account_id: uuid.UUID
    status: TransactionStatus
    occurred_on: date
    booking_date: date | None
    amount: Decimal
    currency: str
    original_amount: Decimal | None
    original_currency: str | None
    counterparty_name: str | None
    description: str | None
    mcc: str | None


class TransactionPage(BaseModel):
    items: list[TransactionOut]
    next_cursor: str | None
