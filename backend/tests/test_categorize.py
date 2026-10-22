"""The categorization engine and transfer matching against a real database (ADR-0007)."""

import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import select

from hubnisio.core.db import get_sessionmaker
from hubnisio.core.models import Household, User
from hubnisio.finance.categorize.engine import CategorizeResult, categorize
from hubnisio.finance.categorize.run import run_all
from hubnisio.finance.categorize.transfers import detect_transfers
from hubnisio.finance.defaults import seed_household
from hubnisio.finance.models import (
    Account,
    Category,
    CategoryAssignment,
    Connection,
    ConnectionStatus,
    Counterparty,
    ProviderName,
    ProviderPayload,
    Rule,
    RuleMatch,
    Source,
    Transaction,
    TransactionAnnotation,
    TransactionKind,
    TransactionStatus,
    Transfer,
    TransferDismissal,
)

pytestmark = pytest.mark.anyio


@dataclass(frozen=True)
class Home:
    household_id: uuid.UUID
    bpi: uuid.UUID  # account IDs
    revolut: uuid.UUID
    payload_id: uuid.UUID
    categories: dict[str, uuid.UUID]  # name -> id


@pytest.fixture
async def home(migrated_database: str) -> Home:
    async with get_sessionmaker()() as session, session.begin():
        user = User(email=f"{uuid.uuid4().hex}@example.com", display_name="Test")
        household = Household(name="Casa")
        session.add_all([user, household])
        await session.flush()
        await seed_household(session, household.id)
        connection = Connection(
            household_id=household.id,
            user_id=user.id,
            provider=ProviderName.ENABLE_BANKING,
            institution_name="BPI",
            institution_country="PT",
            status=ConnectionStatus.ACTIVE,
        )
        accounts = [
            Account(household_id=household.id, institution_name=name, currency="EUR")
            for name in ("BPI", "Revolut")
        ]
        session.add_all([connection, *accounts])
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
        categories = {
            name: id_
            for name, id_ in await session.execute(
                select(Category.name, Category.id).where(Category.household_id == household.id)
            )
        }
        result = Home(household.id, accounts[0].id, accounts[1].id, payload.id, categories)
    return result


async def add(
    home: Home,
    amount: str,
    day: int,
    *,
    account: uuid.UUID | None = None,
    description: str | None = None,
    counterparty: str | None = None,
    code: str | None = None,
    currency: str = "EUR",
) -> uuid.UUID:
    async with get_sessionmaker()() as session, session.begin():
        transaction = Transaction(
            household_id=home.household_id,
            account_id=account or home.bpi,
            status=TransactionStatus.BOOKED,
            entry_reference=uuid.uuid4().hex,
            fingerprint=uuid.uuid4().hex,
            occurrence_index=0,
            amount=Decimal(amount),
            currency=currency,
            occurred_on=date(2026, 10, day),
            booking_date=date(2026, 10, day),
            description=description,
            counterparty_name=counterparty,
            bank_transaction_code={"code": code} if code else None,
            payload_id=home.payload_id,
        )
        session.add(transaction)
    return transaction.id


async def add_rule(
    home: Home,
    position: int,
    conditions: list[dict[str, Any]],
    actions: list[dict[str, Any]],
    *,
    stop_processing: bool = False,
) -> uuid.UUID:
    async with get_sessionmaker()() as session, session.begin():
        rule = Rule(
            household_id=home.household_id,
            name=f"Rule {position}",
            position=position,
            match=RuleMatch.ALL,
            conditions=conditions,
            actions=actions,
            stop_processing=stop_processing,
        )
        session.add(rule)
    return rule.id


async def run(home: Home, ids: list[uuid.UUID] | None = None) -> CategorizeResult:
    async with get_sessionmaker()() as session, session.begin():
        return await categorize(session, home.household_id, ids)


@dataclass(frozen=True)
class State:
    category: str | None
    source: Source | None
    counterparty: str | None
    counterparty_source: Source | None
    kind_override: TransactionKind | None
    tags: list[str]
    rule_tags: list[str]


async def state(home: Home, transaction_id: uuid.UUID) -> State:
    async with get_sessionmaker()() as session:
        assignment = (
            await session.execute(
                select(Category.name, CategoryAssignment.source)
                .join(Category, Category.id == CategoryAssignment.category_id)
                .where(CategoryAssignment.transaction_id == transaction_id)
            )
        ).one_or_none()
        annotation = await session.get(TransactionAnnotation, transaction_id)
        counterparty = (
            await session.get(Counterparty, annotation.counterparty_id)
            if annotation and annotation.counterparty_id
            else None
        )
    return State(
        category=assignment[0] if assignment else None,
        source=assignment[1] if assignment else None,
        counterparty=counterparty.name if counterparty else None,
        counterparty_source=annotation.counterparty_source if annotation else None,
        kind_override=annotation.kind_override if annotation else None,
        tags=list(annotation.tags) if annotation else [],
        rule_tags=list(annotation.rule_tags) if annotation else [],
    )


