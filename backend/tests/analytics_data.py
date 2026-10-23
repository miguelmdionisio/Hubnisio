"""The data the AI tests share (tests/test_analytics.py, tests/test_ai.py): a login per member,
and the cases the views and the MCP tools must agree with the app on."""

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from households import Home, add
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert

from hubnisio.core.auth import Principal
from hubnisio.core.db import get_sessionmaker
from hubnisio.core.models import User
from hubnisio.finance.models import (
    Account,
    AccountOwner,
    AccountVisibility,
    BalanceSnapshot,
    Budget,
    BudgetLimit,
    Cadence,
    CategoryAssignment,
    Connection,
    ConnectionStatus,
    Counterparty,
    FxRate,
    FxSource,
    Overspend,
    ProviderAccount,
    ProviderName,
    RecurringSeries,
    RecurringStatus,
    Review,
    Source,
    TransactionAnnotation,
    TransactionKind,
    TransactionStatus,
    Transfer,
)
from hubnisio.finance.scoping import View

SEPTEMBER, OCTOBER = date(2026, 9, 1), date(2026, 10, 1)
VIEWS: tuple[View, ...] = ("personal", "household")


@dataclass(frozen=True)
class Login:
    role: str
    dsn: str


async def email_of(principal: Principal) -> str:
    async with get_sessionmaker()() as session:
        email = await session.scalar(select(User.email).where(User.id == principal.user_id))
    assert email is not None
    return email


@dataclass(frozen=True)
class Data:
    hers: uuid.UUID  # the member's private account
    hidden: uuid.UUID  # the owner's, hidden
    owner_private: set[uuid.UUID]  # transactions on the owner's private account
    member_private: set[uuid.UUID]  # on the member's


async def new_account(
    home: Home,
    name: str,
    owner: Principal,
    visibility: AccountVisibility,
    *,
    hidden: bool = False,
    currency: str = "EUR",
) -> uuid.UUID:
    async with get_sessionmaker()() as session, session.begin():
        account = Account(
            household_id=home.owner.household_id,
            institution_name="Revolut",
            currency=currency,
            display_name=name,
            visibility=visibility,
            hidden_at=datetime(2026, 10, 1, tzinfo=UTC) if hidden else None,
        )
        session.add(account)
        await session.flush()
        session.add(AccountOwner(account_id=account.id, user_id=owner.user_id))
    return account.id


async def save(*items: Any) -> None:
    async with get_sessionmaker()() as session, session.begin():
        session.add_all(items)


