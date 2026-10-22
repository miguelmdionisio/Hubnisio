"""Admin commands: `python -m hubnisio.cli <command> --help`."""

import argparse
import asyncio
import sys
import uuid
from datetime import date

from sqlalchemy import select

from hubnisio.core.db import get_engine, get_sessionmaker
from hubnisio.core.models import Household, HouseholdMember, HouseholdRole, User
from hubnisio.finance.categorize.run import run_all
from hubnisio.finance.defaults import seed_household
from hubnisio.finance.fx.sources import FxClient
from hubnisio.finance.fx.store import earliest_transaction_day, rate_summary, refresh_rates
from hubnisio.finance.ingest.renormalize import renormalize_account
from hubnisio.finance.models import Account


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


async def _run(args: argparse.Namespace) -> int:
    try:
        match args.command:
            case "bootstrap":
                return await bootstrap(args.email, args.name, args.household)
            case "renormalize":
                return await renormalize(args.account)
            case "recategorize":
                return await recategorize(args.household)
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
