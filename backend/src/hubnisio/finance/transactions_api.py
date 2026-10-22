"""Transactions and their user layer: listing and filtering, editing, transfer links.

Every query is scoped to the accounts the principal may see (finance/scoping.py).
"""

import base64
import binascii
import uuid
from collections.abc import Sequence
from datetime import date
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query, Response, status
from sqlalchemy import Select, and_, case, delete, func, not_, or_, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from hubnisio.core.auth import Principal
from hubnisio.finance import schemas
from hubnisio.finance.categorize.engine import categorize
from hubnisio.finance.deps import CurrentPrincipal, DbSession
from hubnisio.finance.models import (
    Account,
    Category,
    CategoryAssignment,
    Counterparty,
    Source,
    Transaction,
    TransactionAnnotation,
    TransactionKind,
    TransactionStatus,
    Transfer,
    TransferDismissal,
)
from hubnisio.finance.naming import account_name
from hubnisio.finance.scoping import visible_account_ids

router = APIRouter(prefix="/finance", tags=["finance"])

# One row per transaction: the outer-joined entities are None when missing.
TransactionRows = Select[
    Transaction,
    TransactionAnnotation,
    CategoryAssignment,
    Category,
    str,
    Counterparty,
    Transfer,
    uuid.UUID,
    Account,
]

MAX_TAG_LENGTH = 40
_Parent = aliased(Category)
_Other = aliased(Transaction)
_OtherAccount = aliased(Account)

# A transaction is a transfer when it's in a pair or its kind says so (NULL-safe).
_IS_TRANSFER = or_(
    Transfer.id.is_not(None),
    TransactionAnnotation.kind_override.is_not_distinct_from(TransactionKind.TRANSFER),
)


