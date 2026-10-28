"""Finance HTTP API: linking banks, syncing, accounts and transactions.

Every query that returns account data is scoped through `finance.scoping` (ADR-0005).
"""

import ipaddress
import time
import uuid
from collections.abc import AsyncIterator, Sequence
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import JSONResponse
from sqlalchemy import func, or_, select
from sqlalchemy.dialects.postgresql import distinct_on
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from hubnisio.core.auth import Principal
from hubnisio.core.crypto import SecretBox, get_secret_box
from hubnisio.core.settings import get_settings
from hubnisio.finance import linking, schemas, tasks
from hubnisio.finance.balances import latest_balances
from hubnisio.finance.deps import CurrentPrincipal, DbSession
from hubnisio.finance.models import (
    Account,
    AccountOwner,
    BalanceSnapshot,
    Category,
    CategoryKind,
    Connection,
    ConnectionStatus,
    ProviderAccount,
    ProviderName,
    Source,
    SyncRun,
    SyncStatus,
    Transaction,
    TransactionAnnotation,
    TransactionKind,
    Transfer,
)
from hubnisio.finance.naming import account_name
from hubnisio.finance.providers.enable_banking.client import (
    EnableBankingClient,
    psu_headers_from_request,
)
from hubnisio.finance.providers.enable_banking.errors import EnableBankingError, SessionEnded
from hubnisio.finance.scoping import is_owner, listed_account_ids, visible_account_ids
from hubnisio.finance.sync import SyncTrigger

router = APIRouter(prefix="/finance", tags=["finance"])

BANK_LIST_TTL = 6 * 3600  # seconds
# A run still "running" after this long crashed; don't show it as syncing forever.
STALE_RUN = timedelta(minutes=30)

_bank_cache: dict[str, tuple[float, list[schemas.Bank]]] = {}


async def get_enable_banking() -> AsyncIterator[EnableBankingClient]:
    try:
        client = EnableBankingClient.from_settings(get_settings())
    except (RuntimeError, OSError) as exc:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, f"Enable Banking isn't configured: {exc}"
        ) from exc
    async with client:
        yield client


def get_box() -> SecretBox:
    try:
        return get_secret_box()
    except (OSError, ValueError) as exc:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, f"Encryption keys aren't configured: {exc}"
        ) from exc


Banking = Annotated[EnableBankingClient, Depends(get_enable_banking)]
Box = Annotated[SecretBox, Depends(get_box)]


def _bad_gateway(exc: EnableBankingError) -> HTTPException:
    return HTTPException(
        status.HTTP_502_BAD_GATEWAY, f"Enable Banking error: {exc.code or exc.status}"
    )


# Banks and linking


@router.get("/banks", operation_id="listBanks")
async def list_banks(
    client: Banking, country: Annotated[str, Query(pattern=r"^[A-Z]{2}$")]
) -> list[schemas.Bank]:
    cached = _bank_cache.get(country)
    if cached is not None and cached[0] > time.monotonic():
        return cached[1]
    try:
        banks = await client.get_aspsps(country)
    except EnableBankingError as exc:
        raise _bad_gateway(exc) from exc
    result = sorted(
        (
            schemas.Bank(name=bank.name, country=bank.country, logo=bank.logo, beta=bank.beta)
            for bank in banks
            if "personal" in bank.psu_types or not bank.psu_types
        ),
        key=lambda bank: bank.name.casefold(),
    )
    _bank_cache[country] = (time.monotonic() + BANK_LIST_TTL, result)
    return result


@router.post("/connections", status_code=status.HTTP_201_CREATED, operation_id="startConnection")
async def start_connection(
    body: schemas.StartConnection,
    session: DbSession,
    principal: CurrentPrincipal,
    client: Banking,
) -> schemas.StartedConnection:
    try:
        url = await linking.start_connection(
            session,
            client,
            principal,
            institution_name=body.institution_name,
            country=body.country,
            redirect_url=get_settings().enable_banking_redirect_url,
        )
    except linking.UnknownBank as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such bank.") from exc
    except EnableBankingError as exc:
        raise _bad_gateway(exc) from exc
    await session.commit()
    return schemas.StartedConnection(url=url)


