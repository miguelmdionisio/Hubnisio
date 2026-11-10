"""The health schema (ADR-0009, slice H1): a member's Garmin connection, its syncs and raw
replies, how far each kind is synced, and the daily facts: summaries, nights, HRV, samples,
heart-rate zones, fitness age, weigh-ins and the weight goal. Every row belongs to one member.

Revision ID: 0018
Revises: 0017
Create Date: 2026-11-10
"""

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0018"
down_revision: str | None = "0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "health"

# Each enum type, created once here; the columns only refer to it.
PROVIDER = postgresql.ENUM("garmin", name="provider", schema=SCHEMA, create_type=False)
CONNECTION_STATUS = postgresql.ENUM(
    "active", "expired", name="connection_status", schema=SCHEMA, create_type=False
)
SYNC_STATUS = postgresql.ENUM(
    "running", "succeeded", "failed", name="sync_status", schema=SCHEMA, create_type=False
)
SAMPLE_KIND = postgresql.ENUM(
    "heart_rate",
    "hrv",
    "spo2",
    "body_battery",
    name="sample_kind",
    schema=SCHEMA,
    create_type=False,
)
ENUMS = (PROVIDER, CONNECTION_STATUS, SYNC_STATUS, SAMPLE_KIND)


def _user(table: str) -> list[Any]:
    """The user_id column and its foreign key to core.users."""
    return [
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"], ["core.users.id"], name=f"fk_{table}_user_id_users", ondelete="CASCADE"
        ),
    ]


def _small(name: str) -> sa.Column[Any]:
    return sa.Column(name, sa.SmallInteger(), nullable=True)


def _int(name: str) -> sa.Column[Any]:
    return sa.Column(name, sa.Integer(), nullable=True)


def _num(name: str, precision: int, scale: int) -> sa.Column[Any]:
    return sa.Column(name, sa.Numeric(precision, scale), nullable=True)


def _now(name: str) -> sa.Column[Any]:
    return sa.Column(
        name, sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
    )


