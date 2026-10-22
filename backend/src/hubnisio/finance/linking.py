"""Linking a bank through Enable Banking (ADR-0003).

1. `start_connection`: create a pending connection and ask Enable Banking for the bank's
   authorization URL. The browser goes there; the user approves in the bank's app.
2. The bank redirects the browser back with `code` and `state`.
3. `complete_connection`: turn the code into a session, then match each account it gives
   access to against the household's accounts, so a joint account is stored once (ADR-0005).
"""

import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from hubnisio.core.auth import Principal
from hubnisio.core.crypto import SecretBox
from hubnisio.finance.models import (
    Account,
    AccountOwner,
    Connection,
    ConnectionStatus,
    ProviderAccount,
    ProviderName,
    ProviderPayload,
)
from hubnisio.finance.providers.enable_banking.client import EnableBankingClient
from hubnisio.finance.providers.enable_banking.errors import AlreadyAuthorized
from hubnisio.finance.providers.enable_banking.schemas import SessionAccount

# Most banks allow 180 days of consent; ask for the bank's maximum, capped at that.
MAX_CONSENT = timedelta(days=180)
DEFAULT_CONSENT = timedelta(days=90)
# Enable Banking rejects a valid_until past the bank's maximum, measured on its own clock.
CONSENT_MARGIN = timedelta(minutes=10)


class UnknownBank(Exception):
    pass


class UnknownAuthorization(Exception):
    """No pending connection matches this state for this user."""


class AuthorizationLost(Exception):
    """The code was already used, but the session never reached us; link again."""


def hash_state(state: str) -> str:
    return hashlib.sha256(state.encode()).hexdigest()


def session_id_context(connection_id: uuid.UUID) -> str:
    """Associated data that binds an encrypted session ID to its connection row."""
    return f"finance.connections:{connection_id}"


async def start_connection(
    session: AsyncSession,
    client: EnableBankingClient,
    principal: Principal,
    *,
    institution_name: str,
    country: str,
    redirect_url: str,
) -> str:
    """Return the URL to send the browser to. The caller commits."""
    banks = await client.get_aspsps(country)
    bank = next((bank for bank in banks if bank.name == institution_name), None)
    if bank is None:
        raise UnknownBank(institution_name)
    maximum = (
        timedelta(seconds=bank.maximum_consent_validity)
        if bank.maximum_consent_validity
        else DEFAULT_CONSENT
    )
    valid_until = datetime.now(UTC) + min(maximum, MAX_CONSENT) - CONSENT_MARGIN

    state = secrets.token_urlsafe(32)
    connection = Connection(
        household_id=principal.household_id,
        user_id=principal.user_id,
        provider=ProviderName.ENABLE_BANKING,
        institution_name=bank.name,
        institution_country=bank.country,
        status=ConnectionStatus.PENDING,
        auth_state_hash=hash_state(state),
        valid_until=valid_until,
    )
    session.add(connection)
    await session.flush()
    started = await client.start_authorization(
        aspsp_name=bank.name,
        country=bank.country,
        redirect_url=redirect_url,
        state=state,
        valid_until=valid_until,
    )
    return started.url


async def complete_connection(
    session: AsyncSession,
    client: EnableBankingClient,
    box: SecretBox,
    principal: Principal,
    *,
    code: str,
    state: str,
) -> tuple[Connection, bool]:
    """Finish linking. Returns the connection, and whether it was completed just now (False
    when the callback was simply loaded again). The caller commits.

    The row stays locked until the caller commits, so two simultaneous callbacks (a double
    load) take turns: the second sees the connection already active, instead of redeeming the
    single-use code a second time and failing."""
    connection = await session.scalar(
        select(Connection)
        .where(
            Connection.auth_state_hash == hash_state(state),
            Connection.user_id == principal.user_id,
            Connection.household_id == principal.household_id,
        )
        .with_for_update()
    )
    if connection is None:
        raise UnknownAuthorization
    if connection.status is not ConnectionStatus.PENDING:
        return connection, False

    try:
        fetched = await client.create_session(code)
    except AlreadyAuthorized:
        connection.status = ConnectionStatus.FAILED
        raise AuthorizationLost from None
    bank_session = fetched.data

    connection.session_id_encrypted = box.encrypt(
        bank_session.session_id, session_id_context(connection.id)
    )
    connection.valid_until = bank_session.access.valid_until
    connection.status = ConnectionStatus.ACTIVE
    session.add(
        ProviderPayload(
            household_id=connection.household_id,
            connection_id=connection.id,
            kind=fetched.kind,
            request=fetched.request,
            response=fetched.raw,
            fetched_at=datetime.now(UTC),
        )
    )

    linked: set[uuid.UUID] = set()
    for bank_account in bank_session.accounts:
        account = await _match_account(
            session, connection.household_id, bank_account, bank_session.aspsp.name
        )
        linked.add(account.id)
        await session.execute(
            insert(AccountOwner)
            .values(account_id=account.id, user_id=principal.user_id)
            .on_conflict_do_nothing()
        )
        await session.execute(
            insert(ProviderAccount)
            .values(
                connection_id=connection.id,
                provider_account_uid=bank_account.uid,
                account_id=account.id,
            )
            .on_conflict_do_nothing()
        )
    await _retire_replaced(session, principal, connection.id, linked)
    return connection, True


async def _retire_replaced(
    session: AsyncSession,
    principal: Principal,
    connection_id: uuid.UUID,
    linked: set[uuid.UUID],
) -> None:
    """A re-link replaces the user's expired connections whose accounts it now covers."""
    expired = await session.scalars(
        select(Connection).where(
            Connection.user_id == principal.user_id,
            Connection.household_id == principal.household_id,
            Connection.status == ConnectionStatus.EXPIRED,
            Connection.id != connection_id,
        )
    )
    for old in expired:
        covered = set(
            await session.scalars(
                select(ProviderAccount.account_id).where(ProviderAccount.connection_id == old.id)
            )
        )
        if covered and covered <= linked:
            old.status = ConnectionStatus.REVOKED
            old.session_id_encrypted = None


async def _match_account(
    session: AsyncSession,
    household_id: uuid.UUID,
    bank_account: SessionAccount,
    institution_name: str,
) -> Account:
    """The household's account for this bank account: matched on identification_hash
    (stable across sessions), then IBAN; created if neither matches."""
    iban = _iban(bank_account)
    if bank_account.identification_hash:
        found = await session.scalar(
            select(Account).where(
                Account.household_id == household_id,
                Account.identification_hash == bank_account.identification_hash,
            )
        )
        if found is not None:
            return found
    if iban:
        found = await session.scalar(
            select(Account).where(Account.household_id == household_id, Account.iban == iban)
        )
        if found is not None:
            found.identification_hash = (
                found.identification_hash or bank_account.identification_hash
            )
            return found

    account = Account(
        household_id=household_id,
        identification_hash=bank_account.identification_hash,
        iban=iban,
        institution_name=institution_name,
        holder_name=bank_account.name,
        product=bank_account.product,
        currency=bank_account.currency,
        cash_account_type=bank_account.cash_account_type,
    )
    session.add(account)
    await session.flush()
    return account


def _iban(bank_account: SessionAccount) -> str | None:
    identification = bank_account.account_id
    if identification is None or not identification.iban:
        return None
    return identification.iban.replace(" ", "").upper()