@router.post("/connections/complete", operation_id="completeConnection")
async def complete_connection(
    body: schemas.CompleteConnection,
    session: DbSession,
    principal: CurrentPrincipal,
    client: Banking,
    box: Box,
) -> schemas.ConnectionOut:
    try:
        connection, completed = await linking.complete_connection(
            session, client, box, principal, code=body.code, state=body.state
        )
    except linking.UnknownAuthorization as exc:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "This link isn't pending for you. Start again."
        ) from exc
    except linking.AuthorizationLost as exc:
        await session.commit()
        raise HTTPException(
            status.HTTP_409_CONFLICT, "This authorization was already used. Start again."
        ) from exc
    except EnableBankingError as exc:
        raise _bad_gateway(exc) from exc
    await session.commit()
    if completed:
        # Full history is often available only for about an hour after linking.
        await tasks.defer_sync(connection.id, trigger=SyncTrigger.INITIAL)
    (out,) = await _connections_out(session, principal, connection_ids=[connection.id])
    return out


@router.get("/connections", operation_id="listConnections")
async def list_connections(
    session: DbSession, principal: CurrentPrincipal
) -> list[schemas.ConnectionOut]:
    return await _connections_out(session, principal)


@router.delete(
    "/connections/{connection_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    operation_id="deleteConnection",
)
async def delete_connection(
    connection_id: uuid.UUID,
    session: DbSession,
    principal: CurrentPrincipal,
    client: Banking,
    box: Box,
) -> Response:
    """Close the bank session (and consent, where the bank supports it). The accounts and
    their history stay."""
    connection = await _own_connection(session, principal, connection_id)
    if connection.status is ConnectionStatus.ACTIVE and connection.session_id_encrypted:
        session_id = box.decrypt(
            connection.session_id_encrypted, linking.session_id_context(connection.id)
        )
        try:
            await client.delete_session(session_id)
        except SessionEnded:
            pass
        except EnableBankingError as exc:
            raise _bad_gateway(exc) from exc
    connection.status = ConnectionStatus.REVOKED
    connection.session_id_encrypted = None
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/connections/{connection_id}/sync",
    status_code=status.HTTP_202_ACCEPTED,
    operation_id="syncConnection",
)
async def sync_connection(
    connection_id: uuid.UUID,
    request: Request,
    session: DbSession,
    principal: CurrentPrincipal,
) -> schemas.SyncQueued:
    connection = await _own_connection(session, principal, connection_id)
    if connection.status is not ConnectionStatus.ACTIVE:
        raise HTTPException(status.HTTP_409_CONFLICT, "Link this bank again first.")
    # Only banks have a limit that the user's presence lifts.
    banking = connection.provider is ProviderName.ENABLE_BANKING
    queued = await tasks.defer_sync(
        connection.id,
        trigger=SyncTrigger.USER,
        psu_headers=_psu_headers(request) if banking else None,
    )
    return schemas.SyncQueued(queued=queued)


# Accounts


@router.get("/accounts", operation_id="listAccounts")
async def list_accounts(
    session: DbSession, principal: CurrentPrincipal, include_hidden: bool = False
) -> list[schemas.AccountOut]:
    """Hidden accounts are left out unless `include_hidden` (ADR-0007, "Retiring an
    account")."""
    scope = visible_account_ids(principal) if include_hidden else listed_account_ids(principal)
    accounts = list(
        await session.scalars(
            select(Account)
            .where(Account.id.in_(scope))
            # Accounts linked together share `created_at`: the id keeps their order
            # stable across updates, so the rows don't swap under the user's cursor.
            .order_by(Account.institution_name, Account.created_at, Account.id)
        )
    )
    owned = set(
        await session.scalars(
            select(AccountOwner.account_id).where(AccountOwner.user_id == principal.user_id)
        )
    )
    ids = [account.id for account in accounts]
    balances = await latest_balances(session, ids)
    counts = await _transaction_counts(session, ids)
    return [
        _account_out(account, account.id in owned, balances.get(account.id), counts)
        for account in accounts
    ]


@router.patch("/accounts/{account_id}", operation_id="updateAccount")
async def update_account(
    account_id: uuid.UUID,
    body: schemas.AccountUpdate,
    session: DbSession,
    principal: CurrentPrincipal,
) -> schemas.AccountOut:
    """Only an account's owners can change it. Hiding it, or making it a shared pot, is for
    the whole household."""
    account = await _own_account(session, principal, account_id)
    if body.pot_category_id is not None:
        await _pot_category(session, principal, body.pot_category_id)
    if "display_name" in body.model_fields_set:
        account.display_name = (body.display_name or "").strip() or None
    if body.visibility is not None:
        account.visibility = body.visibility
    if body.include_in_net_worth is not None:
        account.include_in_net_worth = body.include_in_net_worth
    if body.hidden is not None and body.hidden != (account.hidden_at is not None):
        account.hidden_at = datetime.now(UTC) if body.hidden else None
    if body.is_pot is not None:
        account.is_pot = body.is_pot
    if "pot_category_id" in body.model_fields_set:
        account.pot_category_id = body.pot_category_id
    await session.commit()
    balances = await latest_balances(session, [account.id])
    counts = await _transaction_counts(session, [account.id])
    return _account_out(account, True, balances.get(account.id), counts)


