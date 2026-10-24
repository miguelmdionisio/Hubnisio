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
- The summary's cash and totals, the positions and the orders' fills become an investment
  account's own records (ADR-0008, "Trades, instruments and holdings"), never transactions.
  An order without a fill (cancelled, rejected, still working) is ignored. Quantities and
  amounts keep the sign Trading 212 sends; a fill's side says which way it went.
- Instruments come from the positions and orders, and their types from the instrument list.

Logs carry counts only, never transaction details (ADR-0004).
"""

import logging
from collections.abc import Callable
from typing import Any

from hubnisio.finance.models import TransactionStatus
from hubnisio.finance.providers.base import (
    BalanceRecord,
    FillPage,
    FillRecord,
    HoldingRecord,
    HoldingsPage,
    InstrumentRecord,
    NormalizedPage,
    Normalizer,
    PortfolioRecord,
    TaxRecord,
    TransactionRecord,
)
from hubnisio.finance.providers.trading212.schemas import (
    AccountSummary,
    CashMovement,
    Dividend,
    HistoricalOrder,
    HistoryPage,
    Instrument,
    Investments,
    Items,
    Position,
    TradableInstrument,
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


def normalize_portfolio(raw: dict[str, Any]) -> PortfolioRecord:
    summary = AccountSummary.model_validate(raw)
    investments = summary.investments or Investments()
    return PortfolioRecord(
        currency=summary.currency,
        total_value=summary.total_value,
        cash=summary.cash.available_to_trade,
        cash_in_pies=summary.cash.in_pies,
        cash_reserved=summary.cash.reserved_for_orders,
        investments_value=investments.current_value,
        investments_cost=investments.total_cost,
        realised_result=investments.realized_profit_loss,
        unrealised_result=investments.unrealized_profit_loss,
    )


def normalize_positions(raw: dict[str, Any]) -> HoldingsPage:
    records, skipped = _parse(Items.model_validate(raw).items, _holding_record)
    return HoldingsPage(records=records, skipped=skipped)


def normalize_orders(raw: dict[str, Any]) -> FillPage:
    parsed, skipped = _parse(HistoryPage.model_validate(raw).items, _fill_record)
    records = [record for record in parsed if record is not None]
    return FillPage(records=records, skipped=skipped, ignored=len(parsed) - len(records))


def normalize_instruments(raw: dict[str, Any]) -> list[InstrumentRecord]:
    records, _ = _parse(Items.model_validate(raw).items, _listed_instrument)
    return records


def normalize_cash(raw: dict[str, Any]) -> NormalizedPage:
    return _page(raw, _cash_record)


def normalize_dividends(raw: dict[str, Any]) -> NormalizedPage:
    return _page(raw, _dividend_record)


normalizer = Normalizer(
    transactions={"transactions": normalize_cash, "dividends": normalize_dividends},
    balances={"summary": normalize_summary},
    portfolios={"summary": normalize_portfolio},
    holdings={"positions": normalize_positions},
    fills={"orders": normalize_orders},
    instruments={"instruments": normalize_instruments},
)


def _page(
    raw: dict[str, Any], record: Callable[[dict[str, Any]], TransactionRecord]
) -> NormalizedPage:
    records, skipped = _parse(HistoryPage.model_validate(raw).items, record)
    return NormalizedPage(records=records, skipped=skipped)


def _parse[R](
    items: list[dict[str, Any]], record: Callable[[dict[str, Any]], R]
) -> tuple[list[R], int]:
    """Each item's record, skipping (and counting) those that can't be parsed."""
    records: list[R] = []
    skipped = 0
    for item in items:
        try:
            records.append(record(item))
        except ValueError:  # pydantic's ValidationError is one too
            skipped += 1
    if skipped:
        logger.warning("Skipped %d unparseable Trading 212 items.", skipped)
    return records, skipped


def _holding_record(item: dict[str, Any]) -> HoldingRecord:
    position = Position.model_validate(item)
    wallet = position.wallet_impact
    return HoldingRecord(
        instrument=_instrument(position.instrument),
        quantity=position.quantity,
        quantity_in_pies=position.quantity_in_pies,
        average_price=position.average_price_paid,
        current_price=position.current_price,
        currency=wallet and wallet.currency,
        value=wallet and wallet.current_value,
        cost=wallet and wallet.total_cost,
        unrealised_result=wallet and wallet.unrealized_profit_loss,
        fx_impact=wallet and wallet.fx_impact,
        opened_at=position.created_at,
    )


def _fill_record(item: dict[str, Any]) -> FillRecord | None:
    """None for an order without a fill."""
    historical = HistoricalOrder.model_validate(item)
    order, fill = historical.order, historical.fill
    if fill is None:
        return None
    instrument = _instrument(order.instrument, order.ticker)
    wallet = fill.wallet_impact
    # The side, else (an order from before Trading 212 sent one) the quantity's sign.
    side = _clean(order.side) or ("SELL" if fill.quantity < 0 else "BUY")
    return FillRecord(
        fill_id=fill.id,
        instrument=instrument,
        side=side.upper(),
        fill_type=_clean(fill.type) or "TRADE",
        filled_at=fill.filled_at,
        quantity=fill.quantity,
        price=fill.price,
        order_id=order.id,
        order_type=_clean(order.type),
        initiated_from=_clean(order.initiated_from),
        currency=wallet and wallet.currency,
        fx_rate=wallet and wallet.fx_rate,
        net_value=wallet and wallet.net_value,
        realised_result=wallet and wallet.realised_profit_loss,
        taxes=tuple(
            TaxRecord(tax.name, tax.quantity, tax.currency, tax.charged_at)
            for tax in (wallet.taxes if wallet else [])
        ),
    )


def _instrument(instrument: Instrument | None, ticker: str | None = None) -> InstrumentRecord:
    found = (instrument and _clean(instrument.ticker)) or _clean(ticker)
    if not found:
        raise ValueError("An instrument without a ticker.")
    if instrument is None:
        return InstrumentRecord(found)
    return InstrumentRecord(
        found, _clean(instrument.isin), _clean(instrument.name), _clean(instrument.currency)
    )


def _listed_instrument(item: dict[str, Any]) -> InstrumentRecord:
    listed = TradableInstrument.model_validate(item)
    ticker = _clean(listed.ticker)
    if not ticker:
        raise ValueError("An instrument without a ticker.")
    return InstrumentRecord(
        ticker,
        _clean(listed.isin),
        _clean(listed.name) or _clean(listed.short_name),
        _clean(listed.currency_code),
        _clean(listed.type),
    )


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
