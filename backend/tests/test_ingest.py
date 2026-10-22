"""Identity and deduplication against a real database (ADR-0007, action item 3)."""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy import select

from hubnisio.core.db import get_sessionmaker
from hubnisio.core.models import Household, User
from hubnisio.finance.ingest.apply import apply_payloads
from hubnisio.finance.ingest.renormalize import renormalize_account
from hubnisio.finance.ingest.store import BANK_FACTS, StoreResult
from hubnisio.finance.models import (
    Account,
    BalanceSnapshot,
    Connection,
    ConnectionStatus,
    ProviderName,
    ProviderPayload,
    SyncRun,
    SyncStatus,
    Transaction,
    TransactionStatus,
)

pytestmark = pytest.mark.anyio


@dataclass(frozen=True)
class World:
    household_id: uuid.UUID
    account_id: uuid.UUID
    connection_ids: tuple[uuid.UUID, uuid.UUID]  # e.g. two partners' consents for a joint account


@pytest.fixture
async def world(migrated_database: str) -> World:
    async with get_sessionmaker()() as session, session.begin():
        user = User(email=f"{uuid.uuid4().hex}@example.com", display_name="Test")
        household = Household(name="Test")
        session.add_all([user, household])
        await session.flush()
        connections = [
            Connection(
                household_id=household.id,
                user_id=user.id,
                provider=ProviderName.ENABLE_BANKING,
                institution_name="Banco Exemplo",
                institution_country="PT",
                status=ConnectionStatus.ACTIVE,
            )
            for _ in range(2)
        ]
        account = Account(
            household_id=household.id,
            identification_hash=uuid.uuid4().hex,
            institution_name="Banco Exemplo",
            currency="EUR",
        )
        session.add_all([*connections, account])
        await session.flush()
        created = World(household.id, account.id, (connections[0].id, connections[1].id))
    return created


def tx(
    reference: str | None,
    amount: str,
    day: int,
    *,
    status: str = "BOOK",
    text: str = "COMPRA SUPERMERCADO",
    **extra: Any,
) -> dict[str, Any]:
    item: dict[str, Any] = {
        "transaction_amount": {"currency": "EUR", "amount": amount},
        "credit_debit_indicator": "DBIT",
        "status": status,
        "transaction_date": f"2026-10-{day:02d}",
        "creditor": {"name": "Supermercado"},
        "remittance_information": [text],
        **extra,
    }
    if status == "BOOK":
        item["booking_date"] = f"2026-10-{day:02d}"
    if reference is not None:
        item["entry_reference"] = reference
    return item


async def sync(
    world: World,
    *pages: list[dict[str, Any]],
    connection: int = 0,
    balances: list[dict[str, Any]] | None = None,
    status: SyncStatus = SyncStatus.SUCCEEDED,
) -> StoreResult:
    """What a sync does after fetching: store the payloads, then apply them."""
    async with get_sessionmaker()() as session, session.begin():
        run = SyncRun(
            household_id=world.household_id,
            connection_id=world.connection_ids[connection],
            account_id=world.account_id,
            trigger="scheduled",
            strategy="default",
            status=status,
            started_at=datetime.now(UTC),
        )
        session.add(run)
        await session.flush()
        responses = [("balances", {"balances": balances})] if balances else []
        responses += [("transactions", {"transactions": page}) for page in pages]
        payloads = [
            ProviderPayload(
                household_id=world.household_id,
                connection_id=world.connection_ids[connection],
                account_id=world.account_id,
                sync_run_id=run.id,
                kind=kind,
                request={},
                response=response,
                fetched_at=datetime.now(UTC),
            )
            for kind, response in responses
        ]
        session.add_all(payloads)
        await session.flush()
        if status is not SyncStatus.SUCCEEDED:
            return StoreResult(seen=0, added=0)
        return await apply_payloads(
            session,
            provider=ProviderName.ENABLE_BANKING,
            household_id=world.household_id,
            account_id=world.account_id,
            sync_run_id=run.id,
            payloads=payloads,
        )


async def stored(world: World) -> list[Transaction]:
    async with get_sessionmaker()() as session:
        return list(
            await session.scalars(
                select(Transaction)
                .where(Transaction.account_id == world.account_id)
                .order_by(
                    Transaction.occurred_on,
                    Transaction.status,
                    Transaction.fingerprint,
                    Transaction.occurrence_index,
                )
            )
        )


def facts(transactions: list[Transaction]) -> list[tuple[object, ...]]:
    """Everything about the rows except their IDs."""
    columns = (
        "status",
        "entry_reference",
        "fingerprint",
        "occurrence_index",
        *BANK_FACTS,
        "first_seen_at",
        "last_seen_at",
    )
    return [tuple(getattr(row, column) for column in columns) for row in transactions]


async def test_syncing_the_same_data_twice_changes_nothing(world: World) -> None:
    page = [tx("R1", "10.00", 1), tx("R2", "20.00", 2), tx(None, "5.00", 3)]

    first = await sync(world, page)
    before = await stored(world)
    second = await sync(world, page)
    after = await stored(world)

    assert (first.seen, first.added) == (3, 3)
    assert (second.seen, second.added) == (3, 0)
    assert [row.id for row in after] == [row.id for row in before]
    assert all(row.last_seen_at > row.first_seen_at for row in after)