@router.delete(
    "/accounts/{account_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    operation_id="deleteAccount",
    responses={status.HTTP_409_CONFLICT: {"model": schemas.AccountDeleteBlocked}},
)
async def delete_account(
    account_id: uuid.UUID,
    session: DbSession,
    principal: CurrentPrincipal,
    confirm: bool = False,
) -> Response:
    """Delete an account with its transactions and everything decided about them, its
    balances and its transfer pairs. An account with transactions needs `confirm=true`.

    A pair's side on an account that stays is kept as a transfer, so spending and income
    don't change. If the bank still offers the account, a re-link brings it back: hiding is
    the lasting way to retire it."""
    account = await _own_account(session, principal, account_id)
    count = (await _transaction_counts(session, [account.id])).get(account.id, 0)
    kept = await _kept_transfer_sides(session, account.id)
    if count and not confirm:
        blocked = schemas.AccountDeleteBlocked(
            detail="This account has transactions. Confirm to delete them with it.",
            transaction_count=count,
            transfer_count=len(kept),
        )
        return JSONResponse(blocked.model_dump(), status_code=status.HTTP_409_CONFLICT)
    await _keep_as_transfers(session, principal, kept)
    await session.delete(account)  # the foreign keys cascade to the rest
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# Helpers


async def _own_account(
    session: AsyncSession, principal: Principal, account_id: uuid.UUID
) -> Account:
    """One of the principal's own accounts. Any other is a 404, so another member's private
    account doesn't even show that it exists."""
    account = await session.scalar(
        select(Account).where(
            Account.id == account_id,
            Account.household_id == principal.household_id,
            is_owner(principal, Account.id),
        )
    )
    if account is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such account among yours.")
    return account


async def _pot_category(
    session: AsyncSession, principal: Principal, category_id: uuid.UUID
) -> Category:
    """A household expense category in use: where contributions to a pot count."""
    category = await session.scalar(
        select(Category).where(
            Category.id == category_id,
            Category.household_id == principal.household_id,
            Category.user_id.is_(None),
        )
    )
    if category is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such category.")
    if category.kind != CategoryKind.EXPENSE or category.archived_at is not None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "Contributions to a pot need an expense category that isn't archived.",
        )
    return category


async def _transaction_counts(
    session: AsyncSession, account_ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, int]:
    rows = await session.execute(
        select(Transaction.account_id, func.count())
        .where(Transaction.account_id.in_(account_ids))
        .group_by(Transaction.account_id)
    )
    return {account_id: count for account_id, count in rows}


async def _kept_transfer_sides(session: AsyncSession, account_id: uuid.UUID) -> list[uuid.UUID]:
    """For each transfer pair between this account and another: the other side's ID."""
    outgoing, incoming = aliased(Transaction), aliased(Transaction)
    rows = await session.execute(
        select(outgoing.id, outgoing.account_id, incoming.id)
        .select_from(Transfer)
        .join(outgoing, outgoing.id == Transfer.outgoing_id)
        .join(incoming, incoming.id == Transfer.incoming_id)
        .where(
            or_(outgoing.account_id == account_id, incoming.account_id == account_id),
            outgoing.account_id != incoming.account_id,
        )
    )
    return [
        incoming_id if outgoing_account == account_id else outgoing_id
        for outgoing_id, outgoing_account, incoming_id in rows
    ]


async def _keep_as_transfers(
    session: AsyncSession, principal: Principal, transaction_ids: Sequence[uuid.UUID]
) -> None:
    """Mark these as transfers (source `auto`) before their pairs go, unless their kind was
    set by hand. The rules engine leaves an `auto` kind alone (categorize/engine.py)."""
    annotations = {
        annotation.transaction_id: annotation
        for annotation in await session.scalars(
            select(TransactionAnnotation).where(
                TransactionAnnotation.transaction_id.in_(transaction_ids)
            )
        )
    }
    for transaction_id in transaction_ids:
        annotation = annotations.get(transaction_id)
        if annotation is None:
            annotation = TransactionAnnotation(
                transaction_id=transaction_id, household_id=principal.household_id, tags=[]
            )
            session.add(annotation)
        elif annotation.kind_source is Source.MANUAL:
            continue
        annotation.kind_override = TransactionKind.TRANSFER
        annotation.kind_source = Source.AUTO
    await session.flush()