async def set_default(home: Home, counterparty_name: str, category: str) -> None:
    async with get_sessionmaker()() as session, session.begin():
        counterparty = await session.scalar(
            select(Counterparty).where(
                Counterparty.household_id == home.household_id,
                Counterparty.name == counterparty_name,
            )
        )
        assert counterparty is not None
        counterparty.default_category_id = home.categories[category]


async def test_bank_names_become_counterparties_once(home: Home) -> None:
    first = await add(home, "-10", 1, counterparty="Continente")
    second = await add(home, "-12", 2, counterparty="CONTINENTE ")
    other = await add(home, "-3", 3, counterparty="Pingo Doce")

    result = await run(home)
    again = await run(home)

    assert (result.counterparties_created, again.counterparties_created) == (2, 0)
    assert (await state(home, first)).counterparty == "Continente"
    assert (await state(home, second)).counterparty == "Continente"
    assert (await state(home, other)).counterparty_source is Source.BANK


async def test_a_counterpartys_default_category_applies(home: Home) -> None:
    transaction = await add(home, "-10", 1, counterparty="Continente")
    await run(home)
    await set_default(home, "Continente", "Groceries")

    result = await run(home)

    assert result.categorized == 1
    assert (await state(home, transaction)).category == "Groceries"
    assert (await state(home, transaction)).source is Source.COUNTERPARTY


async def test_a_rule_beats_the_counterparty_default(home: Home) -> None:
    transaction = await add(home, "-30", 1, counterparty="Continente", description="CAFETARIA")
    await run(home)
    await set_default(home, "Continente", "Groceries")
    await add_rule(
        home,
        1,
        [{"field": "description", "op": "contains", "value": "cafetaria"}],
        [{"type": "set_category", "category_id": str(home.categories["Cafés & snacks"])}],
    )

    await run(home)

    assert (await state(home, transaction)).category == "Cafés & snacks"
    assert (await state(home, transaction)).source is Source.RULE


async def test_a_manual_category_is_never_overwritten(home: Home) -> None:
    transaction = await add(home, "-30", 1, description="CAFETARIA")
    async with get_sessionmaker()() as session, session.begin():
        session.add(
            CategoryAssignment(
                household_id=home.household_id,
                transaction_id=transaction,
                category_id=home.categories["Gifts & donations"],
                source=Source.MANUAL,
            )
        )
    await add_rule(
        home,
        1,
        [{"field": "description", "op": "contains", "value": "cafetaria"}],
        [{"type": "set_category", "category_id": str(home.categories["Cafés & snacks"])}],
    )

    await run(home)

    assert (await state(home, transaction)).category == "Gifts & donations"
    assert (await state(home, transaction)).source is Source.MANUAL


async def test_rules_run_in_order_and_can_stop(home: Home) -> None:
    transaction = await add(home, "-30", 1, description="UBER TRIP")
    category = home.categories
    set_to = [
        {"type": "set_category", "category_id": str(category[name])}
        for name in ("Taxi & ride-hailing", "Food delivery", "Travel")
    ]
    uber = [{"field": "description", "op": "contains", "value": "uber"}]
    await add_rule(home, 1, uber, [set_to[0]])
    await add_rule(home, 2, uber, [set_to[1]], stop_processing=True)
    await add_rule(home, 3, uber, [set_to[2]])

    await run(home)

    assert (await state(home, transaction)).category == "Food delivery"  # later wins, then stop


async def test_a_rule_names_the_counterparty_bpi_doesnt_send(home: Home) -> None:
    await run(home, [await add(home, "-1", 1, counterparty="Continente")])
    await set_default(home, "Continente", "Groceries")
    async with get_sessionmaker()() as session:
        continente = await session.scalar(
            select(Counterparty.id).where(
                Counterparty.household_id == home.household_id, Counterparty.name == "Continente"
            )
        )
    bpi = await add(home, "-42.17", 2, description="COMPRA 4450 CONTINENTE MATOSINHOS")
    await add_rule(
        home,
        1,
        [{"field": "description", "op": "contains", "value": "continente"}],
        [{"type": "set_counterparty", "counterparty_id": str(continente)}],
    )

    await run(home)

    after = await state(home, bpi)
    assert (after.counterparty, after.counterparty_source) == ("Continente", Source.RULE)
    assert (after.category, after.source) == ("Groceries", Source.COUNTERPARTY)


