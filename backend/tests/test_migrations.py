from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, text

from hubnisio.core import models as core_models
from hubnisio.core.db import MODULE_SCHEMAS, Base
from hubnisio.finance import models as finance_models
from hubnisio.health import models as health_models


def _sync_url(database_url: str) -> str:
    return database_url.replace("postgresql://", "postgresql+psycopg://", 1)


def test_models_match_migrations(migrated_database: str) -> None:
    """Autogenerate finds nothing to do, so the migrations and the models agree."""
    _ = (core_models, finance_models, health_models)
    engine = create_engine(_sync_url(migrated_database))
    with engine.connect() as connection:
        context = MigrationContext.configure(
            connection,
            opts={
                "include_schemas": True,
                "include_name": lambda name, type_, _parents: (
                    type_ != "schema" or name in MODULE_SCHEMAS
                ),
            },
        )
        assert compare_metadata(context, Base.metadata) == []
    engine.dispose()


def test_migrations_downgrade_and_upgrade_cleanly(
    migrated_database: str, alembic_config: Config
) -> None:
    command.downgrade(alembic_config, "base")
    command.upgrade(alembic_config, "head")

    engine = create_engine(_sync_url(migrated_database))
    with engine.connect() as connection:
        schemas = set(
            connection.execute(
                text("SELECT schema_name FROM information_schema.schemata")
            ).scalars()
        )
    engine.dispose()
    assert {"core", "finance", "health", "procrastinate"} <= schemas
