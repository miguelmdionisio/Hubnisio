"""Admin commands: `python -m hubnisio.cli <command> --help`."""

import argparse
import asyncio
import sys
import uuid

from sqlalchemy import select

from hubnisio.core.db import get_engine, get_sessionmaker
from hubnisio.core.models import Household, HouseholdMember, HouseholdRole, User
from hubnisio.finance.defaults import seed_household
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


async def _run(args: argparse.Namespace) -> int:
    try:
        match args.command:
            case "bootstrap":
                return await bootstrap(args.email, args.name, args.household)
            case "renormalize":
                return await renormalize(args.account)
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

    args = parser.parse_args(argv)
    # psycopg's async mode can't run on the Proactor event loop that Windows uses by default.
    return asyncio.run(_run(args), loop_factory=asyncio.SelectorEventLoop)


if __name__ == "__main__":
    sys.exit(main())