async def populate(home: Home) -> Data:
    household = home.owner.household_id
    food, groceries = home.categories["Food"], home.categories["Groceries"]
    rent = home.categories["Rent & mortgage"]
    hers = await new_account(home, "Rui privado", home.member, AccountVisibility.PRIVATE)
    theirs = await new_account(home, "Rui", home.member, AccountVisibility.SHARED)
    hidden = await new_account(home, "Antiga", home.owner, AccountVisibility.SHARED, hidden=True)
    merchant = Counterparty(household_id=household, name="Pingo")
    async with get_sessionmaker()() as session, session.begin():
        await session.execute(
            update(Account)
            .where(Account.id == home.savings)
            .values(is_pot=True, pot_category_id=rent)
        )
        # fx_rates is global: a test-only currency, its rate the same in every test.
        await session.execute(
            insert(FxRate)
            .values(quote_currency="XTQ", on=OCTOBER, rate=Decimal(4), source=FxSource.ECB)
            .on_conflict_do_nothing(index_elements=["quote_currency", "on"])
        )
        session.add(merchant)
    # The bank connections the accounts come through: the owner's BPI one, and the member's.
    async with get_sessionmaker()() as session, session.begin():
        bpi = await session.scalar(
            select(Connection.id).where(Connection.household_id == household)
        )
        revolut = Connection(
            household_id=household,
            user_id=home.member.user_id,
            provider=ProviderName.ENABLE_BANKING,
            institution_name="Revolut",
            institution_country="PT",
            status=ConnectionStatus.ACTIVE,
        )
        session.add(revolut)
        await session.flush()
        session.add_all(
            ProviderAccount(
                connection_id=connection, provider_account_uid=uuid.uuid4().hex, account_id=account
            )
            for connection, account in (
                (bpi, home.shared),
                (bpi, home.savings),
                (bpi, home.private),
                (revolut.id, hers),
                (revolut.id, theirs),
            )
        )

    # The owner's shared account.
    weekly = await add(home, "-50.00", 3, description="PINGO DOCE")
    rent_paid = await add(home, "-1200.00", 1)
    rent_back = await add(home, "600.00", 2)  # a repayment: lowers Rent
    await add(home, "2000.00", 1)
    await add(home, "-30.00", 4)
    overridden = await add(home, "-20.00", 5)  # uncategorized, overridden to income
    overridden_category = await add(home, "-15.00", 6)  # in Groceries, overridden to income
    foreign = await add(home, "-40.00", 7, currency="XTQ")  # 10 euros
    await add(home, "-7.00", 8, currency="XTN")  # no rate
    await add(home, "-5.00", 9, status=TransactionStatus.PENDING)
    lone_transfer = await add(home, "-60.00", 10)  # overridden to a transfer
    september = await add(home, "-80.00", 0, on=date(2026, 9, 15))
    # Into the pot and back; to the owner's private account; the member's into the pot.
    to_pot = await add(home, "-300.00", 12)
    into_pot = await add(home, "300.00", 12, account=home.savings)
    from_pot = await add(home, "-50.00", 20, account=home.savings)
    back = await add(home, "50.00", 20)
    to_private = await add(home, "-100.00", 15)
    on_private = await add(home, "100.00", 15, account=home.private)
    their_out = await add(home, "-200.00", 5, account=theirs)
    their_in = await add(home, "200.00", 5, account=home.savings)
    # The pot's own spending, the private accounts, the member's shared one, a hidden one.
    pot_spends = await add(home, "-120.00", 14, account=home.savings)
    private_groceries = await add(home, "-75.00", 16, account=home.private)
    private_big = await add(home, "-999.00", 17, account=home.private)
    hers_one = await add(home, "-44.00", 18, account=hers)
    hers_two = await add(home, "-6.00", 19, account=hers)
    their_groceries = await add(home, "-25.00", 6, account=theirs)
    await add(home, "-10.00", 0, on=date(2026, 9, 3), account=hidden)

    def categorized(
        transaction: uuid.UUID, category: uuid.UUID, source: Source = Source.MANUAL
    ) -> CategoryAssignment:
        return CategoryAssignment(
            household_id=household, transaction_id=transaction, category_id=category, source=source
        )

    def annotated(transaction: uuid.UUID, **fields: Any) -> TransactionAnnotation:
        return TransactionAnnotation(household_id=household, transaction_id=transaction, **fields)

    def override(transaction: uuid.UUID, kind: TransactionKind) -> TransactionAnnotation:
        return annotated(transaction, kind_override=kind, kind_source=Source.MANUAL)

    def paired(outgoing: uuid.UUID, incoming: uuid.UUID) -> Transfer:
        return Transfer(
            household_id=household, outgoing_id=outgoing, incoming_id=incoming, source=Source.AUTO
        )

    await save(
        categorized(weekly, groceries),
        categorized(rent_paid, rent, Source.RULE),
        categorized(rent_back, rent),
        categorized(overridden_category, groceries),
        categorized(foreign, groceries),
        categorized(september, groceries),
        categorized(pot_spends, groceries),
        categorized(private_groceries, groceries),
        categorized(their_groceries, groceries),
        categorized(to_pot, groceries),  # ignored in Mine: the pot's category wins
        annotated(weekly, counterparty_id=merchant.id, tags=["food"], note="weekly shop"),
        override(overridden, TransactionKind.INCOME),
        override(overridden_category, TransactionKind.INCOME),
        override(lone_transfer, TransactionKind.TRANSFER),
        annotated(private_groceries, counterparty_id=merchant.id),
        annotated(hers_one, counterparty_id=merchant.id),
        annotated(hers_two, counterparty_id=merchant.id),
        paired(to_pot, into_pot),
        paired(from_pot, back),
        paired(to_private, on_private),
        paired(their_out, their_in),
    )
    await save(
        *(
            BalanceSnapshot(
                household_id=household,
                account_id=account,
                balance_type=balance_type,
                amount=Decimal(amount),
                currency="EUR",
                reference_date=date(2026, 10, day),
                fetched_at=datetime(2026, 10, day, 12, tzinfo=UTC),
            )
            for account, balance_type, amount, day in (
                (home.shared, "ITAV", "500.00", 20),
                (home.shared, "CLBD", "520.00", 20),
                (home.shared, "ITAV", "600.00", 21),
                (home.shared, "CLBD", "610.00", 21),
                (home.shared, "XXXX", "1.00", 21),
                (home.private, "CLBD", "100.00", 21),
                (home.savings, "ITAV", "180.00", 21),
                (hers, "ITAV", "44.00", 21),
                (hidden, "CLBD", "10.00", 21),
            )
        ),
        *(
            RecurringSeries(
                household_id=household,
                account_id=account,
                match_key=name.lower(),
                name=name,
                cadence=Cadence.MONTHLY,
                kind=TransactionKind.EXPENSE,
                expected_amount=Decimal("-9.99"),
                currency="EUR",
                occurrences=3,
                first_seen_on=date(2026, 8, 1),
                last_seen_on=date(2026, 10, 1),
                next_expected_on=date(2026, 11, 1),
                status=RecurringStatus.ACTIVE,
                review=review,
            )
            for account, name, review in (
                (home.shared, "Netflix", Review.CONFIRMED),
                (home.private, "Gym", Review.SUGGESTED),
                (hers, "Spotify", Review.CONFIRMED),
                (home.shared, "Jornal", Review.DISMISSED),
            )
        ),
    )
    # The overall budget, a group's and a sub-limit inside it, changed from October on.
    overall = Budget(household_id=household, category_id=None, rollover=True)
    group = Budget(household_id=household, category_id=food, overspend=Overspend.CARRY)
    sub = Budget(household_id=household, category_id=groceries, rollover=True)
    await save(overall, group, sub)
    await save(
        BudgetLimit(budget_id=overall.id, starts_on=SEPTEMBER, amount=Decimal(1000)),
        BudgetLimit(budget_id=group.id, starts_on=SEPTEMBER, amount=Decimal(200)),
        BudgetLimit(budget_id=group.id, starts_on=OCTOBER, amount=Decimal(150)),
        BudgetLimit(budget_id=sub.id, starts_on=SEPTEMBER, amount=Decimal(100)),
    )
    return Data(
        hers=hers,
        hidden=hidden,
        owner_private={on_private, private_groceries, private_big},
        member_private={hers_one, hers_two},
    )