def upgrade() -> None:
    op.execute(f"CREATE SCHEMA {SCHEMA}")
    bind = op.get_bind()
    for enum_type in ENUMS:
        enum_type.create(bind)

    op.create_table(
        "connections",
        sa.Column("id", sa.Uuid(), nullable=False),
        *_user("connections"),
        sa.Column("provider", PROVIDER, nullable=False),
        sa.Column("status", CONNECTION_STATUS, nullable=False),
        sa.Column("key_file", sa.String(length=100), nullable=False),
        sa.Column("key_expires_on", sa.Date(), nullable=True),
        sa.Column("time_zone", sa.String(length=64), nullable=True),
        _now("created_at"),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_connections"),
        sa.UniqueConstraint("user_id", "provider", name="uq_connections_user_id_provider"),
        schema=SCHEMA,
    )
    op.create_table(
        "sync_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("connection_id", sa.Uuid(), nullable=False),
        *_user("sync_runs"),
        sa.Column("trigger", sa.String(length=16), nullable=False),
        sa.Column("status", SYNC_STATUS, nullable=False),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("payloads", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "skipped",
            postgresql.ARRAY(sa.String(length=32)),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
        _now("started_at"),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["connection_id"],
            ["health.connections.id"],
            name="fk_sync_runs_connection_id_connections",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_sync_runs"),
        schema=SCHEMA,
    )
    op.create_table(
        "provider_payloads",
        sa.Column("id", sa.Uuid(), nullable=False),
        *_user("provider_payloads"),
        sa.Column("connection_id", sa.Uuid(), nullable=False),
        sa.Column("sync_run_id", sa.Uuid(), nullable=True),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("day_from", sa.Date(), nullable=True),
        sa.Column("day_to", sa.Date(), nullable=True),
        sa.Column("request", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("response", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        _now("fetched_at"),
        sa.ForeignKeyConstraint(
            ["connection_id"],
            ["health.connections.id"],
            name="fk_provider_payloads_connection_id_connections",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["sync_run_id"],
            ["health.sync_runs.id"],
            name="fk_provider_payloads_sync_run_id_sync_runs",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_provider_payloads"),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_provider_payloads_user_id_fetched_at",
        "provider_payloads",
        ["user_id", "fetched_at"],
        schema=SCHEMA,
    )
    op.create_table(
        "sync_cursors",
        sa.Column("connection_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("synced_through", sa.Date(), nullable=False),
        _now("updated_at"),
        sa.ForeignKeyConstraint(
            ["connection_id"],
            ["health.connections.id"],
            name="fk_sync_cursors_connection_id_connections",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("connection_id", "kind", name="pk_sync_cursors"),
        schema=SCHEMA,
    )
    op.create_table(
        "daily_summaries",
        *_user("daily_summaries"),
        sa.Column("day", sa.Date(), nullable=False),
        _int("steps"),
        _int("step_goal"),
        _num("distance_m", 9, 1),
        _small("floors_ascended"),
        _int("active_kcal"),
        _int("resting_kcal"),
        _int("total_kcal"),
        _small("resting_hr"),
        _small("min_hr"),
        _small("max_hr"),
        _small("moderate_minutes"),
        _small("vigorous_minutes"),
        _small("stress_avg"),
        _small("stress_max"),
        _int("rest_stress_s"),
        _int("low_stress_s"),
        _int("medium_stress_s"),
        _int("high_stress_s"),
        _small("body_battery_charged"),
        _small("body_battery_drained"),
        _small("body_battery_min"),
        _small("body_battery_max"),
        _small("spo2_avg"),
        _small("spo2_min"),
        _small("respiration_avg"),
        _small("respiration_min"),
        _small("respiration_max"),
        sa.Column("includes_wellness", sa.Boolean(), nullable=True),
        sa.PrimaryKeyConstraint("user_id", "day", name="pk_daily_summaries"),
        schema=SCHEMA,
    )
    op.create_table(
        "sleeps",
        *_user("sleeps"),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("garmin_id", sa.BigInteger(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=False),
        _small("utc_offset_minutes"),
        _int("sleep_s"),
        _int("deep_s"),
        _int("light_s"),
        _int("rem_s"),
        _int("awake_s"),
        _int("unmeasurable_s"),
        _int("nap_s"),
        _small("awake_count"),
        _small("score"),
        sa.Column("score_qualifier", sa.String(length=32), nullable=True),
        _small("need_minutes"),
        _num("avg_hr", 4, 1),
        _num("avg_respiration", 4, 1),
        _num("min_respiration", 4, 1),
        _num("max_respiration", 4, 1),
        _num("avg_spo2", 4, 1),
        _small("min_spo2"),
        _num("avg_sleep_stress", 4, 1),
        sa.Column("from_device", sa.Boolean(), nullable=True),
        sa.PrimaryKeyConstraint("user_id", "day", name="pk_sleeps"),
        schema=SCHEMA,
    )
    op.create_table(
        "hrv_nights",
        *_user("hrv_nights"),
        sa.Column("day", sa.Date(), nullable=False),
        _small("last_night_avg"),
        _small("last_night_5min_high"),
        _small("weekly_avg"),
        sa.Column("status", sa.String(length=32), nullable=True),
        _small("baseline_low_upper"),
        _small("baseline_balanced_low"),
        _small("baseline_balanced_upper"),
        sa.PrimaryKeyConstraint("user_id", "day", name="pk_hrv_nights"),
        schema=SCHEMA,
    )
    op.create_table(
        "samples",
        *_user("samples"),
        sa.Column("kind", SAMPLE_KIND, nullable=False),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("value", sa.Numeric(6, 1), nullable=False),
        sa.PrimaryKeyConstraint("user_id", "kind", "at", name="pk_samples"),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_samples_user_id_kind_day", "samples", ["user_id", "kind", "day"], schema=SCHEMA
    )
    op.create_table(
        "heart_rate_zones",
        *_user("heart_rate_zones"),
        sa.Column("sport", sa.String(length=32), nullable=False),
        sa.Column("training_method", sa.String(length=32), nullable=True),
        _small("max_hr"),
        _small("lactate_threshold_hr"),
        _small("resting_hr"),
        _small("zone1_floor"),
        _small("zone2_floor"),
        _small("zone3_floor"),
        _small("zone4_floor"),
        _small("zone5_floor"),
        sa.PrimaryKeyConstraint("user_id", "sport", name="pk_heart_rate_zones"),
        schema=SCHEMA,
    )
    op.create_table(
        "fitness_ages",
        *_user("fitness_ages"),
        sa.Column("day", sa.Date(), nullable=False),
        _num("fitness_age", 4, 1),
        _num("previous_fitness_age", 4, 1),
        _small("chronological_age"),
        _small("resting_hr"),
        _num("bmi", 4, 1),
        _num("vigorous_days_avg", 4, 1),
        _num("vigorous_minutes_avg", 5, 1),
        sa.PrimaryKeyConstraint("user_id", "day", name="pk_fitness_ages"),
        schema=SCHEMA,
    )
    op.create_table(
        "weights",
        *_user("weights"),
        sa.Column("measured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("weight_kg", sa.Numeric(6, 3), nullable=False),
        _num("bmi", 4, 1),
        _num("body_fat_pct", 4, 1),
        _num("body_water_pct", 4, 1),
        _num("muscle_mass_kg", 6, 3),
        _num("bone_mass_kg", 6, 3),
        sa.Column("source", sa.String(length=32), nullable=True),
        sa.PrimaryKeyConstraint("user_id", "measured_at", name="pk_weights"),
        schema=SCHEMA,
    )
    op.create_table(
        "weight_goals",
        *_user("weight_goals"),
        _num("target_kg", 6, 3),
        sa.Column("starts_on", sa.Date(), nullable=True),
        sa.PrimaryKeyConstraint("user_id", name="pk_weight_goals"),
        schema=SCHEMA,
    )


def downgrade() -> None:
    for table in (
        "weight_goals",
        "weights",
        "fitness_ages",
        "heart_rate_zones",
        "samples",
        "hrv_nights",
        "sleeps",
        "daily_summaries",
        "sync_cursors",
        "provider_payloads",
        "sync_runs",
        "connections",
    ):
        op.drop_table(table, schema=SCHEMA)
    for enum_type in reversed(ENUMS):
        enum_type.drop(op.get_bind())
    op.execute(f"DROP SCHEMA {SCHEMA}")
