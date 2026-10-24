"""Trading 212 payloads → records, from synthetic payloads."""

from datetime import date
from decimal import Decimal
from typing import Any

import pytest

from hubnisio.finance.models import TransactionStatus
from hubnisio.finance.providers.trading212.normalize import (
    normalize_cash,
    normalize_dividends,
    normalize_summary,
    normalizer,
)


def movement(kind: str, amount: float, reference: str = "ref-1", **extra: Any) -> dict[str, Any]:
    return {
        "type": kind,
        "amount": amount,
        "currency": "EUR",
        "dateTime": "2026-10-20T23:30:00.000+00:00",
        "reference": reference,
        **extra,
    }


def test_the_summary_is_the_total_value() -> None:
    raw = {
        "id": 4242,
        "currency": "EUR",
        "totalValue": 1234.56,
        "cash": {"availableToTrade": 34.56, "inPies": 0, "reservedForOrders": 0},
    }
    (balance,) = normalize_summary(raw)
    assert (balance.balance_type, balance.amount, balance.currency) == (
        "TVAL",
        Decimal("1234.56"),
        "EUR",
    )


@pytest.mark.parametrize(
    ("kind", "sent", "stored"),
    [
        ("DEPOSIT", 500, "500"),
        ("WITHDRAW", 3000, "-3000"),  # either sign convention is money out
        ("WITHDRAW", -3000, "-3000"),
        ("FEE", 0.5, "-0.5"),
        ("FEE", -0.5, "-0.5"),
        ("INTEREST_ON_FREE_CASH", 1.23, "1.23"),
        ("LENDING_INTEREST", 0.04, "0.04"),
        ("TRANSFER", -100, "-100"),  # a transfer keeps its sign
        ("TRANSFER", 100, "100"),
    ],
)
def test_cash_movements_are_signed(kind: str, sent: float, stored: str) -> None:
    (record,) = normalize_cash({"items": [movement(kind, sent)], "nextPagePath": None}).records
    assert record.amount == Decimal(stored)
    assert record.bank_transaction_code == {"code": f"T212_{kind}"}


def test_a_cash_movement_becomes_a_booked_transaction() -> None:
    (record,) = normalize_cash({"items": [movement("DEPOSIT", 500, " abc-1 ")]}).records
    assert record.status is TransactionStatus.BOOKED
    assert record.entry_reference == "transactions:abc-1"
    assert record.reference == "abc-1"
    assert record.occurred_on == record.booking_date == date(2026, 10, 20)
    assert (record.currency, record.description) == ("EUR", "Deposit")
    assert record.counterparty_name is None


def test_a_timestamp_counts_on_its_utc_day() -> None:
    item = movement("DEPOSIT", 5, dateTime="2026-10-21T00:30:00+02:00")
    (record,) = normalize_cash({"items": [item]}).records
    assert record.occurred_on == date(2026, 10, 20)


def test_an_unknown_type_is_kept_with_its_sign() -> None:
    (record,) = normalize_cash({"items": [movement("CASHBACK", 2)]}).records
    assert (record.amount, record.description) == (Decimal(2), "Cashback")


def test_unparseable_items_are_skipped_not_fatal() -> None:
    page = normalize_cash({"items": [movement("DEPOSIT", 5), {"type": "DEPOSIT"}]})
    assert (len(page.records), page.skipped) == (1, 1)


def test_a_dividend_becomes_income_in_the_account_currency() -> None:
    item = {
        "amount": 3.21,
        "amountInEuro": 3.21,
        "currency": "EUR",
        "grossAmountPerShare": 0.45,
        "instrument": {"ticker": "VWRL_EQ", "name": "Vanguard FTSE All-World", "currency": "USD"},
        "paidOn": "2026-10-01T09:00:00Z",
        "quantity": 8.5,
        "reference": 987654,
        "ticker": "VWRL_EQ",
        "tickerCurrency": "USD",
        "type": "ORDINARY",
    }
    (record,) = normalize_dividends({"items": [item]}).records
    assert (record.amount, record.currency) == (Decimal("3.21"), "EUR")
    assert record.entry_reference == "dividends:987654"
    assert record.description == "Dividend: Vanguard FTSE All-World (VWRL_EQ)"
    assert record.bank_transaction_code == {"code": "T212_DIVIDEND", "sub_code": "ORDINARY"}
    assert record.occurred_on == date(2026, 10, 1)


def test_the_normalizer_reads_three_kinds_of_payload() -> None:
    assert set(normalizer.balances) == {"summary"}
    assert set(normalizer.transactions) == {"transactions", "dividends"}
