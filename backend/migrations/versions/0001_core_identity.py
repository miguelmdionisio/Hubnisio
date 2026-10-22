"""Create the module schemas and the household identity tables (ADR-0005).

Revision ID: 0001
Revises:
Create Date: 2026-10-22
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA core")
    op.execute("CREATE SCHEMA finance")

    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("display_name", sa.String(100), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_users"),
        sa.UniqueConstraint("email", name="uq_users_email"),
        schema="core",
    )
    op.create_table(
        "households",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_households"),
        schema="core",
    )
    op.create_table(
        "household_members",
        sa.Column("household_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column(
            "role",
            postgresql.ENUM("owner", "member", name="household_role", schema="core"),
            nullable=False,
        ),
        sa.Column(
            "joined_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["household_id"],
            ["core.households.id"],
            name="fk_household_members_household_id_households",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["core.users.id"],
            name="fk_household_members_user_id_users",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("household_id", "user_id", name="pk_household_members"),
        schema="core",
    )


def downgrade() -> None:
    op.drop_table("household_members", schema="core")
    op.drop_table("households", schema="core")
    op.drop_table("users", schema="core")
    op.execute("DROP TYPE core.household_role")
    op.execute("DROP SCHEMA finance")
    op.execute("DROP SCHEMA core")
