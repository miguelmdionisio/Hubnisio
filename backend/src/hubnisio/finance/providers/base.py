"""What every data source gives the sync (ADR-0003).

Linking differs too much between sources to share an interface (a bank redirect and consent
for Enable Banking, an API key for Trading 212), so each provider exposes its own. Fetching is
shared: a provider yields raw responses, the sync stores each one in
`finance.provider_payloads`, and the provider's `Normalizer` turns them into records.
"""

from collections.abc import AsyncIterator, Callable, Mapping
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Protocol

from hubnisio.finance.models import TransactionStatus


@dataclass(frozen=True, slots=True)
class Fetched[T]:
    """One provider response: what was asked, the raw JSON, and its parsed form."""

    kind: str  # e.g. "balances", "transactions"
    request: dict[str, Any]
    raw: dict[str, Any]
    data: T


class Provider(Protocol):
    def fetch(
        self,
        account_uid: str,
        since: date | None,
        psu_headers: Mapping[str, str] | None = None,
    ) -> AsyncIterator[Fetched[Any]]:
        """Yield every response needed to bring one account up to date.

        `since=None` asks for the longest history the source offers (the first sync).
        `psu_headers` are given only when the user is present and triggered the fetch.
        """
        ...


@dataclass(frozen=True, slots=True)
class TransactionRecord:
    """A transaction as the provider reports it: the bank facts, before identity is assigned."""

    status: TransactionStatus
    amount: Decimal  # negative = money out
    currency: str
    occurred_on: date  # booking date, else transaction date, else value date
    entry_reference: str | None = None
    original_amount: Decimal | None = None
    original_currency: str | None = None
    booking_date: date | None = None
    value_date: date | None = None
    transaction_date: date | None = None
    counterparty_name: str | None = None
    counterparty_iban: str | None = None
    description: str | None = None
    reference: str | None = None
    mcc: str | None = None
    bank_transaction_code: dict[str, Any] | None = None
    balance_after: Decimal | None = None


@dataclass(frozen=True, slots=True)
class BalanceRecord:
    balance_type: str
    amount: Decimal
    currency: str
    reference_date: date | None = None
    last_change_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class NormalizedPage:
    records: list[TransactionRecord] = field(default_factory=list)
    skipped: int = 0  # items that couldn't be parsed
    ignored: int = 0  # items in a state the hub doesn't store, e.g. cancelled or rejected


@dataclass(frozen=True, slots=True)
class Normalizer:
    """Turns one provider's raw payloads into records. Pure: no I/O, no clock."""

    transactions: Callable[[dict[str, Any]], NormalizedPage]
    balances: Callable[[dict[str, Any]], list[BalanceRecord]]
