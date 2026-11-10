"""Activities (ADR-0009, slice H2): Garmin's summaries, each activity's original file, and what
its file gives: per-second streams, laps, pool lengths and the derived results.

Revision ID: 0019
Revises: 0018
Create Date: 2026-11-10
"""

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0019"
down_revision: str | None = "0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "health"
REAL = postgresql.REAL()
JSONB = postgresql.JSONB(astext_type=sa.Text())


def _user(table: str) -> list[Any]:
    return [
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"], ["core.users.id"], name=f"fk_{table}_user_id_users", ondelete="CASCADE"
        ),
    ]


def _activity(table: str) -> list[Any]:
    """user_id and activity_id, and their foreign key to the activity."""
    return [
        *_user(table),
        sa.Column("activity_id", sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id", "activity_id"],
            ["health.activities.user_id", "health.activities.activity_id"],
            name=f"fk_{table}_activity",
            ondelete="CASCADE",
        ),
    ]


def _col(name: str, type_: Any) -> sa.Column[Any]:
    return sa.Column(name, type_, nullable=True)


def _num(name: str, precision: int, scale: int) -> sa.Column[Any]:
    return _col(name, sa.Numeric(precision, scale))


def _small(name: str) -> sa.Column[Any]:
    return _col(name, sa.SmallInteger())


def _real(name: str) -> sa.Column[Any]:
    return _col(name, REAL)


def _array(name: str, type_: Any) -> sa.Column[Any]:
    return _col(name, postgresql.ARRAY(type_))


