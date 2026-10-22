"""Install the Procrastinate job queue in its own schema.

The SQL is Procrastinate's schema, frozen at the pinned version. When upgrading Procrastinate,
add a new migration that applies its SQL migrations for the versions in between (they ship in
the package under procrastinate/sql/migrations), with the search_path set as below.

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-22
"""

from collections.abc import Sequence
from pathlib import Path

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA_SQL = Path(__file__).parent.parent / "sql" / "procrastinate-3.10.0.sql"


def upgrade() -> None:
    op.execute("CREATE SCHEMA procrastinate")
    # The file holds many statements; psycopg runs those only as a parameterless script on the
    # raw connection (SQLAlchemy's execute would treat its colons as bind parameters).
    driver = op.get_bind().connection.driver_connection
    if driver is None:
        raise RuntimeError("Migration 0002 needs a live database connection (no offline mode).")
    driver.execute("SET LOCAL search_path TO procrastinate")
    driver.execute(SCHEMA_SQL.read_text(encoding="utf-8"))
    driver.execute("RESET search_path")


def downgrade() -> None:
    op.execute("DROP SCHEMA procrastinate CASCADE")
