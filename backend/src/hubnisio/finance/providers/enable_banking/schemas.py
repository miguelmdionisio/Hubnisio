"""Enable Banking response models, for the fields the hub reads.

Unknown fields are kept (`extra="allow"`), and the raw JSON is stored separately anyway, so a
field we don't model yet is never lost. Transactions stay raw dicts here: the normalizer parses
them one by one, so one odd transaction can't fail a whole page.
"""

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict


class _Model(BaseModel):
    model_config = ConfigDict(extra="allow")


class Aspsp(_Model):
    """A bank (Account Servicing Payment Service Provider)."""

    name: str
    country: str
    logo: str | None = None
    psu_types: list[str] = []
    maximum_consent_validity: int | None = None  # seconds
    required_psu_headers: list[str] = []
    beta: bool = False


class AspspList(_Model):
    aspsps: list[Aspsp]


class AuthorizationStarted(_Model):
    url: str
    authorization_id: str
    psu_id_hash: str | None = None


class OtherIdentification(_Model):
    identification: str
    scheme_name: str | None = None


class AccountIdentification(_Model):
    iban: str | None = None
    other: OtherIdentification | None = None


class SessionAccount(_Model):
    uid: str
    identification_hash: str | None = None
    account_id: AccountIdentification | None = None
    name: str | None = None  # holder name(s)
    details: str | None = None  # a label; some banks repeat the holder name here
    product: str | None = None
    cash_account_type: str | None = None
    currency: str


class Access(_Model):
    valid_until: datetime


class SessionAspsp(_Model):
    name: str
    country: str


class Session(_Model):
    """POST /sessions: the session created from an authorization code."""

    session_id: str
    accounts: list[SessionAccount]
    aspsp: SessionAspsp
    psu_type: str | None = None
    access: Access


class AccountData(_Model):
    uid: str
    identification_hash: str | None = None


class SessionStatus(_Model):
    """GET /sessions/{id}."""

    status: str  # AUTHORIZED, EXPIRED, REVOKED, CLOSED, ...
    accounts: list[str] = []
    accounts_data: list[AccountData] = []
    access: Access | None = None


class Amount(_Model):
    currency: str
    amount: Decimal


class Balance(_Model):
    name: str | None = None
    balance_amount: Amount
    balance_type: str
    last_change_date_time: datetime | None = None
    reference_date: date | None = None


class BalanceList(_Model):
    balances: list[Balance]


class TransactionsPage(_Model):
    # A flat list per the API reference; some banks have sent {"booked": [...], "pending": [...]}.
    transactions: list[dict[str, Any]] | dict[str, Any] = []
    continuation_key: str | None = None


class Party(_Model):
    name: str | None = None


class ExchangeRate(_Model):
    unit_currency: str | None = None
    exchange_rate: str | None = None
    rate_type: str | None = None
    # The original-currency amount of a cross-currency card payment.
    instructed_amount: Amount | None = None


class BankTransaction(_Model):
    """One item of a transactions page. Parsed by the normalizer, one item at a time."""

    entry_reference: str | None = None
    transaction_amount: Amount
    credit_debit_indicator: str | None = None  # CRDT (in) / DBIT (out)
    status: str | None = None  # BOOK, PDNG, HOLD, SCHD, CNCL, RJCT, OTHR
    booking_date: date | None = None
    value_date: date | None = None
    transaction_date: date | None = None
    creditor: Party | None = None
    creditor_account: AccountIdentification | None = None
    debtor: Party | None = None
    debtor_account: AccountIdentification | None = None
    remittance_information: list[str] | None = None
    reference_number: str | None = None
    merchant_category_code: str | None = None
    bank_transaction_code: dict[str, Any] | None = None
    balance_after_transaction: Amount | None = None
    exchange_rate: ExchangeRate | None = None
