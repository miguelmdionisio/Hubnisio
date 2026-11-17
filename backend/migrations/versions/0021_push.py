"""Push alerts (M9 P6): each member's devices subscribed for Web Push, which kinds of alert they
want, and the alerts already sent, so each goes out once.

Revision ID: 0021
Revises: 0020
Create Date: 2026-11-17
"""

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0021"
down_revision: str | None = "0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "core"

# Created once here; the columns only refer to it.
ALERT_KIND = postgresql.ENUM(
    "bill_due",
    "budget_over",
    "sync_failing",
    "key_lapsing",
    name="alert_kind",
    schema=SCHEMA,
    create_type=False,
)


def _user(table: str) -> list[Any]:
    return [
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"], ["core.users.id"], name=f"fk_{table}_user_id_users", ondelete="CASCADE"
        ),
    ]


def upgrade() -> None:
    ALERT_KIND.create(op.get_bind())
    op.create_table(
        "push_subscriptions",
        sa.Column("id", sa.Uuid(), nullable=False),
        *_user("push_subscriptions"),
        sa.Column("endpoint", sa.Text(), nullable=False),
        sa.Column("p256dh", sa.String(length=200), nullable=False),
        sa.Column("auth", sa.String(length=100), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("last_sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_push_subscriptions"),
        sa.UniqueConstraint("endpoint", name="uq_push_subscriptions_endpoint"),
        schema=SCHEMA,
    )
    op.create_table(
        "alert_preferences",
        *_user("alert_preferences"),
        sa.Column("kind", ALERT_KIND, nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint("user_id", "kind", name="pk_alert_preferences"),
        schema=SCHEMA,
    )
    op.create_table(
        "alerts_sent",
        *_user("alerts_sent"),
        sa.Column("key", sa.String(length=200), nullable=False),
        sa.Column("kind", ALERT_KIND, nullable=False),
        sa.Column(
            "sent_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.PrimaryKeyConstraint("user_id", "key", name="pk_alerts_sent"),
        schema=SCHEMA,
    )


def downgrade() -> None:
    for table in ("alerts_sent", "alert_preferences", "push_subscriptions"):
        op.drop_table(table, schema=SCHEMA)
    ALERT_KIND.drop(op.get_bind())