async def test_overlapping_windows_store_each_transaction_once(world: World) -> None:
    await sync(world, [tx("R1", "1.00", 1), tx("R2", "2.00", 5), tx(None, "3.00", 6)])
    result = await sync(world, [tx("R2", "2.00", 5), tx(None, "3.00", 6), tx("R3", "4.00", 9)])

    assert result.added == 1
    assert len(await stored(world)) == 4


async def test_identical_transactions_on_the_same_day_stay_distinct(world: World) -> None:
    twins = [tx(None, "1.20", 4, text="CAFE"), tx(None, "1.20", 4, text="CAFE")]

    await sync(world, twins)
    await sync(world, twins)

    rows = await stored(world)
    assert [row.occurrence_index for row in rows] == [0, 1]


async def test_refless_rows_survive_cosmetic_description_changes(world: World) -> None:
    await sync(world, [tx(None, "7.00", 2, text="COMPRA 1234 PADARIA")])
    result = await sync(world, [tx(None, "7.00", 2, text="Compra 1234  padaria")])

    rows = await stored(world)
    assert result.added == 0
    assert len(rows) == 1
    assert rows[0].description == "Compra 1234  padaria"  # bank facts follow the latest fetch


async def test_bank_corrections_update_facts_but_keep_the_row(world: World) -> None:
    await sync(world, [tx("R1", "10.00", 1, text="ORIGINAL")])
    (before,) = await stored(world)
    await sync(world, [tx("R1", "10.00", 1, text="CORRECTED", merchant_category_code="5812")])
    (after,) = await stored(world)

    assert after.id == before.id
    assert after.first_seen_at == before.first_seen_at
    assert (after.description, after.mcc) == ("CORRECTED", "5812")


async def test_pending_is_replaced_by_each_sync(world: World) -> None:
    await sync(world, [tx(None, "3.50", 10, status="PDNG"), tx(None, "8.00", 11, status="PDNG")])
    await sync(world, [tx(None, "8.00", 11, status="PDNG")])

    rows = await stored(world)
    assert [(row.status, str(row.amount)) for row in rows] == [
        (TransactionStatus.PENDING, "-8.0000")
    ]


async def test_pending_disappears_when_it_books(world: World) -> None:
    await sync(world, [tx(None, "3.50", 10, status="PDNG")])
    await sync(world, [tx("R9", "3.50", 10)])

    rows = await stored(world)
    assert [(row.status, row.entry_reference) for row in rows] == [(TransactionStatus.BOOKED, "R9")]


async def test_duplicate_references_from_the_bank(world: World) -> None:
    page = [
        tx("SAME", "1.00", 1),
        tx("SAME", "1.00", 1),  # the same transaction, listed twice
        tx("SHARED", "2.00", 2, text="A"),
        tx("SHARED", "3.00", 2, text="B"),  # different transactions, one reference
    ]

    await sync(world, page)
    await sync(world, page)

    rows = await stored(world)
    assert sorted((str(row.amount), row.entry_reference) for row in rows) == [
        ("-1.0000", "SAME"),
        ("-2.0000", None),
        ("-3.0000", None),
    ]


async def test_a_joint_account_seen_through_two_connections_is_stored_once(
    world: World,
) -> None:
    page = [tx("R1", "50.00", 3), tx(None, "12.00", 4)]

    await sync(world, page, connection=0)
    result = await sync(world, page, connection=1)

    assert result.added == 0
    assert len(await stored(world)) == 2


async def test_balances_are_snapshotted(world: World) -> None:
    await sync(
        world,
        [],
        balances=[
            {"balance_amount": {"currency": "EUR", "amount": "99.50"}, "balance_type": "CLBD"}
        ],
    )

    async with get_sessionmaker()() as session:
        snapshots = list(
            await session.scalars(
                select(BalanceSnapshot).where(BalanceSnapshot.account_id == world.account_id)
            )
        )
    assert [(snapshot.balance_type, str(snapshot.amount)) for snapshot in snapshots] == [
        ("CLBD", "99.5000")
    ]


async def test_renormalize_rebuilds_the_same_rows(world: World) -> None:
    await sync(
        world,
        [tx("R1", "10.00", 1), tx(None, "1.20", 4), tx(None, "1.20", 4)],
        [tx(None, "3.50", 10, status="PDNG")],
        balances=[
            {"balance_amount": {"currency": "EUR", "amount": "99.50"}, "balance_type": "CLBD"}
        ],
    )
    await sync(world, [tx("R1", "10.00", 1, text="CORRECTED"), tx("R2", "2.00", 6)])
    await sync(world, [tx("IGNORED", "999.00", 7)], status=SyncStatus.FAILED)
    before = facts(await stored(world))

    async with get_sessionmaker()() as session, session.begin():
        result = await renormalize_account(session, world.account_id)

    assert (result.syncs, result.transactions) == (2, 4)
    assert facts(await stored(world)) == before
