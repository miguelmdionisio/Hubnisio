import uuid
from collections.abc import Awaitable, Callable
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import Date, delete, func, literal, select
from sqlalchemy.exc import IntegrityError

from hubnisio.core.db import get_sessionmaker
from hubnisio.core.models import Household, User
from hubnisio.finance.fx.convert import MAX_RATE_AGE_DAYS, eur_amount, to_eur
from hubnisio.finance.models import (
    Account,
    Connection,
    ConnectionStatus,
    FxRate,
    FxSource,
    Money,
    ProviderName,
    ProviderPayload,
    Transaction,
    TransactionStatus,
)

pytestmark = pytest.mark.anyio

# Dollar rates are easy to divide by: 2 from the 1st, 4 from the 5th, 5 from the 20th.
RATES = {date(2026, 10, 1): "2", date(2026, 10, 5): "4", date(2026, 10, 20): "5"}


@pytest.fixture
async def rates(migrated_database: str) -> None:
    async with get_sessionmaker()() as session, session.begin():
        await session.execute(delete(FxRate))  # global, shared by every test
        session.add_all(
            FxRate(quote_currency="USD", on=day, rate=Decimal(rate), source=FxSource.ECB)
            for day, rate in RATES.items()
        )


Convert = Callable[[str, str, date], Awaitable[Decimal | None]]


async def convert_in_python(amount: str, currency: str, on: date) -> Decimal | None:
    async with get_sessionmaker()() as session:
        return await to_eur(session, Decimal(amount), currency, on)


async def convert_in_sql(amount: str, currency: str, on: date) -> Decimal | None:
    async with get_sessionmaker()() as session:
        return await session.scalar(
            select(
                eur_amount(literal(Decimal(amount), Money), literal(currency), literal(on, Date))
            )
        )


@pytest.fixture(params=["python", "sql"])
def convert(request: pytest.FixtureRequest) -> Convert:
    """The single-value helper and the SQL expression must agree on every rule."""
    return convert_in_python if request.param == "python" else convert_in_sql


async def test_an_amount_is_converted_at_the_latest_rate_on_or_before_its_day(
    rates: None, convert: Convert
) -> None:
    assert await convert("8", "USD", date(2026, 10, 1)) == Decimal("4")  # the rate's own day
    assert await convert("8", "USD", date(2026, 10, 4)) == Decimal("4")  # still 2
    assert await convert("8", "USD", date(2026, 10, 5)) == Decimal("2")  # a new rate
    assert await convert("8", "USD", date(2026, 10, 14)) == Decimal("2")  # 4, nine days old
    assert await convert("-8", "USD", date(2026, 10, 25)) == Decimal("-1.6")  # 5: the newest


async def test_euros_pass_through_whatever_the_rates(rates: None, convert: Convert) -> None:
    assert await convert("12.34", "EUR", date(2026, 10, 7)) == Decimal("12.34")
    assert await convert("12.34", "EUR", date(1999, 1, 1)) == Decimal("12.34")


async def test_without_a_recent_rate_there_is_no_amount_not_a_one_to_one_guess(
    rates: None, convert: Convert
) -> None:
    assert MAX_RATE_AGE_DAYS == 10
    # The 5th's rate is usable until the 15th, and gone on the 16th, until the 20th has one.
    assert await convert("8", "USD", date(2026, 10, 15)) == Decimal("2")
    assert await convert("8", "USD", date(2026, 10, 16)) is None
    assert await convert("8", "USD", date(2026, 10, 19)) is None
    assert await convert("8", "USD", date(2026, 10, 20)) == Decimal("1.6")
    # Before the first rate, and for a currency with none at all.
    assert await convert("8", "USD", date(2026, 9, 30)) is None
    assert await convert("8", "MAD", date(2026, 10, 7)) is None


async def test_to_eur_rounds_to_the_money_scale(rates: None) -> None:
    assert await convert_in_python("1", "USD", date(2026, 10, 5)) == Decimal("0.2500")
    async with get_sessionmaker()() as session, session.begin():
        session.add(
            FxRate(
                quote_currency="MAD",
                on=date(2026, 10, 5),
                rate=Decimal("11.01207566"),
                source=FxSource.CURRENCY_API,
            )
        )

    converted = await convert_in_python("100", "MAD", date(2026, 10, 5))

    assert converted == Decimal("9.0809")
    assert converted is not None
    assert converted.as_tuple().exponent == -4


async def test_a_zero_rate_cannot_be_stored(rates: None) -> None:
    with pytest.raises(IntegrityError, match="ck_fx_rates_rate_positive"):
        async with get_sessionmaker()() as session, session.begin():
            session.add(
                FxRate(
                    quote_currency="XXX", on=date(2026, 10, 5), rate=Decimal(0), source=FxSource.ECB
                )
            )


async def test_the_expression_converts_a_sum_of_transactions(rates: None) -> None:
    """The expression takes the columns of a real query, and a missing rate leaves a row out
    of the sum (NULL), which callers count separately."""
    async with get_sessionmaker()() as session, session.begin():
        user = User(email=f"fx-{uuid.uuid4().hex[:8]}@example.com", display_name="Ana")
        household = Household(name="Casa")
        session.add_all([user, household])
        await session.flush()
        connection = Connection(
            household_id=household.id,
            user_id=user.id,
            provider=ProviderName.ENABLE_BANKING,
            institution_name="Revolut",
            institution_country="LT",
            status=ConnectionStatus.ACTIVE,
        )
        account = Account(household_id=household.id, institution_name="Revolut", currency="EUR")
        session.add_all([connection, account])
        await session.flush()
        payload = ProviderPayload(
            household_id=household.id,
            connection_id=connection.id,
            kind="transactions",
            request={},
            response={},
        )
        session.add(payload)
        await session.flush()
        for amount, currency, day in (
            ("-10", "EUR", date(2026, 10, 6)),
            ("-20", "USD", date(2026, 10, 7)),  # 4 -> -5 euros
            ("-30", "USD", date(2026, 10, 25)),  # 5 -> -6 euros
            ("-40", "MAD", date(2026, 10, 7)),  # no rate
        ):
            session.add(
                Transaction(
                    household_id=household.id,
                    account_id=account.id,
                    status=TransactionStatus.BOOKED,
                    entry_reference=uuid.uuid4().hex,
                    fingerprint=uuid.uuid4().hex,
                    occurrence_index=0,
                    amount=Decimal(amount),
                    currency=currency,
                    occurred_on=day,
                    payload_id=payload.id,
                )
            )
        await session.flush()

        in_euros = eur_amount(Transaction.amount, Transaction.currency, Transaction.occurred_on)
        total, unconverted = (
            await session.execute(
                select(
                    func.sum(in_euros),
                    func.count().filter(in_euros.is_(None)),
                ).where(Transaction.account_id == account.id)
            )
        ).one()

    assert (total, unconverted) == (Decimal("-21"), 1)
