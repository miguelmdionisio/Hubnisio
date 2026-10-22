"""Shared fixtures: a throwaway Postgres in Docker, migrated to head.

Database tests are skipped when Docker isn't reachable, unless REQUIRE_DOCKER=1 (set in CI).
"""

import asyncio
import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic.config import Config

from hubnisio.core.db import get_engine, get_sessionmaker
from hubnisio.core.settings import get_settings

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