@router.get("/transactions", operation_id="listTransactions")
async def list_transactions(
    session: DbSession,
    principal: CurrentPrincipal,
    account_id: uuid.UUID | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    q: Annotated[str | None, Query(max_length=100)] = None,
    transaction_status: Annotated[TransactionStatus | None, Query(alias="status")] = None,
    kind: TransactionKind | None = None,
    category_id: uuid.UUID | None = None,
    uncategorized: bool = False,
    counterparty_id: uuid.UUID | None = None,
    cursor: str | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> schemas.TransactionPage:
    """Newest first. Pass `next_cursor` back as `cursor` for the next page. A group's
    `category_id` includes its categories; `uncategorized` leaves out transfers."""
    query = _query(principal)
    if account_id is not None:
        query = query.where(Transaction.account_id == account_id)
    if date_from is not None:
        query = query.where(Transaction.occurred_on >= date_from)
    if date_to is not None:
        query = query.where(Transaction.occurred_on <= date_to)
    if transaction_status is not None:
        query = query.where(Transaction.status == transaction_status)
    if kind is not None:
        query = query.where(_kind_is(kind))
    if category_id is not None:
        query = query.where(
            or_(CategoryAssignment.category_id == category_id, Category.parent_id == category_id)
        )
    if uncategorized:
        query = query.where(CategoryAssignment.id.is_(None), not_(_IS_TRANSFER))
    if counterparty_id is not None:
        query = query.where(TransactionAnnotation.counterparty_id == counterparty_id)
    if q and q.strip():
        pattern = f"%{_escape_like(q.strip())}%"
        query = query.where(
            or_(
                Transaction.description.ilike(pattern, escape="\\"),
                Transaction.counterparty_name.ilike(pattern, escape="\\"),
                Counterparty.name.ilike(pattern, escape="\\"),
                TransactionAnnotation.note.ilike(pattern, escape="\\"),
            )
        )
    if cursor is not None:
        after_date, after_id = _decode_cursor(cursor)
        query = query.where(
            tuple_(Transaction.occurred_on, Transaction.id) < tuple_(after_date, after_id)
        )

    rows = (
        await session.execute(
            query.order_by(Transaction.occurred_on.desc(), Transaction.id.desc()).limit(limit + 1)
        )
    ).all()
    page = rows[:limit]
    visible = await _visible(session, principal)
    return schemas.TransactionPage(
        items=[_out(row, visible) for row in page],
        next_cursor=_encode_cursor(page[-1].Transaction) if len(rows) > limit else None,
    )


@router.patch("/transactions/{transaction_id}", operation_id="updateTransaction")
async def update_transaction(
    transaction_id: uuid.UUID,
    body: schemas.TransactionUpdate,
    session: DbSession,
    principal: CurrentPrincipal,
) -> schemas.TransactionUpdated:
    """Set what a transaction is. Values set here win over rules and defaults; `null` hands
    the field back to them."""
    transaction = await _visible_transaction(session, principal, transaction_id)
    fields = body.model_fields_set
    annotation = await session.get(TransactionAnnotation, transaction.id)
    if annotation is None:
        annotation = TransactionAnnotation(
            transaction_id=transaction.id, household_id=principal.household_id, tags=[]
        )
        session.add(annotation)

    manual_category = None
    if "category_id" in fields:
        await session.execute(
            delete(CategoryAssignment).where(CategoryAssignment.transaction_id == transaction.id)
        )
        if body.category_id is not None:
            manual_category = await _usable_category(session, principal, body.category_id)
            session.add(
                CategoryAssignment(
                    household_id=principal.household_id,
                    transaction_id=transaction.id,
                    category_id=manual_category.id,
                    source=Source.MANUAL,
                )
            )
    if "counterparty_id" in fields:
        if body.counterparty_id is not None:
            await _own_counterparty(session, principal, body.counterparty_id)
            annotation.counterparty_id = body.counterparty_id
            annotation.counterparty_source = Source.MANUAL
        else:
            annotation.counterparty_source = None  # the bank's name or a rule decides again
    if "kind" in fields:
        annotation.kind_override = body.kind
        annotation.kind_source = Source.MANUAL if body.kind else None
        if body.kind in (TransactionKind.EXPENSE, TransactionKind.INCOME):
            await _unlink(session, principal, transaction.id)
    if "note" in fields:
        annotation.note = (body.note or "").strip() or None
    if "tags" in fields:
        annotation.tags = _clean_tags(body.tags or [])
    await session.flush()
    await categorize(session, principal.household_id, [transaction.id])
    await session.commit()

    offer = None
    if manual_category is not None:
        offer = await _offer_for_counterparty(session, principal, transaction.id, manual_category)
    (out,) = await _load(session, principal, [transaction.id])
    return schemas.TransactionUpdated(transaction=out, offer=offer)


@router.post("/transfers", status_code=status.HTTP_201_CREATED, operation_id="linkTransfer")
async def link_transfer(
    body: schemas.TransferLink, session: DbSession, principal: CurrentPrincipal
) -> list[schemas.TransactionOut]:
    """Pair two transactions as a transfer by hand."""
    outgoing = await _visible_transaction(session, principal, body.outgoing_id)
    incoming = await _visible_transaction(session, principal, body.incoming_id)
    if not (outgoing.amount < 0 < incoming.amount):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "A transfer needs money out of one account and into another.",
        )
    if outgoing.account_id == incoming.account_id:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "A transfer is between two accounts."
        )
    already = await session.scalar(
        select(func.count())
        .select_from(Transfer)
        .where(
            or_(
                Transfer.outgoing_id.in_([outgoing.id, incoming.id]),
                Transfer.incoming_id.in_([outgoing.id, incoming.id]),
            )
        )
    )
    if already:
        raise HTTPException(status.HTTP_409_CONFLICT, "One of them is already in a transfer.")
    await session.execute(
        delete(TransferDismissal).where(
            TransferDismissal.outgoing_id == outgoing.id,
            TransferDismissal.incoming_id == incoming.id,
        )
    )
    for annotation in await session.scalars(
        select(TransactionAnnotation).where(
            TransactionAnnotation.transaction_id.in_([outgoing.id, incoming.id]),
            TransactionAnnotation.kind_source == Source.MANUAL,
        )
    ):
        annotation.kind_override, annotation.kind_source = None, None
    session.add(
        Transfer(
            household_id=principal.household_id,
            outgoing_id=outgoing.id,
            incoming_id=incoming.id,
            source=Source.MANUAL,
        )
    )
    await session.flush()
    await categorize(session, principal.household_id, [outgoing.id, incoming.id])
    await session.commit()
    return await _load(session, principal, [outgoing.id, incoming.id])


@router.delete(
    "/transfers/{transfer_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    operation_id="unlinkTransfer",
)
async def unlink_transfer(
    transfer_id: uuid.UUID, session: DbSession, principal: CurrentPrincipal
) -> Response:
    """Undo a pair. Matching won't link these two again."""
    transfer = await session.get(Transfer, transfer_id)
    visible = await _visible(session, principal)
    if transfer is None or transfer.household_id != principal.household_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such transfer.")
    accounts = set(
        await session.scalars(
            select(Transaction.account_id).where(
                Transaction.id.in_([transfer.outgoing_id, transfer.incoming_id])
            )
        )
    )
    if not accounts & visible:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such transfer.")
    await _unlink(session, principal, transfer.outgoing_id)
    await session.flush()
    await categorize(session, principal.household_id, [transfer.outgoing_id, transfer.incoming_id])
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# Shared with the rules and categories API.


