"""Admin commands: `python -m hubnisio.cli <command> --help`."""

import argparse
import asyncio
import sys

from sqlalchemy import select

from hubnisio.core.db import get_engine, get_sessionmaker
from hubnisio.core.models import Household, HouseholdMember, HouseholdRole, User


async def bootstrap(email: str, name: str, household_name: str) -> int:
    """Create the first user, their household and their owner membership."""
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
    print(f"Created {email}, owner of household {household_name!r}.")
    return 0


async def _run(args: argparse.Namespace) -> int:
    try:
        match args.command:
            case "bootstrap":
                return await bootstrap(args.email, args.name, args.household)
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

    args = parser.parse_args(argv)
    # psycopg's async mode can't run on the Proactor event loop that Windows uses by default.
    return asyncio.run(_run(args), loop_factory=asyncio.SelectorEventLoop)


if __name__ == "__main__":
    sys.exit(main())
