"""Shared fixtures: a throwaway Postgres in Docker, migrated to head.

Database tests are skipped when Docker isn't reachable, unless REQUIRE_DOCKER=1 (set in CI).
"""

import asyncio
import os
import uuid
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest
from alembic.config import Config
from analytics_data import Data, Login, email_of, populate
from households import Home, make_home
from sqlalchemy import delete

from hubnisio.cli import ai_login, ai_role_name
from hubnisio.core.db import get_engine, get_sessionmaker
from hubnisio.core.models import Household
from hubnisio.core.settings import get_settings
from hubnisio.finance.models import FxRate

ALEMBIC_INI = Path(__file__).parents[1] / "alembic.ini"


@pytest.fixture
def anyio_backend() -> tuple[str, dict[str, object]]:
    # psycopg's async mode can't run on the Proactor event loop that Windows uses by default.
    return "asyncio", {"loop_factory": asyncio.SelectorEventLoop}


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    from testcontainers.community.postgres import PostgresContainer

    try:
        container = PostgresContainer("postgres:18-alpine", driver=None)
        container.start()
    except Exception as exc:
        if os.environ.get("REQUIRE_DOCKER") == "1":
            raise
        pytest.skip(f"Docker is not reachable: {exc}")
    try:
        yield container.get_connection_url()
    finally:
        container.stop()


@pytest.fixture
def alembic_config(database_url: str) -> Config:
    config = Config(ALEMBIC_INI)
    config.set_main_option(
        "sqlalchemy.url", database_url.replace("postgresql://", "postgresql+psycopg://", 1)
    )
    config.attributes["configure_logger"] = False
    return config


@pytest.fixture
def migrated_database(alembic_config: Config, database_url: str) -> Iterator[str]:
    """A database at the latest migration, with the app pointed at it."""
    from alembic import command

    command.upgrade(alembic_config, "head")
    previous = os.environ.get("HUBNISIO_DATABASE_URL")
    os.environ["HUBNISIO_DATABASE_URL"] = database_url
    for cached in (get_settings, get_engine, get_sessionmaker):
        cached.cache_clear()
    yield database_url
    for cached in (get_settings, get_engine, get_sessionmaker):
        cached.cache_clear()
    if previous is None:
        del os.environ["HUBNISIO_DATABASE_URL"]
    else:
        os.environ["HUBNISIO_DATABASE_URL"] = previous


@pytest.fixture
async def home(migrated_database: str) -> Home:
    """A household with two members and three accounts (see households.py)."""
    return await make_home()


@pytest.fixture
async def logins(
    home: Home, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[dict[uuid.UUID, Login]]:
    """An AI login for each member, made by the CLI command (ADR-0006)."""
    monkeypatch.setenv("HUBNISIO_AI_SECRETS_DIR", str(tmp_path))
    get_settings.cache_clear()
    result: dict[uuid.UUID, Login] = {}
    for principal in (home.owner, home.member):
        assert await ai_login(await email_of(principal), revoke=False) == 0
        role = ai_role_name(principal.user_id)
        result[principal.user_id] = Login(role, (tmp_path / role).read_text().strip())
    yield result
    get_settings.cache_clear()


@pytest.fixture
async def data(home: Home) -> AsyncIterator[Data]:
    """The cases in analytics_data.py. Removed afterwards: the FX tests look at every currency
    in use, and these are fake."""
    yield await populate(home)
    async with get_sessionmaker()() as session, session.begin():
        await session.execute(delete(Household).where(Household.id == home.owner.household_id))
        await session.execute(delete(FxRate).where(FxRate.quote_currency == "XTQ"))