def transactions_query(principal: Principal) -> TransactionRows:
    return _query(principal)


async def load_transactions(
    session: AsyncSession, principal: Principal, ids: Sequence[uuid.UUID]
) -> list[schemas.TransactionOut]:
    return await _load(session, principal, ids)


def transaction_out(row: Any, visible: set[uuid.UUID]) -> schemas.TransactionOut:
    return _out(row, visible)


async def visible_accounts(session: AsyncSession, principal: Principal) -> set[uuid.UUID]:
    return await _visible(session, principal)


# Helpers


def _query(principal: Principal) -> TransactionRows:
    """One row per transaction, with its user layer and transfer counterpart."""
    other_id = case(
        (Transfer.outgoing_id == Transaction.id, Transfer.incoming_id),
        else_=Transfer.outgoing_id,
    )
    return (
        select(
            Transaction,
            TransactionAnnotation,
            CategoryAssignment,
            Category,
            _Parent.name.label("group_name"),
            Counterparty,
            Transfer,
            _Other.id.label("other_id"),
            _OtherAccount,
        )
        .outerjoin(TransactionAnnotation, TransactionAnnotation.transaction_id == Transaction.id)
        .outerjoin(CategoryAssignment, CategoryAssignment.transaction_id == Transaction.id)
        .outerjoin(Category, Category.id == CategoryAssignment.category_id)
        .outerjoin(_Parent, _Parent.id == Category.parent_id)
        .outerjoin(Counterparty, Counterparty.id == TransactionAnnotation.counterparty_id)
        .outerjoin(
            Transfer,
            or_(Transfer.outgoing_id == Transaction.id, Transfer.incoming_id == Transaction.id),
        )
        .outerjoin(_Other, _Other.id == other_id)
        .outerjoin(_OtherAccount, _OtherAccount.id == _Other.account_id)
        .where(Transaction.account_id.in_(visible_account_ids(principal)))
    )


def _kind_is(kind: TransactionKind) -> Any:
    override = TransactionAnnotation.kind_override
    match kind:
        case TransactionKind.TRANSFER:
            return _IS_TRANSFER
        case TransactionKind.INCOME:
            sign = and_(override.is_(None), Transaction.amount > 0)
        case _:
            sign = and_(override.is_(None), Transaction.amount <= 0)
    return and_(not_(_IS_TRANSFER), or_(override.is_not_distinct_from(kind), sign))


def _out(row: Any, visible: set[uuid.UUID]) -> schemas.TransactionOut:
    transaction: Transaction = row.Transaction
    annotation: TransactionAnnotation | None = row.TransactionAnnotation
    assignment: CategoryAssignment | None = row.CategoryAssignment
    category: Category | None = row.Category
    counterparty: Counterparty | None = row.Counterparty
    transfer: Transfer | None = row.Transfer
    other_account: Account | None = row[8]

    if transfer is not None:
        kind, kind_source = TransactionKind.TRANSFER, transfer.source
    elif annotation is not None and annotation.kind_override is not None:
        kind, kind_source = annotation.kind_override, annotation.kind_source
    else:
        kind = TransactionKind.INCOME if transaction.amount > 0 else TransactionKind.EXPENSE
        kind_source = None

    return schemas.TransactionOut(
        id=transaction.id,
        account_id=transaction.account_id,
        status=transaction.status,
        occurred_on=transaction.occurred_on,
        booking_date=transaction.booking_date,
        value_date=transaction.value_date,
        amount=transaction.amount,
        currency=transaction.currency,
        original_amount=transaction.original_amount,
        original_currency=transaction.original_currency,
        counterparty_name=transaction.counterparty_name,
        description=transaction.description,
        reference=transaction.reference,
        mcc=transaction.mcc,
        bank_code=(transaction.bank_transaction_code or {}).get("code") or None,
        kind=kind,
        kind_source=kind_source,
        category=(
            schemas.TransactionCategory(
                id=category.id,
                name=category.name,
                group_name=row.group_name,
                source=assignment.source,
            )
            if category is not None and assignment is not None
            else None
        ),
        counterparty=(
            schemas.TransactionCounterparty(
                id=counterparty.id,
                name=counterparty.name,
                source=annotation.counterparty_source if annotation else None,
            )
            if counterparty is not None
            else None
        ),
        transfer=(
            schemas.TransactionTransfer(
                id=transfer.id,
                other_transaction_id=row.other_id,
                other_account_id=other_account.id,
                # Another member's private account stays unnamed.
                other_account_name=(
                    account_name(other_account)
                    if other_account.id in visible
                    else "Another household account"
                ),
                source=transfer.source,
            )
            if transfer is not None and other_account is not None
            else None
        ),
        note=annotation.note if annotation else None,
        tags=list(annotation.tags) if annotation else [],
        rule_tags=list(annotation.rule_tags) if annotation else [],
    )


