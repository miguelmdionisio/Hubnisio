"""Enable Banking payloads → records. Pure functions: re-running them on stored payloads gives
the same result, which is what lets `cli renormalize` rebuild transactions after a parser fix.

Logs carry counts only, never transaction details (ADR-0004).
"""

import logging
from typing import Any

from pydantic import ValidationError

from hubnisio.finance.models import TransactionStatus
from hubnisio.finance.providers.base import (
    BalanceRecord,
    NormalizedPage,
    Normalizer,
    TransactionRecord,
)
from hubnisio.finance.providers.enable_banking.schemas import (
    AccountIdentification,
    BalanceList,
    BankTransaction,
    Party,
)

logger = logging.getLogger(__name__)

_STATUSES = {
    "BOOK": TransactionStatus.BOOKED,
    "PDNG": TransactionStatus.PENDING,
    "HOLD": TransactionStatus.PENDING,  # card authorizations holding funds
}
# SCHD (scheduled), CNCL (cancelled), RJCT (rejected) and OTHR are not stored.
# Some banks have sent pages grouped by status instead of a flat list.
_GROUP_STATUSES = {"booked": "BOOK", "pending": "PDNG"}


def normalize_transactions(raw: dict[str, Any]) -> NormalizedPage:
    records: list[TransactionRecord] = []
    skipped = ignored = 0
    for item in _items(raw.get("transactions")):
        try:
            transaction = BankTransaction.model_validate(item)
        except ValidationError:
            skipped += 1
            continue
        status = _status(transaction)
        if status is None:
            ignored += 1
            continue
        record = _record(transaction, status, item)
        if record is None:
            skipped += 1
            continue
        records.append(record)
    if skipped:
        logger.warning("Skipped %d unparseable Enable Banking transactions.", skipped)
    return NormalizedPage(records=records, skipped=skipped, ignored=ignored)


def normalize_balances(raw: dict[str, Any]) -> list[BalanceRecord]:
    return [
        BalanceRecord(
            balance_type=balance.balance_type,
            amount=balance.balance_amount.amount,
            currency=balance.balance_amount.currency,
            reference_date=balance.reference_date,
            last_change_at=balance.last_change_date_time,
        )
        for balance in BalanceList.model_validate(raw).balances
    ]


normalizer = Normalizer(
    transactions={"transactions": normalize_transactions},
    balances={"balances": normalize_balances},
)


def _items(transactions: object) -> list[dict[str, Any]]:
    if isinstance(transactions, list):
        return [item for item in transactions if isinstance(item, dict)]
    if isinstance(transactions, dict):
        items: list[dict[str, Any]] = []
        for group, group_items in transactions.items():
            implied = _GROUP_STATUSES.get(group)
            if implied is None or not isinstance(group_items, list):
                continue
            items.extend(
                {"status": implied, **item} for item in group_items if isinstance(item, dict)
            )
        return items
    return []


def _status(transaction: BankTransaction) -> TransactionStatus | None:
    if transaction.status is None:
        # No status at all: trust the booking date.
        return TransactionStatus.BOOKED if transaction.booking_date else TransactionStatus.PENDING
    return _STATUSES.get(transaction.status)


def _record(
    transaction: BankTransaction, status: TransactionStatus, item: dict[str, Any]
) -> TransactionRecord | None:
    occurred_on = transaction.booking_date or transaction.transaction_date or transaction.value_date
    if occurred_on is None:
        return None

    amount = abs(transaction.transaction_amount.amount)
    money_out = transaction.credit_debit_indicator == "DBIT" or (
        transaction.credit_debit_indicator is None and transaction.transaction_amount.amount < 0
    )
    sign = -1 if money_out else 1
    # Money out goes to the creditor; money in comes from the debtor.
    party, party_account = (
        (transaction.creditor, transaction.creditor_account)
        if money_out
        else (transaction.debtor, transaction.debtor_account)
    )

    original_amount = original_currency = None
    instructed = transaction.exchange_rate and transaction.exchange_rate.instructed_amount
    if instructed and instructed.currency != transaction.transaction_amount.currency:
        original_amount = sign * abs(instructed.amount)
        original_currency = instructed.currency

    return TransactionRecord(
        status=status,
        amount=sign * amount,
        currency=transaction.transaction_amount.currency,
        occurred_on=occurred_on,
        entry_reference=_clean(transaction.entry_reference),
        original_amount=original_amount,
        original_currency=original_currency,
        booking_date=transaction.booking_date,
        value_date=transaction.value_date,
        transaction_date=transaction.transaction_date,
        counterparty_name=_party_name(party),
        counterparty_iban=_iban(party_account),
        description=_description(transaction, item),
        reference=_clean(transaction.reference_number),
        mcc=_clean(transaction.merchant_category_code),
        bank_transaction_code=transaction.bank_transaction_code or None,
        balance_after=(
            transaction.balance_after_transaction.amount
            if transaction.balance_after_transaction
            else None
        ),
    )


def _description(transaction: BankTransaction, item: dict[str, Any]) -> str | None:
    parts = [part.strip() for part in transaction.remittance_information or [] if part.strip()]
    if parts:
        return " ".join(parts)
    additional = item.get("additional_information")
    return _clean(additional) if isinstance(additional, str) else None


def _party_name(party: Party | None) -> str | None:
    return _clean(party.name) if party else None


def _iban(account: AccountIdentification | None) -> str | None:
    if account is None or not account.iban:
        return None
    return account.iban.replace(" ", "").upper()


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    return value.strip() or None