async def _own_connection(
    session: AsyncSession, principal: Principal, connection_id: uuid.UUID
) -> Connection:
    connection = await session.scalar(
        select(Connection).where(
            Connection.id == connection_id,
            Connection.user_id == principal.user_id,
            Connection.household_id == principal.household_id,
        )
    )
    if connection is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such connection.")
    return connection


async def _connections_out(
    session: AsyncSession,
    principal: Principal,
    *,
    connection_ids: Sequence[uuid.UUID] | None = None,
) -> list[schemas.ConnectionOut]:
    """The principal's own connections: consent is personal (ADR-0005). Abandoned and closed
    ones are left out."""
    query = select(Connection).where(
        Connection.user_id == principal.user_id,
        Connection.household_id == principal.household_id,
    )
    if connection_ids is None:
        query = query.where(
            Connection.status.in_([ConnectionStatus.ACTIVE, ConnectionStatus.EXPIRED])
        )
    else:
        query = query.where(Connection.id.in_(connection_ids))
    connections = list(await session.scalars(query.order_by(Connection.created_at)))
    ids = [connection.id for connection in connections]

    account_ids: dict[uuid.UUID, list[uuid.UUID]] = {id_: [] for id_ in ids}
    for connection_id, account_id in await session.execute(
        select(ProviderAccount.connection_id, ProviderAccount.account_id)
        .where(ProviderAccount.connection_id.in_(ids))
        .order_by(ProviderAccount.account_id)
    ):
        account_ids[connection_id].append(account_id)

    now = datetime.now(UTC)
    syncing = set(
        await session.scalars(
            select(SyncRun.connection_id).where(
                SyncRun.connection_id.in_(ids),
                SyncRun.status == SyncStatus.RUNNING,
                SyncRun.started_at > now - STALE_RUN,
            )
        )
    )
    latest = (
        select(SyncRun.connection_id, SyncRun.status, SyncRun.error_code)
        .where(SyncRun.connection_id.in_(ids), SyncRun.finished_at.is_not(None))
        .order_by(SyncRun.connection_id, SyncRun.finished_at.desc())
        .ext(distinct_on(SyncRun.connection_id))
    )
    last_error = {
        connection_id: error_code if run_status is SyncStatus.FAILED else None
        for connection_id, run_status, error_code in await session.execute(latest)
    }

    return [
        schemas.ConnectionOut(
            id=connection.id,
            provider=connection.provider,
            institution_name=connection.institution_name,
            institution_country=connection.institution_country,
            status=connection.status,
            valid_until=connection.valid_until,
            days_left=(
                max((connection.valid_until - now).days, 0) if connection.valid_until else None
            ),
            key_file=connection.key_file,
            last_synced_at=connection.last_synced_at,
            syncing=connection.id in syncing,
            last_error=last_error.get(connection.id),
            account_ids=account_ids[connection.id],
        )
        for connection in connections
    ]


def _account_out(
    account: Account,
    owned: bool,
    balance: BalanceSnapshot | None,
    transaction_counts: dict[uuid.UUID, int],
) -> schemas.AccountOut:
    return schemas.AccountOut(
        id=account.id,
        name=account_name(account),
        institution_name=account.institution_name,
        iban_masked=f"{account.iban[:4]} •••• {account.iban[-4:]}" if account.iban else None,
        currency=account.currency,
        cash_account_type=account.cash_account_type,
        visibility=account.visibility,
        include_in_net_worth=account.include_in_net_worth,
        is_owner=owned,
        hidden_at=account.hidden_at,
        is_pot=account.is_pot,
        pot_category_id=account.pot_category_id,
        is_investment=account.is_investment,
        transaction_count=transaction_counts.get(account.id, 0),
        balance=(
            schemas.Balance(
                balance_type=balance.balance_type,
                amount=balance.amount,
                currency=balance.currency,
                fetched_at=balance.fetched_at,
            )
            if balance
            else None
        ),
    )


def _psu_headers(request: Request) -> dict[str, str] | None:
    """The user's details for the bank, which lift its limit on unattended fetches. Only sent
    with a public IP address: behind the dev proxy or a VPN the app sees a private one."""
    host = request.client.host if request.client else None
    try:
        if host is None or not ipaddress.ip_address(host).is_global:
            return None
    except ValueError:
        return None
    return psu_headers_from_request(host, request.headers)
