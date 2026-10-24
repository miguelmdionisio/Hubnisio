"""Trading 212 payloads → records (ADR-0008). Pure functions, so `cli renormalize` can rebuild
an account from its stored payloads.

- The summary becomes one balance, of type `TVAL`: the account's total value, cash plus
  holdings at market value.
- Cash movements and dividends become booked transactions. Their entry reference is the
  endpoint and Trading 212's reference (`transactions:…`, `dividends:…`), and their bank code
  is the type with a `T212_` prefix: Revolut sends `TRANSFER` and `FEE` too, so a rule on the
  bare type would catch Revolut payments.
- Withdrawals and fees are money out whichever sign they come with. Every other type keeps the
  sign Trading 212 sends: a deposit and interest in, a transfer either way.
- A day is the timestamp's UTC day.

Logs carry counts only, never transaction details (ADR-0004).
"""

import logging
from collections.abc import Callable
from typing import Any

from pydantic import ValidationError

from hubnisio.finance.models import TransactionStatus
from hubnisio.finance.providers.base import (
    BalanceRecord,
    NormalizedPage,
    Normalizer,
    TransactionRecord,
)
from hubnisio.finance.providers.trading212.schemas import (
    AccountSummary,
    CashMovement,
    Dividend,
    HistoryPage,
    day_of,
)

logger = logging.getLogger(__name__)

TOTAL_VALUE = "TVAL"
CODE_PREFIX = "T212_"
DIVIDEND_CODE = f"{CODE_PREFIX}DIVIDEND"
_MONEY_OUT = frozenset({"WITHDRAW", "FEE"})
_DESCRIPTIONS = {
    "DEPOSIT": "Deposit",
    "WITHDRAW": "Withdrawal",
    "FEE": "Fee",
    "TRANSFER": "Transfer between Trading 212 accounts",
    "INTEREST_ON_FREE_CASH": "Interest on cash",
    "LENDING_INTEREST": "Share lending interest",
}


def normalize_summary(raw: dict[str, Any]) -> list[BalanceRecord]:
    summary = AccountSummary.model_validate(raw)
    return [
        BalanceRecord(
            balance_type=TOTAL_VALUE, amount=summary.total_value, currency=summary.currency
        )
    ]


def normalize_cash(raw: dict[str, Any]) -> NormalizedPage:
    return _page(raw, _cash_record)


def normalize_dividends(raw: dict[str, Any]) -> NormalizedPage:
    return _page(raw, _dividend_record)


normalizer = Normalizer(
    transactions={"transactions": normalize_cash, "dividends": normalize_dividends},
    balances={"summary": normalize_summary},
)


def _page(
    raw: dict[str, Any], record: Callable[[dict[str, Any]], TransactionRecord]
) -> NormalizedPage:
    records: list[TransactionRecord] = []
    skipped = 0
    for item in HistoryPage.model_validate(raw).items:
        try:
            records.append(record(item))
        except ValidationError:
            skipped += 1
    if skipped:
        logger.warning("Skipped %d unparseable Trading 212 history items.", skipped)
    return NormalizedPage(records=records, skipped=skipped)


def _cash_record(item: dict[str, Any]) -> TransactionRecord:
    movement = CashMovement.model_validate(item)
    amount = -abs(movement.amount) if movement.type in _MONEY_OUT else movement.amount
    day = day_of(movement.date_time)
    return TransactionRecord(
        status=TransactionStatus.BOOKED,
        amount=amount,
        currency=movement.currency,
        occurred_on=day,
        entry_reference=_entry_reference("transactions", movement.reference),
        booking_date=day,
        description=_DESCRIPTIONS.get(movement.type, movement.type.replace("_", " ").capitalize()),
        reference=_clean(movement.reference),
        bank_transaction_code={"code": CODE_PREFIX + movement.type},
    )


def _dividend_record(item: dict[str, Any]) -> TransactionRecord:
    dividend = Dividend.model_validate(item)
    instrument = dividend.instrument
    ticker = _clean(dividend.ticker) or (instrument and _clean(instrument.ticker))
    name = (instrument and _clean(instrument.name)) or ticker
    description = "Dividend"
    if name:
        description += f": {name}" + (f" ({ticker})" if ticker and ticker != name else "")
    code: dict[str, Any] = {"code": DIVIDEND_CODE}
    if dividend.type:
        code["sub_code"] = dividend.type
    day = day_of(dividend.paid_on)
    return TransactionRecord(
        status=TransactionStatus.BOOKED,
        amount=dividend.amount,
        currency=dividend.currency,
        occurred_on=day,
        entry_reference=_entry_reference("dividends", dividend.reference),
        booking_date=day,
        description=description,
        reference=_clean(dividend.reference),
        bank_transaction_code=code,
    )


def _entry_reference(endpoint: str, reference: str | None) -> str | None:
    cleaned = _clean(reference)
    return f"{endpoint}:{cleaned}" if cleaned else None


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    return value.strip() or None