async def _load(
    session: AsyncSession, principal: Principal, ids: Sequence[uuid.UUID]
) -> list[schemas.TransactionOut]:
    rows = (await session.execute(_query(principal).where(Transaction.id.in_(ids)))).all()
    by_id = {row.Transaction.id: row for row in rows}
    visible = await _visible(session, principal)
    return [_out(by_id[id_], visible) for id_ in ids if id_ in by_id]


async def _visible(session: AsyncSession, principal: Principal) -> set[uuid.UUID]:
    return set(await session.scalars(visible_account_ids(principal)))


async def _visible_transaction(
    session: AsyncSession, principal: Principal, transaction_id: uuid.UUID
) -> Transaction:
    transaction = await session.scalar(
        select(Transaction).where(
            Transaction.id == transaction_id,
            Transaction.account_id.in_(visible_account_ids(principal)),
        )
    )
    if transaction is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such transaction.")
    return transaction


async def _usable_category(
    session: AsyncSession, principal: Principal, category_id: uuid.UUID
) -> Category:
    category = await session.get(Category, category_id)
    if (
        category is None
        or category.household_id != principal.household_id
        or category.archived_at is not None
    ):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such category.")
    return category


async def _own_counterparty(
    session: AsyncSession, principal: Principal, counterparty_id: uuid.UUID
) -> Counterparty:
    counterparty = await session.get(Counterparty, counterparty_id)
    if counterparty is None or counterparty.household_id != principal.household_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such counterparty.")
    return counterparty


async def _unlink(session: AsyncSession, principal: Principal, transaction_id: uuid.UUID) -> None:
    """Remove the transaction's transfer pair, if any, and remember not to relink it."""
    transfer = await session.scalar(
        select(Transfer).where(
            or_(Transfer.outgoing_id == transaction_id, Transfer.incoming_id == transaction_id)
        )
    )
    if transfer is None:
        return
    await session.delete(transfer)
    exists = await session.get(TransferDismissal, (transfer.outgoing_id, transfer.incoming_id))
    if exists is None:
        session.add(
            TransferDismissal(
                outgoing_id=transfer.outgoing_id,
                incoming_id=transfer.incoming_id,
                household_id=principal.household_id,
            )
        )


async def _offer_for_counterparty(
    session: AsyncSession,
    principal: Principal,
    transaction_id: uuid.UUID,
    category: Category,
) -> schemas.ApplyToCounterparty | None:
    """After a category is set by hand: offer it as the counterparty's default, if the
    counterparty has other transactions and doesn't already default to it."""
    counterparty = await session.scalar(
        select(Counterparty)
        .join(TransactionAnnotation, TransactionAnnotation.counterparty_id == Counterparty.id)
        .where(TransactionAnnotation.transaction_id == transaction_id)
    )
    if counterparty is None or counterparty.default_category_id == category.id:
        return None
    others = await session.scalar(
        select(func.count())
        .select_from(TransactionAnnotation)
        .join(Transaction, Transaction.id == TransactionAnnotation.transaction_id)
        .where(
            TransactionAnnotation.counterparty_id == counterparty.id,
            Transaction.id != transaction_id,
            Transaction.account_id.in_(visible_account_ids(principal)),
        )
    )
    if not others:
        return None
    return schemas.ApplyToCounterparty(
        counterparty_id=counterparty.id,
        counterparty_name=counterparty.name,
        category_id=category.id,
        other_transactions=others,
    )


def _clean_tags(tags: list[str]) -> list[str]:
    cleaned: list[str] = []
    for tag in tags:
        tag = tag.strip()[:MAX_TAG_LENGTH]
        if tag and tag.casefold() not in {existing.casefold() for existing in cleaned}:
            cleaned.append(tag)
    return cleaned


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _encode_cursor(row: Transaction) -> str:
    raw = f"{row.occurred_on.isoformat()}|{row.id}"
    return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")


def _decode_cursor(cursor: str) -> tuple[date, uuid.UUID]:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        day, _, id_ = base64.urlsafe_b64decode(padded).decode().partition("|")
        return date.fromisoformat(day), uuid.UUID(id_)
    except (binascii.Error, UnicodeDecodeError, ValueError) as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid cursor.") from exc