async def test_rule_tags_follow_the_rules_and_manual_tags_stay(home: Home) -> None:
    transaction = await add(home, "-9.99", 1, description="NETFLIX.COM")
    rule_id = await add_rule(
        home,
        1,
        [{"field": "description", "op": "contains", "value": "netflix"}],
        [{"type": "add_tag", "tag": "streaming"}],
    )
    await run(home)
    async with get_sessionmaker()() as session, session.begin():
        annotation = await session.get_one(TransactionAnnotation, transaction)
        annotation.tags = ["shared with Ana"]
        await session.delete(await session.get_one(Rule, rule_id))

    before = await state(home, transaction)
    await run(home)
    after = await state(home, transaction)

    assert before.rule_tags == ["streaming"]
    assert (after.rule_tags, after.tags) == ([], ["shared with Ana"])


async def test_seeded_rule_marks_revolut_exchanges_as_transfers(home: Home) -> None:
    exchange = await add(home, "-100", 1, account=home.revolut, code="EXCHANGE", counterparty="X")
    await run(home)
    await set_default(home, "X", "Travel")

    await run(home)

    after = await state(home, exchange)
    assert after.kind_override is TransactionKind.TRANSFER
    assert after.category is None  # transfers are neither income nor spending


async def test_a_kind_set_by_hand_wins_over_rules(home: Home) -> None:
    exchange = await add(home, "-100", 1, account=home.revolut, code="EXCHANGE")
    async with get_sessionmaker()() as session, session.begin():
        session.add(
            TransactionAnnotation(
                transaction_id=exchange,
                household_id=home.household_id,
                kind_override=TransactionKind.EXPENSE,
                kind_source=Source.MANUAL,
            )
        )

    await run(home)

    assert (await state(home, exchange)).kind_override is TransactionKind.EXPENSE


async def test_archived_categories_are_not_assigned(home: Home) -> None:
    transaction = await add(home, "-5", 1, description="PADARIA")
    await add_rule(
        home,
        1,
        [{"field": "description", "op": "contains", "value": "padaria"}],
        [{"type": "set_category", "category_id": str(home.categories["Groceries"])}],
    )
    async with get_sessionmaker()() as session, session.begin():
        category = await session.get_one(Category, home.categories["Groceries"])
        category.archived_at = category.created_at

    await run(home)

    assert (await state(home, transaction)).category is None


async def detect(home: Home) -> set[uuid.UUID]:
    async with get_sessionmaker()() as session, session.begin():
        return await detect_transfers(session, home.household_id)


async def pairs(home: Home) -> set[tuple[uuid.UUID, uuid.UUID]]:
    async with get_sessionmaker()() as session:
        return {
            (outgoing, incoming)
            for outgoing, incoming in await session.execute(
                select(Transfer.outgoing_id, Transfer.incoming_id).where(
                    Transfer.household_id == home.household_id
                )
            )
        }


async def test_a_unique_pair_becomes_a_transfer_without_a_category(home: Home) -> None:
    out = await add(home, "-200", 10, description="TRF REVOLUT", counterparty="Revolut")
    into = await add(home, "200", 11, account=home.revolut, code="TOPUP")
    await run(home)
    await set_default(home, "Revolut", "Other insurance")
    await run(home)
    assert (await state(home, out)).category == "Other insurance"

    async with get_sessionmaker()() as session, session.begin():
        await run_all(session, home.household_id)

    assert await pairs(home) == {(out, into)}
    assert (await state(home, out)).category is None


async def test_ambiguous_or_distant_matches_are_left_alone(home: Home) -> None:
    out = await add(home, "-50", 10)
    await add(home, "50", 10, account=home.revolut)
    await add(home, "50", 11, account=home.revolut)  # two candidates: ambiguous
    await add(home, "-70", 1)
    await add(home, "70", 5, account=home.revolut)  # 4 days apart
    await add(home, "-80", 1)
    await add(home, "80", 1, account=home.revolut, currency="USD")  # another currency
    await add(home, "-90", 1)
    await add(home, "90", 1)  # the same account

    linked = await detect(home)

    assert linked == set()
    assert out not in linked


async def test_an_unlinked_pair_is_never_linked_again(home: Home) -> None:
    out = await add(home, "-200", 10)
    into = await add(home, "200", 10, account=home.revolut)
    await detect(home)
    async with get_sessionmaker()() as session, session.begin():
        transfer = await session.scalar(select(Transfer).where(Transfer.outgoing_id == out))
        assert transfer is not None
        await session.delete(transfer)
        session.add(
            TransferDismissal(outgoing_id=out, incoming_id=into, household_id=home.household_id)
        )

    assert await detect(home) == set()
    assert await pairs(home) == set()
