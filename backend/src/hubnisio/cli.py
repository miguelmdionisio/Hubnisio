"""Admin commands: `python -m hubnisio.cli <command> --help`."""

import argparse
import asyncio
import os
import re
import secrets
import sys
import uuid
from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import LiteralString

import httpx
import psycopg
from psycopg import sql
from psycopg.rows import TupleRow
from pydantic import ValidationError
from sqlalchemy import exists, func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession

from hubnisio.core.auth import Principal
from hubnisio.core.db import get_engine, get_sessionmaker
from hubnisio.core.models import AiLogin, Household, HouseholdMember, HouseholdRole, User
from hubnisio.core.settings import get_settings
from hubnisio.finance import tasks
from hubnisio.finance.categorize.run import run_all
from hubnisio.finance.defaults import seed_household
from hubnisio.finance.fx.sources import FxClient
from hubnisio.finance.fx.store import earliest_transaction_day, rate_summary, refresh_rates
from hubnisio.finance.ingest.renormalize import renormalize_account
from hubnisio.finance.linking import link_trading212
from hubnisio.finance.models import Account, RecurringSeries
from hubnisio.finance.providers.trading212.client import Trading212Client
from hubnisio.finance.providers.trading212.errors import (
    KeyFileError,
    KeyRejected,
    MissingPermission,
    Trading212Error,
)
from hubnisio.finance.recurring.run import detect_recurring
from hubnisio.finance.sync import SyncTrigger
from hubnisio.jobs import app as job_app


async def bootstrap(email: str, name: str, household_name: str) -> int:
    """Create the first user, their household (with default categories and rules) and their
    owner membership."""
    email = email.strip().lower()
    async with get_sessionmaker()() as session, session.begin():
        if await session.scalar(select(User.id).where(User.email == email)) is not None:
            print(f"A user with email {email} already exists.", file=sys.stderr)
            return 1
        user = User(email=email, display_name=name)
        household = Household(name=household_name)
        session.add_all([user, household])
        await session.flush()
        session.add(
            HouseholdMember(household_id=household.id, user_id=user.id, role=HouseholdRole.OWNER)
        )
        await seed_household(session, household.id)
    print(f"Created {email}, owner of household {household_name!r}.")
    return 0


async def renormalize(account_id: uuid.UUID | None) -> int:
    """Rebuild transactions and balances from stored payloads, one account per transaction."""
    sessionmaker = get_sessionmaker()
    if account_id is None:
        async with sessionmaker() as session:
            account_ids = list(await session.scalars(select(Account.id).order_by(Account.id)))
    else:
        account_ids = [account_id]
    for current in account_ids:
        async with sessionmaker() as session, session.begin():
            result = await renormalize_account(session, current)
        print(
            f"Account {current}: replayed {result.syncs} syncs, {result.transactions} "
            f"transactions, {result.removed} removed."
        )
    return 0


async def recategorize(household_id: uuid.UUID | None) -> int:
    """Pair transfers and categorize every transaction again, one household per transaction."""
    sessionmaker = get_sessionmaker()
    if household_id is None:
        async with sessionmaker() as session:
            household_ids = list(await session.scalars(select(Household.id).order_by(Household.id)))
    else:
        household_ids = [household_id]
    for current in household_ids:
        async with sessionmaker() as session, session.begin():
            result = await run_all(session, current)
        print(
            f"Household {current}: {result.processed} transactions, {result.categorized} with a "
            f"category, {result.counterparties_created} new counterparties."
        )
    return 0


async def detect_recurring_series(household_id: uuid.UUID | None) -> int:
    """Re-detect recurring series, then count them by cadence, kind, status and review."""
    sessionmaker = get_sessionmaker()
    if household_id is None:
        async with sessionmaker() as session:
            household_ids = list(await session.scalars(select(Household.id).order_by(Household.id)))
    else:
        household_ids = [household_id]
    for current in household_ids:
        async with sessionmaker() as session, session.begin():
            result = await detect_recurring(session, current, date.today())
            counts = await session.execute(
                select(
                    RecurringSeries.cadence,
                    RecurringSeries.kind,
                    RecurringSeries.status,
                    RecurringSeries.review,
                    func.count(),
                )
                .where(RecurringSeries.household_id == current)
                .group_by(
                    RecurringSeries.cadence,
                    RecurringSeries.kind,
                    RecurringSeries.status,
                    RecurringSeries.review,
                )
                .order_by(RecurringSeries.cadence, RecurringSeries.kind, RecurringSeries.status)
            )
            print(f"Household {current}: {result.series} series detected, {result.created} new.")
            for cadence, kind, status, review, count in counts:
                print(f"  {cadence} {kind}, {status}, {review}: {count}")
    return 0