def upgrade() -> None:
    op.create_table(
        "activities",
        *_user("activities"),
        sa.Column("activity_id", sa.BigInteger(), nullable=False),
        _col("name", sa.String(length=200)),
        sa.Column("sport", sa.String(length=48), nullable=False),
        _col("event_type", sa.String(length=32)),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        _col("start_local", sa.DateTime()),
        _col("time_zone", sa.String(length=64)),
        _num("duration_s", 8, 1),
        _num("elapsed_s", 8, 1),
        _num("moving_s", 8, 1),
        _num("distance_m", 9, 1),
        _num("elevation_gain_m", 6, 1),
        _num("elevation_loss_m", 6, 1),
        _num("min_elevation_m", 6, 1),
        _num("max_elevation_m", 6, 1),
        _small("avg_hr"),
        _small("max_hr"),
        _num("avg_speed", 6, 3),
        _num("max_speed", 6, 3),
        _num("avg_gap_speed", 6, 3),
        _small("avg_power"),
        _small("max_power"),
        _small("norm_power"),
        _num("avg_cadence", 5, 1),
        _num("max_cadence", 5, 1),
        _col("calories", sa.Integer()),
        _col("steps", sa.Integer()),
        _num("garmin_load", 6, 1),
        _num("aerobic_te", 3, 1),
        _num("anaerobic_te", 3, 1),
        _col("te_label", sa.String(length=32)),
        _small("moderate_minutes"),
        _small("vigorous_minutes"),
        _small("body_battery_change"),
        _array("hr_zone_s", sa.Integer()),
        _array("power_zone_s", sa.Integer()),
        _num("ground_contact_ms", 5, 1),
        _num("vertical_oscillation_cm", 4, 1),
        _num("vertical_ratio_pct", 4, 1),
        _num("stride_length_cm", 5, 1),
        _num("pool_length_m", 5, 1),
        _small("active_lengths"),
        _col("strokes", sa.Integer()),
        _num("avg_strokes", 5, 1),
        _num("avg_swolf", 5, 1),
        _num("avg_stroke_distance_m", 4, 2),
        _col("fastest_splits", JSONB),
        _small("lap_count"),
        _col("manual", sa.Boolean()),
        sa.Column("is_parent", sa.Boolean(), server_default=sa.false(), nullable=False),
        _col("parent_id", sa.BigInteger()),
        _array("child_ids", sa.BigInteger()),
        sa.Column("raw", JSONB, nullable=False),
        sa.PrimaryKeyConstraint("user_id", "activity_id", name="pk_activities"),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_activities_user_id_started_at",
        "activities",
        ["user_id", "started_at"],
        schema=SCHEMA,
    )
    op.create_table(
        "activity_files",
        *_user("activity_files"),
        sa.Column("activity_id", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        _col("data", sa.LargeBinary()),
        _col("content_type", sa.String(length=64)),
        _col("size", sa.Integer()),
        sa.Column("attempts", sa.SmallInteger(), server_default=sa.text("0"), nullable=False),
        _col("error_code", sa.String(length=64)),
        sa.Column(
            "fetched_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("user_id", "activity_id", name="pk_activity_files"),
        schema=SCHEMA,
    )
    op.create_table(
        "activity_streams",
        *_activity("activity_streams"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("time_s", postgresql.ARRAY(sa.Integer()), nullable=False),
        _array("distance_m", REAL),
        _array("heart_rate", sa.SmallInteger()),
        _array("speed", REAL),
        _array("altitude_m", REAL),
        _array("cadence", REAL),
        _array("power", sa.SmallInteger()),
        _array("lat", sa.Double()),
        _array("lon", sa.Double()),
        _array("vertical_oscillation_mm", REAL),
        _array("ground_contact_ms", REAL),
        _array("step_length_mm", REAL),
        _array("vertical_ratio_pct", REAL),
        sa.PrimaryKeyConstraint("user_id", "activity_id", name="pk_activity_streams"),
        schema=SCHEMA,
    )
    op.create_table(
        "activity_laps",
        *_activity("activity_laps"),
        sa.Column("lap_index", sa.SmallInteger(), nullable=False),
        _col("started_at", sa.DateTime(timezone=True)),
        _real("elapsed_s"),
        _real("timer_s"),
        _real("distance_m"),
        _small("avg_hr"),
        _small("max_hr"),
        _real("avg_speed"),
        _real("max_speed"),
        _small("avg_power"),
        _small("max_power"),
        _small("normalized_power"),
        _real("avg_cadence"),
        _small("ascent_m"),
        _small("descent_m"),
        _small("calories"),
        _col("intensity", sa.String(length=32)),
        _col("trigger", sa.String(length=32)),
        _col("swim_stroke", sa.String(length=32)),
        _small("active_lengths"),
        _col("strokes", sa.Integer()),
        sa.PrimaryKeyConstraint("user_id", "activity_id", "lap_index", name="pk_activity_laps"),
        schema=SCHEMA,
    )
    op.create_table(
        "activity_lengths",
        *_activity("activity_lengths"),
        sa.Column("length_index", sa.SmallInteger(), nullable=False),
        _col("started_at", sa.DateTime(timezone=True)),
        _real("elapsed_s"),
        sa.Column("active", sa.Boolean(), nullable=False),
        _col("swim_stroke", sa.String(length=32)),
        _small("strokes"),
        _real("avg_speed"),
        _small("swolf"),
        sa.PrimaryKeyConstraint(
            "user_id", "activity_id", "length_index", name="pk_activity_lengths"
        ),
        schema=SCHEMA,
    )
    op.create_table(
        "activity_derived",
        *_activity("activity_derived"),
        sa.Column("moving_s", sa.Integer(), nullable=False),
        _real("hr_threshold"),
        _real("hr_max"),
        _real("hr_rest"),
        _col("hr_reference_source", sa.String(length=16)),
        _real("hr_load"),
        _array("hr_zone_s", sa.Integer()),
        _array("power_curve", REAL),
        _array("hr_curve", REAL),
        _array("speed_curve", REAL),
        _col("best_efforts", JSONB),
        _real("gap_speed"),
        _real("ngp_speed"),
        _real("efficiency_factor"),
        _real("decoupling_pct"),
        _col("steady", sa.Boolean()),
        _real("vo2max"),
        _col("climbs", JSONB),
        _real("best_vam"),
        sa.PrimaryKeyConstraint("user_id", "activity_id", name="pk_activity_derived"),
        schema=SCHEMA,
    )


def downgrade() -> None:
    for table in (
        "activity_derived",
        "activity_lengths",
        "activity_laps",
        "activity_streams",
        "activity_files",
    ):
        op.drop_table(table, schema=SCHEMA)
    op.drop_index("ix_activities_user_id_started_at", table_name="activities", schema=SCHEMA)
    op.drop_table("activities", schema=SCHEMA)
