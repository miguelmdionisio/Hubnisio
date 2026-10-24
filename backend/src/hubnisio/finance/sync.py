"""Bringing a connection's accounts up to date (ADR-0003, ADR-0007, ADR-0008).

For each account the connection reaches: fetch balances and transactions through the
connection's provider, store every raw response, then apply them. The first sync asks for the
longest history the provider offers (a bank's full history is often only available for about an
hour after linking); later syncs re-fetch from two weeks before the latest booked transaction,
so late-booked items are picked up. A broker's trades go back the same way from the latest
fill, or to the start when there's none yet.

Each account's sync is recorded in `finance.sync_runs`. Raw payloads are committed before
they're applied, so a parser bug never loses data (see ingest/apply.py's APPLY_FAILED).
"""

import enum
import logging
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

import httpx
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from hubnisio.core.db import get_sessionmaker
from hubnisio.core.settings import get_settings
from hubnisio.finance.categorize.run import after_sync
from hubnisio.finance.ingest.apply import APPLY_FAILED, NORMALIZERS, apply_payloads
from hubnisio.finance.models import (
    Account,
    Connection,
    ConnectionStatus,
    Fill,
    ProviderAccount,
    ProviderName,
    ProviderPayload,
    SyncRun,
    SyncStatus,
    Transaction,
    TransactionStatus,
)
from hubnisio.finance.providers.base import Fetched, Provider
from hubnisio.finance.providers.enable_banking.client import EnableBankingClient
from hubnisio.finance.providers.enable_banking.errors import (
    EnableBankingError,
    PaginationError,
    RateLimited,
    SessionEnded,
    WrongPeriod,
)
from hubnisio.finance.providers.trading212 import errors as t212
from hubnisio.finance.providers.trading212.client import Trading212Client

logger = logging.getLogger(__name__)

OVERLAP = timedelta(days=14)


class SyncTrigger(enum.StrEnum):
    INITIAL = "initial"  # right after linking: fetch the longest history
    SCHEDULED = "scheduled"
    USER = "user"  # "Sync now"


class AccountResult(enum.Enum):
    SUCCEEDED = enum.auto()
    FAILED = enum.auto()
    RATE_LIMITED = enum.auto()
    SESSION_ENDED = enum.auto()


@dataclass
class SyncOutcome:
    provider: ProviderName | None = None
    succeeded: int = 0
    failed: int = 0
    rate_limited: bool = False
    session_ended: bool = False


def default_client(connection: Connection) -> Provider:
    settings = get_settings()
    match connection.provider:
        case ProviderName.ENABLE_BANKING:
            return EnableBankingClient.from_settings(settings)
        case ProviderName.TRADING212:
            if not connection.key_file:
                raise RuntimeError(f"Connection {connection.id} names no key file.")
            return Trading212Client(settings.trading212_keys_dir / connection.key_file)


async def active_connection_ids() -> list[uuid.UUID]:
    async with get_sessionmaker()() as session:
        return list(
            await session.scalars(
                select(Connection.id).where(Connection.status == ConnectionStatus.ACTIVE)
            )
        )


async def sync_connection(
    connection_id: uuid.UUID,
    *,
    trigger: SyncTrigger,
    psu_headers: Mapping[str, str] | None = None,
    client_factory: Callable[[Connection], Provider] = default_client,
) -> SyncOutcome:
    sessionmaker = get_sessionmaker()
    started_at = datetime.now(UTC)
    async with sessionmaker() as session, session.begin():
        connection = await session.get(Connection, connection_id)
        if connection is None or connection.status is not ConnectionStatus.ACTIVE:
            return SyncOutcome()
        provider = connection.provider
        if connection.valid_until is not None and connection.valid_until <= datetime.now(UTC):
            connection.status = ConnectionStatus.EXPIRED
            return SyncOutcome(provider, session_ended=True)
        household_id = connection.household_id
        links = (
            await session.execute(
                select(ProviderAccount.provider_account_uid, ProviderAccount.account_id)
                .join(Account, Account.id == ProviderAccount.account_id)
                # A hidden account is retired: the bank isn't asked for it any more.
                .where(ProviderAccount.connection_id == connection_id, Account.hidden_at.is_(None))
                .order_by(ProviderAccount.account_id)
            )
        ).all()

    outcome = SyncOutcome(provider)
    async with client_factory(connection) as client:
        for uid, account_id in links:
            result = await _sync_account(
                client,
                connection_id=connection_id,
                household_id=household_id,
                provider=provider,
                account_id=account_id,
                account_uid=uid,
                trigger=trigger,
                psu_headers=psu_headers,
            )
            match result:
                case AccountResult.SUCCEEDED:
                    outcome.succeeded += 1
                case AccountResult.FAILED:
                    outcome.failed += 1
                case AccountResult.RATE_LIMITED:
                    outcome.failed += 1
                    outcome.rate_limited = True
                case AccountResult.SESSION_ENDED:
                    outcome.failed += 1
                    outcome.session_ended = True
                    await _expire_connection(connection_id)
                    break

    if outcome.succeeded:
        async with sessionmaker() as session, session.begin():
            connection = await session.get(Connection, connection_id)
            if connection is not None:
                connection.last_synced_at = datetime.now(UTC)
        await _refresh_user_layer(household_id, started_at, initial=trigger is SyncTrigger.INITIAL)
    logger.info(
        "Synced connection %s: %d accounts succeeded, %d failed.",
        connection_id,
        outcome.succeeded,
        outcome.failed,
    )
    return outcome