async def fx_backfill(since: date | None) -> int:
    """Fetch the exchange rates the hub's currencies are missing since `since` (default: the
    earliest transaction), then show what is stored."""
    async with FxClient() as client, get_sessionmaker()() as session, session.begin():
        if since is None:
            since = await earliest_transaction_day(session)
        result = await refresh_rates(session, client, since=since)
        stored = await rate_summary(session)
    print(f"Fetched rates since {since or 'the first day each currency appears'}.")
    for (currency, source), rows in sorted(result.written.items()):
        print(f"{currency} ({source}): {rows} rows written.")
    if not result.written:
        print("Nothing new to write.")
    for item in stored:
        print(
            f"Stored {item.currency} ({item.source}): {item.rows} rows, "
            f"{item.first} to {item.last}."
        )
    for currency, error in sorted(result.failed.items()):
        print(f"{currency} failed: {error}", file=sys.stderr)
    return 1 if result.failed else 0


# A file in the keys folder: no path, no hidden files.
KEY_FILE_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,99}")


async def t212_link(
    email: str,
    key_file: str,
    *,
    client_factory: Callable[[Path], Trading212Client] = Trading212Client,
) -> int:
    """Link the Trading 212 account a key file reads for a member (ADR-0008), then queue its
    first sync. Prints no key, value or account number."""
    email = email.strip().lower()
    if not KEY_FILE_NAME.fullmatch(key_file):
        print("--key-file takes a file's name in the keys folder, e.g. invest.", file=sys.stderr)
        return 1
    path = get_settings().trading212_keys_dir / key_file
    async with get_sessionmaker()() as session:
        member = (
            await session.execute(
                select(HouseholdMember.user_id, HouseholdMember.household_id, HouseholdMember.role)
                .join(User, User.id == HouseholdMember.user_id)
                .where(User.email == email)
            )
        ).one_or_none()
    if member is None:
        print(f"No household member has the email {email}.", file=sys.stderr)
        return 1
    principal = Principal(member.user_id, member.household_id, member.role)

    try:
        async with client_factory(path) as client:
            summary = await client.get_summary()
    except KeyFileError as exc:
        print(f"{exc.message} See the README for the format.", file=sys.stderr)
        return 1
    except KeyRejected:
        print(
            "Trading 212 rejected the key. Check it, and the IP addresses it's limited to.",
            file=sys.stderr,
        )
        return 1
    except MissingPermission:
        print("The key lacks the Account data permission.", file=sys.stderr)
        return 1
    except (Trading212Error, httpx.HTTPError, ValidationError) as exc:
        print(f"Couldn't read the account summary: {exc}.", file=sys.stderr)
        return 1

    async with get_sessionmaker()() as session, session.begin():
        connection, account = await link_trading212(
            session, principal, key_file=key_file, summary=summary
        )
    async with job_app.open_async():
        await tasks.defer_sync(connection.id, trigger=SyncTrigger.INITIAL)
    print(
        f"Linked Trading 212 for {email}: account {account.id}. Its first sync is queued; "
        "the worker fetches the whole history."
    )
    return 0


AI_GROUP = "hub_ai"
# Set on every AI login: read-only transactions and short statements by default. The grants
# are what keep it out of everything but `analytics`; these only make the defaults safe.
AI_ROLE_SETTINGS: dict[LiteralString, str] = {
    "default_transaction_read_only": "on",
    "statement_timeout": "30s",
    "search_path": "analytics",
}


def ai_role_name(user_id: uuid.UUID) -> str:
    """A UUIDv7 starts with its timestamp, so the name takes the random end."""
    return f"{AI_GROUP}_{user_id.hex[-12:]}"


async def ai_login(email: str, *, revoke: bool) -> int:
    """Create a member's Postgres login for AI access (ADR-0006), or drop it. The login's
    connection string goes to a file in the AI secrets folder; its password is never printed."""
    email = email.strip().lower()
    settings = get_settings()
    async with get_sessionmaker()() as session, session.begin():
        user_id = await session.scalar(
            select(User.id).where(
                User.email == email, exists().where(HouseholdMember.user_id == User.id)
            )
        )
        if user_id is None:
            print(f"No household member has the email {email}.", file=sys.stderr)
            return 1
        role = ai_role_name(user_id)
        path = settings.ai_secrets_dir / role
        login = await session.get(AiLogin, role)
        driver = await _driver_connection(session)

        if revoke:
            if login is None:
                print(f"{email} has no AI login.", file=sys.stderr)
                return 1
            # Without its mapping the views show the login nothing, open sessions included.
            await session.delete(login)
            await session.flush()
            await session.execute(
                text("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE usename = :r"),
                {"r": role},
            )
            await driver.execute(sql.SQL("DROP ROLE IF EXISTS {}").format(sql.Identifier(role)))
            path.unlink(missing_ok=True)
            print(f"Revoked the AI login {role} of {email}.")
            return 0

        if login is not None:
            print(f"{email} already has the AI login {role}.", file=sys.stderr)
            return 1
        if await session.scalar(text("SELECT 1 FROM pg_roles WHERE rolname = :r"), {"r": role}):
            print(f"A role {role} exists but isn't an AI login: drop it first.", file=sys.stderr)
            return 1
        password = secrets.token_urlsafe(32)
        # Hashed here, so the password never reaches the server, or its logs, in the clear.
        verifier = driver.pgconn.encrypt_password(
            password.encode(), role.encode(), b"scram-sha-256"
        )
        await driver.execute(
            sql.SQL("CREATE ROLE {} LOGIN PASSWORD {} IN ROLE {}").format(
                sql.Identifier(role), sql.Literal(verifier.decode()), sql.Identifier(AI_GROUP)
            )
        )
        for name, value in AI_ROLE_SETTINGS.items():
            await driver.execute(
                sql.SQL("ALTER ROLE {} SET {} = {}").format(
                    sql.Identifier(role), sql.SQL(name), sql.Literal(value)
                )
            )
        session.add(AiLogin(role_name=role, user_id=user_id))
        await session.flush()
        url = make_url(settings.database_url).set(username=role, password=password)
        _write_secret(path, url.render_as_string(hide_password=False))
    print(f"Created the AI login {role} for {email}. Its connection string is in {path}.")
    return 0


