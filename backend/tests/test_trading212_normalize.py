"""Trading 212 payloads → records, from synthetic payloads."""

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

import pytest

from hubnisio.finance.models import TransactionStatus
from hubnisio.finance.providers.base import InstrumentRecord, TaxRecord
from hubnisio.finance.providers.trading212.normalize import (
    normalize_cash,
    normalize_dividends,
    normalize_instruments,
    normalize_orders,
    normalize_portfolio,
    normalize_positions,
    normalize_summary,
    normalizer,
)

SUMMARY = {
    "id": 4242,
    "currency": "EUR",
    "totalValue": 1234.56,
    "cash": {"availableToTrade": 30.06, "inPies": 4.5, "reservedForOrders": 0},
    "investments": {
        "currentValue": 1200,
        "totalCost": 1100,
        "realizedProfitLoss": 12.5,
        "unrealizedProfitLoss": 100,
    },
}
VWRL = {"ticker": "VWRL_EQ", "isin": "IE00B3RBWM25", "name": "Vanguard FTSE All-World"}


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


def test_the_normalizer_reads_every_kind_of_payload() -> None:
    assert set(normalizer.balances) == set(normalizer.portfolios) == {"summary"}
    assert set(normalizer.transactions) == {"transactions", "dividends"}
    assert set(normalizer.holdings) == {"positions"}
    assert set(normalizer.fills) == {"orders"}
    assert set(normalizer.instruments) == {"instruments"}


def test_the_summary_gives_the_cash_and_totals() -> None:
    record = normalize_portfolio(SUMMARY)
    assert (record.currency, record.total_value) == ("EUR", Decimal("1234.56"))
    assert (record.cash, record.cash_in_pies, record.cash_reserved) == (
        Decimal("30.06"),
        Decimal("4.5"),
        Decimal(0),
    )
    assert (record.investments_value, record.investments_cost) == (Decimal(1200), Decimal(1100))
    assert (record.realised_result, record.unrealised_result) == (Decimal("12.5"), Decimal(100))


def test_a_position_becomes_a_holding() -> None:
    item = {
        "instrument": {**VWRL, "currency": "USD"},
        "quantity": 3.5,
        "quantityInPies": 3.5,
        "averagePricePaid": 100.2,
        "currentPrice": 120.7,
        "createdAt": "2025-03-01T09:00:00Z",
        "walletImpact": {
            "currency": "EUR",
            "currentValue": 390.1,
            "totalCost": 330,
            "unrealizedProfitLoss": 60.1,
            "fxImpact": -2.3,
        },
    }
    (record,) = normalize_positions({"items": [item, {"quantity": 1}]}).records
    assert record.instrument == InstrumentRecord(
        "VWRL_EQ", "IE00B3RBWM25", "Vanguard FTSE All-World", "USD"
    )
    assert (record.quantity, record.quantity_in_pies) == (Decimal("3.5"), Decimal("3.5"))
    assert (record.average_price, record.current_price) == (Decimal("100.2"), Decimal("120.7"))
    assert (record.currency, record.value, record.cost) == ("EUR", Decimal("390.1"), Decimal(330))
    assert (record.unrealised_result, record.fx_impact) == (Decimal("60.1"), Decimal("-2.3"))
    assert record.opened_at == datetime(2025, 3, 1, 9, tzinfo=UTC)
    assert normalize_positions({"items": [{"quantity": 1}]}).skipped == 1  # no instrument


def order(fill: dict[str, Any] | None, **fields: Any) -> dict[str, Any]:
    return {
        "order": {
            "id": 77,
            "createdAt": "2026-10-01T08:00:00Z",
            "status": "FILLED" if fill else "CANCELLED",
            "side": "BUY",
            "type": "MARKET",
            "initiatedFrom": "AUTOINVEST",
            "ticker": "VWRL_EQ",
            "instrument": VWRL,
            **fields,
        },
        "fill": fill,
    }


FILL = {
    "id": 9001,
    "filledAt": "2026-10-01T08:00:05Z",
    "quantity": 0.25,
    "price": 120.5,
    "type": "TRADE",
    "tradingMethod": "TOTV",
    "walletImpact": {
        "currency": "EUR",
        "fxRate": 1.09,
        "netValue": 27.7,
        "realisedProfitLoss": 0,
        "taxes": [
            {
                "name": "CURRENCY_CONVERSION_FEE",
                "quantity": 0.04,
                "currency": "EUR",
                "chargedAt": "2026-10-01T08:00:05Z",
            }
        ],
    },
}


def test_an_order_with_a_fill_becomes_a_fill() -> None:
    page = normalize_orders({"items": [order(FILL)], "nextPagePath": None})
    (record,) = page.records
    assert (record.fill_id, record.order_id) == (9001, 77)
    assert record.instrument.ticker == "VWRL_EQ"
    assert (record.side, record.fill_type) == ("BUY", "TRADE")
    assert (record.order_type, record.initiated_from) == ("MARKET", "AUTOINVEST")
    assert record.filled_at == datetime(2026, 10, 1, 8, 0, 5, tzinfo=UTC)
    assert (record.quantity, record.price) == (Decimal("0.25"), Decimal("120.5"))
    assert (record.currency, record.fx_rate, record.net_value) == (
        "EUR",
        Decimal("1.09"),
        Decimal("27.7"),
    )
    assert record.realised_result == Decimal(0)
    assert record.taxes == (
        TaxRecord(
            "CURRENCY_CONVERSION_FEE",
            Decimal("0.04"),
            "EUR",
            datetime(2026, 10, 1, 8, 0, 5, tzinfo=UTC),
        ),
    )


def test_orders_without_a_fill_are_ignored_and_odd_ones_skipped() -> None:
    page = normalize_orders(
        {"items": [order(None), order(FILL), {"order": {"id": 3}, "fill": {"id": 1}}]}
    )
    assert (len(page.records), page.ignored, page.skipped) == (1, 1, 1)


def test_a_corporate_action_keeps_its_type_and_an_old_order_takes_its_side_from_the_sign() -> None:
    split = {**FILL, "type": "STOCK_SPLIT", "quantity": -2, "walletImpact": None}
    (record,) = normalize_orders({"items": [order(split, side=None, instrument=None)]}).records
    assert (record.fill_type, record.side, record.quantity) == ("STOCK_SPLIT", "SELL", Decimal(-2))
    assert record.instrument == InstrumentRecord("VWRL_EQ")  # from the order's ticker
    assert (record.net_value, record.taxes) == (None, ())


def test_the_instrument_list_gives_types() -> None:
    items = [
        {
            "ticker": "VWRL_EQ",
            "isin": "IE00B3RBWM25",
            "name": "Vanguard FTSE All-World",
            "currencyCode": "GBX",
            "type": "ETF",
            "shortName": "VWRL",
        },
        {"ticker": "AAPL_US_EQ", "shortName": "AAPL", "currencyCode": "USD", "type": "STOCK"},
        {"name": "no ticker"},
    ]
    assert normalize_instruments({"items": items}) == [
        InstrumentRecord("VWRL_EQ", "IE00B3RBWM25", "Vanguard FTSE All-World", "GBX", "ETF"),
        InstrumentRecord("AAPL_US_EQ", None, "AAPL", "USD", "STOCK"),
    ]
