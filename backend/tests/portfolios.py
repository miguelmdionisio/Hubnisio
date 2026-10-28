"""Investment accounts written straight to the database (ADR-0008), for tests that need a
portfolio without a sync: synthetic instruments, fills, a snapshot with its holdings, and cash
movements. Instruments are global, so each gets a ticker no other test uses."""

import itertools
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from decimal import Decimal

from households import Home, add
from sqlalchemy.dialects.postgresql import insert

from hubnisio.core.auth import Principal
from hubnisio.core.db import get_sessionmaker
from hubnisio.finance.models import (
    Account,
    AccountOwner,
    AccountVisibility,
    Fill,
    HoldingSnapshot,
    Instrument,
    InstrumentPrice,
    PortfolioSnapshot,
    PriceSource,
)

_fill_ids = itertools.count(1)


@dataclass(frozen=True)
class Trade:
    instrument: uuid.UUID
    on: date
    quantity: str  # as Trading 212 sends it: negative on a sell
    price: str
    net_value: str  # positive both ways
    side: str = "BUY"
    fill_type: str = "TRADE"
    hour: int = 12  # UTC
    tax: str | None = None  # a currency conversion fee in euros, negative as Trading 212 sends it


async def new_instrument(
    *,
    exchange: str = "_US_EQ",
    currency: str | None = "EUR",
    isin: str | None = None,
    kind: str | None = "STOCK",
    name: str | None = None,
) -> Instrument:
    """`exchange` ends the ticker: `_US_EQ`, or a European exchange's letter and `_EQ`."""
    code = uuid.uuid4().hex[:6].upper()
    instrument = Instrument(
        ticker=f"XT{code}{exchange}",
        isin=isin or f"XS{uuid.uuid4().int % 10**10:010d}",
        name=name or f"Test {code}",
        currency=currency,
        type=kind,
    )
    async with get_sessionmaker()() as session, session.begin():
        session.add(instrument)
    return instrument


async def investment_account(
    home: Home,
    owner: Principal,
    *,
    as_of: datetime,
    cash: str,
    total_value: str,
    holdings: dict[uuid.UUID, tuple[str, str]] | None = None,  # quantity, current price
    trades: list[Trade] | None = None,
    movements: dict[date, str | tuple[str, str]] | None = None,  # an amount, or with a bank code
    visibility: AccountVisibility = AccountVisibility.SHARED,
    include_in_net_worth: bool = True,
    name: str = "Trading 212 EUR",
) -> uuid.UUID:
    household = home.owner.household_id
    async with get_sessionmaker()() as session, session.begin():
        account = Account(
            household_id=household,
            institution_name="Trading 212",
            currency="EUR",
            display_name=name,
            visibility=visibility,
            is_investment=True,
            include_in_net_worth=include_in_net_worth,
        )
        session.add(account)
        await session.flush()
        session.add(AccountOwner(account_id=account.id, user_id=owner.user_id))
        snapshot = PortfolioSnapshot(
            household_id=household,
            account_id=account.id,
            currency="EUR",
            total_value=Decimal(total_value),
            cash=Decimal(cash),
            cash_in_pies=Decimal(0),
            cash_reserved=Decimal(0),
            fetched_at=as_of,
        )
        session.add(snapshot)
        await session.flush()
        session.add_all(
            HoldingSnapshot(
                household_id=household,
                account_id=account.id,
                portfolio_snapshot_id=snapshot.id,
                instrument_id=instrument,
                quantity=Decimal(quantity),
                current_price=Decimal(price),
            )
            for instrument, (quantity, price) in (holdings or {}).items()
        )
        session.add_all(
            Fill(
                household_id=household,
                account_id=account.id,
                instrument_id=trade.instrument,
                fill_id=next(_fill_ids),
                side=trade.side,
                fill_type=trade.fill_type,
                filled_at=datetime.combine(trade.on, time(trade.hour), UTC),
                quantity=Decimal(trade.quantity),
                price=Decimal(trade.price),
                currency="EUR",
                net_value=Decimal(trade.net_value),
                taxes=[
                    {
                        "name": "CURRENCY_CONVERSION_FEE",
                        "amount": trade.tax,
                        "currency": "EUR",
                        "charged_at": None,
                    }
                ]
                if trade.tax
                else [],
                payload_id=home.payload_id,
            )
            for trade in trades or []
        )
    for on, movement in (movements or {}).items():
        amount, code = movement if isinstance(movement, tuple) else (movement, None)
        await add(home, amount, 0, on=on, account=account.id, bank_code=code)
    return account.id


async def set_prices(
    instrument: uuid.UUID, prices: dict[date, str], source: PriceSource = PriceSource.YAHOO
) -> None:
    async with get_sessionmaker()() as session, session.begin():
        await session.execute(
            insert(InstrumentPrice)
            .values(
                [
                    {
                        "instrument_id": instrument,
                        "on": on,
                        "price": Decimal(price),
                        "source": source,
                    }
                    for on, price in prices.items()
                ]
            )
            .on_conflict_do_nothing()
        )