async def _driver_connection(session: AsyncSession) -> psycopg.AsyncConnection[TupleRow]:
    """The session's psycopg connection, in its transaction: for statements that take
    identifiers and literals rather than parameters."""
    raw = await (await session.connection()).get_raw_connection()
    driver = raw.driver_connection
    if not isinstance(driver, psycopg.AsyncConnection):
        raise TypeError(f"Expected a psycopg connection, got {type(driver)}")
    return driver


def _write_secret(path: Path, content: str) -> None:
    """Readable by its owner only."""
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as file:
        file.write(content + "\n")


async def _run(args: argparse.Namespace) -> int:
    try:
        match args.command:
            case "bootstrap":
                return await bootstrap(args.email, args.name, args.household)
            case "ai-login":
                return await ai_login(args.email, revoke=args.revoke)
            case "t212-link":
                return await t212_link(args.email, args.key_file)
            case "renormalize":
                return await renormalize(args.account)
            case "recategorize":
                return await recategorize(args.household)
            case "detect-recurring":
                return await detect_recurring_series(args.household)
            case "fx-backfill":
                return await fx_backfill(args.since)
            case _:
                raise AssertionError(args.command)
    finally:
        # The engine is cached; release its connections before this event loop closes.
        await get_engine().dispose()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m hubnisio.cli")
    commands = parser.add_subparsers(dest="command", required=True)

    bootstrap_parser = commands.add_parser(
        "bootstrap", help="create the first user and their household"
    )
    bootstrap_parser.add_argument("--email", required=True)
    bootstrap_parser.add_argument("--name", required=True, help="display name")
    bootstrap_parser.add_argument("--household", default="Home", help="household name")

    ai_login_parser = commands.add_parser(
        "ai-login", help="create a member's Postgres login for AI access, or revoke it"
    )
    ai_login_parser.add_argument("--email", required=True)
    ai_login_parser.add_argument(
        "--revoke", action="store_true", help="drop the login and its connection string"
    )

    t212_parser = commands.add_parser(
        "t212-link",
        help="link a member's Trading 212 account from an API key file, and sync it",
    )
    t212_parser.add_argument("--email", required=True)
    t212_parser.add_argument(
        "--key-file",
        required=True,
        help="the key file's name in the Trading 212 keys folder (secrets/trading212)",
    )

    renormalize_parser = commands.add_parser(
        "renormalize", help="rebuild transactions and balances from stored provider payloads"
    )
    renormalize_parser.add_argument(
        "--account", type=uuid.UUID, help="one account ID (default: every account)"
    )

    recategorize_parser = commands.add_parser(
        "recategorize", help="pair transfers and run counterparties and rules on everything"
    )
    recategorize_parser.add_argument(
        "--household", type=uuid.UUID, help="one household ID (default: every household)"
    )

    recurring_parser = commands.add_parser(
        "detect-recurring", help="find recurring payments again and count them"
    )
    recurring_parser.add_argument(
        "--household", type=uuid.UUID, help="one household ID (default: every household)"
    )

    fx_backfill_parser = commands.add_parser(
        "fx-backfill", help="fetch the exchange rates into EUR that are missing"
    )
    fx_backfill_parser.add_argument(
        "--since",
        type=date.fromisoformat,
        metavar="YYYY-MM-DD",
        help="check from this day (default: the earliest transaction)",
    )

    args = parser.parse_args(argv)
    # psycopg's async mode can't run on the Proactor event loop that Windows uses by default.
    return asyncio.run(_run(args), loop_factory=asyncio.SelectorEventLoop)


if __name__ == "__main__":
    sys.exit(main())
