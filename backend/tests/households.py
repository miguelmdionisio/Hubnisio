"""A test household for the finance API tests (the `home` fixture is in conftest.py): two
members, the seeded categories, and three accounts, one of them private to the owner."""

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

import httpx
from sqlalchemy import select

from hubnisio.core.auth import Principal, get_principal
from hubnisio.core.db import get_sessionmaker
from hubnisio.core.models import Household, HouseholdMember, HouseholdRole, User
from hubnisio.finance.categorize.run import run_all
from hubnisio.finance.defaults import seed_household
from hubnisio.finance.models import (
    Account,
    AccountOwner,
    AccountVisibility,
    Category,
    Connection,
    ConnectionStatus,
    ProviderName,
    ProviderPayload,
    Transaction,
    TransactionStatus,
)
from hubnisio.main import app


@dataclass(frozen=True)
class Home:
    owner: Principal
    member: Principal
    shared: uuid.UUID  # account IDs
    savings: uuid.UUID  # shared too
    private: uuid.UUID  # the owner's only
    payload_id: uuid.UUID
    categories: dict[str, uuid.UUID]


async def make_home() -> Home:
    async with get_sessionmaker()() as session, session.begin():
        owner = User(email=f"o-{uuid.uuid4().hex[:8]}@example.com", display_name="Ana")
        member = User(email=f"m-{uuid.uuid4().hex[:8]}@example.com", display_name="Rui")
        household = Household(name="Casa")
        session.add_all([owner, member, household])
        await session.flush()
        session.add_all(
            [
                HouseholdMember(
                    household_id=household.id, user_id=owner.id, role=HouseholdRole.OWNER
                ),
                HouseholdMember(
                    household_id=household.id, user_id=member.id, role=HouseholdRole.MEMBER
                ),
            ]
        )
        await seed_household(session, household.id)
        connection = Connection(
            household_id=household.id,
            user_id=owner.id,
            provider=ProviderName.ENABLE_BANKING,
            institution_name="BPI",
            institution_country="PT",
            status=ConnectionStatus.ACTIVE,
        )
        accounts = [
            Account(
                household_id=household.id,
                institution_name="BPI",
                currency="EUR",
                display_name=name,
                visibility=visibility,
            )
            for name, visibility in (
                ("Conta", AccountVisibility.SHARED),
                ("Poupança", AccountVisibility.SHARED),
                ("Pessoal", AccountVisibility.PRIVATE),
            )
        ]
        session.add_all([connection, *accounts])
        await session.flush()
        session.add_all(
            AccountOwner(account_id=account.id, user_id=owner.id) for account in accounts
        )
        payload = ProviderPayload(
            household_id=household.id,
            connection_id=connection.id,
            kind="transactions",
            request={},
            response={},
        )
        session.add(payload)
        await session.flush()
        categories = {
            name: id_
            for name, id_ in await session.execute(
                select(Category.name, Category.id).where(Category.household_id == household.id)
            )
        }
        result = Home(
            owner=Principal(owner.id, household.id, HouseholdRole.OWNER),
            member=Principal(member.id, household.id, HouseholdRole.MEMBER),
            shared=accounts[0].id,
            savings=accounts[1].id,
            private=accounts[2].id,
            payload_id=payload.id,
            categories=categories,
        )
    return result


async def add(
    home: Home,
    amount: str,
    day: int,
    *,
    on: date | None = None,
    account: uuid.UUID | None = None,
    description: str | None = None,
    counterparty: str | None = None,
    currency: str = "EUR",
    status: TransactionStatus = TransactionStatus.BOOKED,
    bank_code: str | None = None,
) -> uuid.UUID:
    """A transaction on `day` of October 2026, or on `on`."""
    occurred_on = on or date(2026, 10, day)
    async with get_sessionmaker()() as session, session.begin():
        transaction = Transaction(
            household_id=home.owner.household_id,
            account_id=account or home.shared,
            status=status,
            entry_reference=uuid.uuid4().hex if status == TransactionStatus.BOOKED else None,
            fingerprint=uuid.uuid4().hex,
            occurrence_index=0,
            amount=Decimal(amount),
            currency=currency,
            occurred_on=occurred_on,
            booking_date=occurred_on,
            description=description,
            counterparty_name=counterparty,
            bank_transaction_code={"code": bank_code} if bank_code else None,
            payload_id=home.payload_id,
        )
        session.add(transaction)
    return transaction.id


async def refresh(home: Home) -> None:
    async with get_sessionmaker()() as session, session.begin():
        await run_all(session, home.owner.household_id)


@asynccontextmanager
async def api(principal: Principal) -> AsyncIterator[httpx.AsyncClient]:
    app.dependency_overrides[get_principal] = lambda: principal
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            yield client
    finally:
        app.dependency_overrides.pop(get_principal, None)
