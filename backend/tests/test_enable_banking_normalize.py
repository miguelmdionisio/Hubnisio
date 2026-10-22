import json
from datetime import date
from decimal import Decimal
from pathlib import Path

from hubnisio.finance.models import TransactionStatus
from hubnisio.finance.providers.enable_banking.normalize import (
    normalize_balances,
    normalize_transactions,
)

FIXTURES = Path(__file__).parent / "fixtures" / "enable_banking"


def load(name: str) -> dict[str, object]:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def test_page_maps_bank_fields() -> None:
    page = normalize_transactions(load("transactions_page.json"))

    assert (len(page.records), page.ignored, page.skipped) == (4, 1, 2)
    card, salary, foreign, pending = page.records

    assert card.status is TransactionStatus.BOOKED
    assert card.entry_reference == "20261014-000123"
    assert card.amount == Decimal("-42.17")
    assert card.counterparty_name == "SUPERMERCADO EXEMPLO PORTO"  # the creditor: money out
    assert card.counterparty_iban is None
    assert card.description == "COMPRA 4450 SUPERMERCADO EXEMPLO PORTO"
    assert card.occurred_on == date(2026, 10, 14)  # booking date wins
    assert card.transaction_date == date(2026, 10, 13)
    assert card.mcc == "5411"
    assert card.bank_transaction_code == {
        "description": "Card payment",
        "code": "CCRD",
        "sub_code": "POSD",
    }
    assert card.balance_after == Decimal("1957.83")

    assert salary.amount == Decimal("2100.00")
    assert salary.counterparty_name == "EMPRESA EXEMPLO LDA"  # the debtor: money in
    assert salary.counterparty_iban == "PT50000201231234567890154"  # spaces removed
    assert salary.reference == "RF18539007547034"

    assert foreign.amount == Decimal("-9.21")
    assert (foreign.original_amount, foreign.original_currency) == (Decimal("-10.00"), "USD")

    assert pending.status is TransactionStatus.PENDING
    assert pending.entry_reference is None
    assert pending.booking_date is None
    assert pending.occurred_on == date(2026, 10, 17)  # falls back to the transaction date


def test_grouped_pages_take_their_status_from_the_group() -> None:
    amount = {"currency": "EUR", "amount": "1.00"}
    raw = {
        "transactions": {
            "booked": [{"transaction_amount": amount, "booking_date": "2026-10-01"}],
            "pending": [{"transaction_amount": amount, "transaction_date": "2026-10-02"}],
        }
    }

    statuses = [record.status for record in normalize_transactions(raw).records]

    assert statuses == [TransactionStatus.BOOKED, TransactionStatus.PENDING]


def test_missing_status_follows_the_booking_date() -> None:
    amount = {"currency": "EUR", "amount": "-5.00"}
    raw = {
        "transactions": [
            {"transaction_amount": amount, "booking_date": "2026-10-01"},
            {"transaction_amount": amount, "value_date": "2026-10-02"},
        ]
    }

    records = normalize_transactions(raw).records

    assert [record.status for record in records] == [
        TransactionStatus.BOOKED,
        TransactionStatus.PENDING,
    ]
    # No credit/debit indicator: a negative amount means money out.
    assert records[0].amount == Decimal("-5.00")


def test_hold_is_pending_and_scheduled_is_ignored() -> None:
    amount = {"currency": "EUR", "amount": "1.00"}
    raw = {
        "transactions": [
            {"transaction_amount": amount, "status": "HOLD", "transaction_date": "2026-10-01"},
            {"transaction_amount": amount, "status": "SCHD", "value_date": "2026-11-01"},
            {"transaction_amount": amount, "status": "RJCT", "booking_date": "2026-10-01"},
        ]
    }

    page = normalize_transactions(raw)

    assert [record.status for record in page.records] == [TransactionStatus.PENDING]
    assert page.ignored == 2


def test_balances() -> None:
    raw = {
        "balances": [
            {
                "name": "Saldo",
                "balance_amount": {"currency": "EUR", "amount": "1957.83"},
                "balance_type": "CLBD",
                "reference_date": "2026-10-16",
            },
            {
                "balance_amount": {"currency": "EUR", "amount": "1954.33"},
                "balance_type": "ITAV",
                "last_change_date_time": "2026-10-17T09:30:00Z",
            },
        ]
    }

    clbd, itav = normalize_balances(raw)

    assert (clbd.balance_type, clbd.amount, clbd.reference_date) == (
        "CLBD",
        Decimal("1957.83"),
        date(2026, 10, 16),
    )
    assert itav.last_change_at is not None
    assert itav.last_change_at.isoformat() == "2026-10-17T09:30:00+00:00"