async def _sync_account(
    client: Provider,
    *,
    connection_id: uuid.UUID,
    household_id: uuid.UUID,
    provider: ProviderName,
    account_id: uuid.UUID,
    account_uid: str,
    trigger: SyncTrigger,
    psu_headers: Mapping[str, str] | None,
) -> AccountResult:
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session, session.begin():
        since = trades_since = None
        if trigger is not SyncTrigger.INITIAL:
            since = await _since(session, account_id)
            if NORMALIZERS[provider].fills:  # only a broker has trades
                trades_since = await _trades_since(session, account_id)
        run = SyncRun(
            household_id=household_id,
            connection_id=connection_id,
            account_id=account_id,
            trigger=trigger,
            strategy="longest" if since is None else "default",
            date_from=since,
            status=SyncStatus.RUNNING,
            started_at=datetime.now(UTC),
        )
        session.add(run)
    run_id = run.id  # committed, so the run shows as running while we fetch

    fetched: list[tuple[Fetched[Any], datetime]] = []
    error: Exception | None = None
    strategy = run.strategy
    try:
        try:
            async for item in client.fetch(
                account_uid, since, psu_headers, trades_since=trades_since
            ):
                fetched.append((item, datetime.now(UTC)))
        except WrongPeriod:
            if since is None:
                raise
            # The bank no longer has transactions that far back: take what it has.
            strategy = "longest"
            async for item in client.fetch(account_uid, None, psu_headers):
                fetched.append((item, datetime.now(UTC)))
    except (
        EnableBankingError,
        PaginationError,
        t212.Trading212Error,
        httpx.HTTPError,
        ValidationError,
    ) as exc:
        error = exc
    except Exception as exc:
        logger.exception("Unexpected error syncing account %s.", account_id)
        error = exc

    async with sessionmaker() as session, session.begin():
        payloads = [
            ProviderPayload(
                household_id=household_id,
                connection_id=connection_id,
                account_id=account_id,
                sync_run_id=run_id,
                kind=item.kind,
                request=item.request,
                response=item.raw,
                fetched_at=fetched_at,
            )
            for item, fetched_at in fetched
        ]
        session.add_all(payloads)
        run = await session.get_one(SyncRun, run_id)
        run.strategy = strategy
        if error is not None:
            run.status = SyncStatus.FAILED
            run.error_code = _error_code(error)
            run.finished_at = datetime.now(UTC)

    if error is not None:
        logger.warning("Sync of account %s failed: %s.", account_id, _error_code(error))
        if isinstance(error, SessionEnded | t212.KeyRejected):
            return AccountResult.SESSION_ENDED
        if isinstance(error, RateLimited | t212.RateLimited):
            return AccountResult.RATE_LIMITED
        return AccountResult.FAILED

    try:
        async with sessionmaker() as session, session.begin():
            stored = await apply_payloads(
                session,
                provider=provider,
                household_id=household_id,
                account_id=account_id,
                sync_run_id=run_id,
                payloads=payloads,
            )
            run = await session.get_one(SyncRun, run_id)
            run.status = SyncStatus.SUCCEEDED
            run.transactions_seen = stored.seen
            run.transactions_added = stored.added
            run.finished_at = datetime.now(UTC)
    except Exception:
        logger.exception("Applying payloads for account %s failed.", account_id)
        async with sessionmaker() as session, session.begin():
            run = await session.get_one(SyncRun, run_id)
            run.status = SyncStatus.FAILED
            run.error_code = APPLY_FAILED
            run.finished_at = datetime.now(UTC)
        return AccountResult.FAILED
    return AccountResult.SUCCEEDED


async def _refresh_user_layer(
    household_id: uuid.UUID, started_at: datetime, *, initial: bool
) -> None:
    """Pair transfers and categorize what this sync touched. A failure here is logged, not
    raised: the bank data is stored, and the next sync or "Run rules now" retries."""
    try:
        async with get_sessionmaker()() as session, session.begin():
            result = await after_sync(session, household_id, started_at, initial=initial)
        logger.info(
            "Categorized %d transactions (%d with a category), %d new counterparties.",
            result.processed,
            result.categorized,
            result.counterparties_created,
        )
    except Exception:
        logger.exception("Categorizing after the sync failed.")


async def _since(session: AsyncSession, account_id: uuid.UUID) -> date | None:
    """Two weeks before the latest booked transaction; None (the longest history) if none."""
    latest = await session.scalar(
        select(func.max(Transaction.occurred_on)).where(
            Transaction.account_id == account_id,
            Transaction.status == TransactionStatus.BOOKED,
        )
    )
    return latest - OVERLAP if latest is not None else None


async def _trades_since(session: AsyncSession, account_id: uuid.UUID) -> date | None:
    """Two weeks before the latest fill's day; None (every trade) if none."""
    latest = await session.scalar(
        select(func.max(Fill.filled_at)).where(Fill.account_id == account_id)
    )
    return latest.astimezone(UTC).date() - OVERLAP if latest is not None else None


async def _expire_connection(connection_id: uuid.UUID) -> None:
    """The bank ended the session (expired, closed or revoked), or Trading 212 rejected the
    key: the user has to link again."""
    async with get_sessionmaker()() as session, session.begin():
        connection = await session.get(Connection, connection_id)
        if connection is not None:
            connection.status = ConnectionStatus.EXPIRED


def _error_code(error: Exception) -> str:
    match error:
        case t212.Trading212Error(code=code):
            return code
        case EnableBankingError(code=str(code)):
            return code
        case EnableBankingError(status=status):
            return f"HTTP_{status}"
        case PaginationError():
            return "PAGINATION"
        case httpx.HTTPError():
            return "NETWORK"
        case ValidationError():
            return "UNEXPECTED_RESPONSE"
        case _:
            return "UNEXPECTED"
