"""Alembic environment. Migrations run over a synchronous psycopg connection."""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, pool

from hubnisio.core import models as core_models
from hubnisio.core.db import MODULE_SCHEMAS, Base
from hubnisio.core.settings import get_settings
from hubnisio.finance import models as finance_models

config = context.config
if config.config_file_name is not None and config.attributes.get("configure_logger", True):
    fileConfig(config.config_file_name)

# Importing a module's models registers its tables on Base.metadata.
_ = (core_models, finance_models)
target_metadata = Base.metadata


def include_name(name: str | None, type_: str, parent_names: object) -> bool:
    """Only compare the modules' own schemas; the job queue manages its own."""
    if type_ == "schema":
        return name in MODULE_SCHEMAS
    return True


def database_url() -> str:
    return config.get_main_option("sqlalchemy.url") or get_settings().sqlalchemy_url


def run_migrations_offline() -> None:
    context.configure(
        url=database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        include_schemas=True,
        include_name=include_name,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_engine(database_url(), poolclass=pool.NullPool)
    with engine.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            include_schemas=True,
            include_name=include_name,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
