"""Health tables (ADR-0009): a member's Garmin connection, the raw replies, and the daily
facts normalized from them.

Health data belongs to one member: every table carries `user_id`, and nothing here has a
household. Only the sync (and `renormalize`, from the stored replies) writes the facts, which
are rebuilt whole from `provider_payloads`.
"""

import enum
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

# Health foreign keys point at core.users; load core's models so SQLAlchemy can resolve them.
from hubnisio.core import models as core_models  # noqa: F401
from hubnisio.core.db import Base

SCHEMA = "health"


def _enum(python_enum: type[enum.StrEnum], name: str) -> Enum:
    return Enum(
        python_enum,
        name=name,
        schema=SCHEMA,
        values_callable=lambda members: [member.value for member in members],
    )


def _user() -> Mapped[uuid.UUID]:
    return mapped_column(ForeignKey("core.users.id", ondelete="CASCADE"), primary_key=True)


class ProviderName(enum.StrEnum):
    GARMIN = "garmin"


class ConnectionStatus(enum.StrEnum):
    ACTIVE = "active"
    EXPIRED = "expired"  # the key lapsed or was rejected: link a new one


class SyncStatus(enum.StrEnum):
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class SampleKind(enum.StrEnum):
    HEART_RATE = "heart_rate"  # bpm, every couple of minutes, all day
    HRV = "hrv"  # ms, the night's 5-minute readings
    SPO2 = "spo2"  # %, hourly averages
    BODY_BATTERY = "body_battery"  # 0 to 100


class Connection(Base):
    """A member's link to a provider: the name of their key's file, never the key."""

    __tablename__ = "connections"
    __table_args__ = (
        UniqueConstraint("user_id", "provider", name="uq_connections_user_id_provider"),
        {"schema": SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid7)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("core.users.id", ondelete="CASCADE"))
    provider: Mapped[ProviderName] = mapped_column(_enum(ProviderName, "provider"))
    status: Mapped[ConnectionStatus] = mapped_column(_enum(ConnectionStatus, "connection_status"))
    key_file: Mapped[str] = mapped_column(String(100))
    # The key lasts a year at most and the API doesn't say when it lapses: given when linking.
    key_expires_on: Mapped[date | None] = mapped_column(Date)
    # The member's time zone at the provider (an IANA name): what "today" is for them.
    time_zone: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SyncRun(Base):
    """One sync of one connection. `skipped` names the kinds whose calls failed but didn't fail
    the run (ADR-0009, "Sync")."""

    __tablename__ = "sync_runs"
    __table_args__ = {"schema": SCHEMA}  # noqa: RUF012

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid7)
    connection_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("health.connections.id", ondelete="CASCADE")
    )
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("core.users.id", ondelete="CASCADE"))
    trigger: Mapped[str] = mapped_column(String(16))  # initial, scheduled, user, backfill
    status: Mapped[SyncStatus] = mapped_column(_enum(SyncStatus, "sync_status"))
    error_code: Mapped[str | None] = mapped_column(String(64))
    payloads: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    skipped: Mapped[list[str]] = mapped_column(ARRAY(String(32)), server_default=text("'{}'"))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ProviderPayload(Base):
    """Every reply, append-only: `renormalize` rebuilds the facts from these."""

    __tablename__ = "provider_payloads"
    __table_args__ = (
        Index("ix_provider_payloads_user_id_fetched_at", "user_id", "fetched_at"),
        {"schema": SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid7)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("core.users.id", ondelete="CASCADE"))
    connection_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("health.connections.id", ondelete="CASCADE")
    )
    sync_run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("health.sync_runs.id", ondelete="SET NULL")
    )
    kind: Mapped[str] = mapped_column(String(32))  # daily_summaries, sleep, hrv, …
    day_from: Mapped[date | None] = mapped_column(Date)  # the days the reply covers
    day_to: Mapped[date | None] = mapped_column(Date)
    request: Mapped[dict[str, Any]] = mapped_column(JSONB)
    # A JSON object or list; null when the reply had no body.
    response: Mapped[Any] = mapped_column(JSONB, nullable=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SyncCursor(Base):
    """How far each kind is synced: the next sync starts a little before this day."""

    __tablename__ = "sync_cursors"
    __table_args__ = {"schema": SCHEMA}  # noqa: RUF012

    connection_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("health.connections.id", ondelete="CASCADE"), primary_key=True
    )
    kind: Mapped[str] = mapped_column(String(32), primary_key=True)
    synced_through: Mapped[date] = mapped_column(Date)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class DailySummary(Base):
    """One day's totals, from Garmin's daily summary; the stress, steps and Body Battery
    replies fill what it lacks."""

    __tablename__ = "daily_summaries"
    __table_args__ = {"schema": SCHEMA}  # noqa: RUF012

    user_id: Mapped[uuid.UUID] = _user()
    day: Mapped[date] = mapped_column(Date, primary_key=True)
    steps: Mapped[int | None] = mapped_column(Integer)
    step_goal: Mapped[int | None] = mapped_column(Integer)
    distance_m: Mapped[Decimal | None] = mapped_column(Numeric(9, 1))
    floors_ascended: Mapped[int | None] = mapped_column(SmallInteger)
    active_kcal: Mapped[int | None] = mapped_column(Integer)
    resting_kcal: Mapped[int | None] = mapped_column(Integer)
    total_kcal: Mapped[int | None] = mapped_column(Integer)
    resting_hr: Mapped[int | None] = mapped_column(SmallInteger)
    min_hr: Mapped[int | None] = mapped_column(SmallInteger)
    max_hr: Mapped[int | None] = mapped_column(SmallInteger)
    moderate_minutes: Mapped[int | None] = mapped_column(SmallInteger)
    vigorous_minutes: Mapped[int | None] = mapped_column(SmallInteger)
    stress_avg: Mapped[int | None] = mapped_column(SmallInteger)
    stress_max: Mapped[int | None] = mapped_column(SmallInteger)
    rest_stress_s: Mapped[int | None] = mapped_column(Integer)
    low_stress_s: Mapped[int | None] = mapped_column(Integer)
    medium_stress_s: Mapped[int | None] = mapped_column(Integer)
    high_stress_s: Mapped[int | None] = mapped_column(Integer)
    body_battery_charged: Mapped[int | None] = mapped_column(SmallInteger)
    body_battery_drained: Mapped[int | None] = mapped_column(SmallInteger)
    body_battery_min: Mapped[int | None] = mapped_column(SmallInteger)
    body_battery_max: Mapped[int | None] = mapped_column(SmallInteger)
    spo2_avg: Mapped[int | None] = mapped_column(SmallInteger)
    spo2_min: Mapped[int | None] = mapped_column(SmallInteger)
    respiration_avg: Mapped[int | None] = mapped_column(SmallInteger)
    respiration_min: Mapped[int | None] = mapped_column(SmallInteger)
    respiration_max: Mapped[int | None] = mapped_column(SmallInteger)
    includes_wellness: Mapped[bool | None] = mapped_column(Boolean)


class Sleep(Base):
    """One night, under the day it ends (Garmin's calendar date)."""

    __tablename__ = "sleeps"
    __table_args__ = {"schema": SCHEMA}  # noqa: RUF012

    user_id: Mapped[uuid.UUID] = _user()
    day: Mapped[date] = mapped_column(Date, primary_key=True)
    garmin_id: Mapped[int | None] = mapped_column(BigInteger)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    utc_offset_minutes: Mapped[int | None] = mapped_column(SmallInteger)  # local time - UTC
    sleep_s: Mapped[int | None] = mapped_column(Integer)
    deep_s: Mapped[int | None] = mapped_column(Integer)
    light_s: Mapped[int | None] = mapped_column(Integer)
    rem_s: Mapped[int | None] = mapped_column(Integer)
    awake_s: Mapped[int | None] = mapped_column(Integer)
    unmeasurable_s: Mapped[int | None] = mapped_column(Integer)
    nap_s: Mapped[int | None] = mapped_column(Integer)
    awake_count: Mapped[int | None] = mapped_column(SmallInteger)
    score: Mapped[int | None] = mapped_column(SmallInteger)
    score_qualifier: Mapped[str | None] = mapped_column(String(32))
    need_minutes: Mapped[int | None] = mapped_column(SmallInteger)
    avg_hr: Mapped[Decimal | None] = mapped_column(Numeric(4, 1))
    avg_respiration: Mapped[Decimal | None] = mapped_column(Numeric(4, 1))
    min_respiration: Mapped[Decimal | None] = mapped_column(Numeric(4, 1))
    max_respiration: Mapped[Decimal | None] = mapped_column(Numeric(4, 1))
    avg_spo2: Mapped[Decimal | None] = mapped_column(Numeric(4, 1))
    min_spo2: Mapped[int | None] = mapped_column(SmallInteger)
    avg_sleep_stress: Mapped[Decimal | None] = mapped_column(Numeric(4, 1))
    from_device: Mapped[bool | None] = mapped_column(Boolean)


class HrvNight(Base):
    """A night's HRV summary and Garmin's baseline (ms)."""

    __tablename__ = "hrv_nights"
    __table_args__ = {"schema": SCHEMA}  # noqa: RUF012

    user_id: Mapped[uuid.UUID] = _user()
    day: Mapped[date] = mapped_column(Date, primary_key=True)
    last_night_avg: Mapped[int | None] = mapped_column(SmallInteger)
    last_night_5min_high: Mapped[int | None] = mapped_column(SmallInteger)
    weekly_avg: Mapped[int | None] = mapped_column(SmallInteger)
    status: Mapped[str | None] = mapped_column(String(32))
    baseline_low_upper: Mapped[int | None] = mapped_column(SmallInteger)
    baseline_balanced_low: Mapped[int | None] = mapped_column(SmallInteger)
    baseline_balanced_upper: Mapped[int | None] = mapped_column(SmallInteger)


class Sample(Base):
    """A reading over time: heart rate, HRV, SpO2 or Body Battery. `day` is the calendar day
    of the reply it came from."""

    __tablename__ = "samples"
    __table_args__ = (
        Index("ix_samples_user_id_kind_day", "user_id", "kind", "day"),
        {"schema": SCHEMA},
    )

    user_id: Mapped[uuid.UUID] = _user()
    kind: Mapped[SampleKind] = mapped_column(_enum(SampleKind, "sample_kind"), primary_key=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    day: Mapped[date] = mapped_column(Date)
    value: Mapped[Decimal] = mapped_column(Numeric(6, 1))


class HeartRateZones(Base):
    """The member's current heart-rate zones per sport (floors in bpm)."""

    __tablename__ = "heart_rate_zones"
    __table_args__ = {"schema": SCHEMA}  # noqa: RUF012

    user_id: Mapped[uuid.UUID] = _user()
    sport: Mapped[str] = mapped_column(String(32), primary_key=True)
    training_method: Mapped[str | None] = mapped_column(String(32))
    max_hr: Mapped[int | None] = mapped_column(SmallInteger)
    lactate_threshold_hr: Mapped[int | None] = mapped_column(SmallInteger)
    resting_hr: Mapped[int | None] = mapped_column(SmallInteger)
    zone1_floor: Mapped[int | None] = mapped_column(SmallInteger)
    zone2_floor: Mapped[int | None] = mapped_column(SmallInteger)
    zone3_floor: Mapped[int | None] = mapped_column(SmallInteger)
    zone4_floor: Mapped[int | None] = mapped_column(SmallInteger)
    zone5_floor: Mapped[int | None] = mapped_column(SmallInteger)


class FitnessAge(Base):
    """Garmin's fitness age as read on a day."""

    __tablename__ = "fitness_ages"
    __table_args__ = {"schema": SCHEMA}  # noqa: RUF012

    user_id: Mapped[uuid.UUID] = _user()
    day: Mapped[date] = mapped_column(Date, primary_key=True)
    fitness_age: Mapped[Decimal | None] = mapped_column(Numeric(4, 1))
    previous_fitness_age: Mapped[Decimal | None] = mapped_column(Numeric(4, 1))
    chronological_age: Mapped[int | None] = mapped_column(SmallInteger)
    resting_hr: Mapped[int | None] = mapped_column(SmallInteger)
    bmi: Mapped[Decimal | None] = mapped_column(Numeric(4, 1))
    vigorous_days_avg: Mapped[Decimal | None] = mapped_column(Numeric(4, 1))
    vigorous_minutes_avg: Mapped[Decimal | None] = mapped_column(Numeric(5, 1))


class Weight(Base):
    """A weigh-in."""

    __tablename__ = "weights"
    __table_args__ = {"schema": SCHEMA}  # noqa: RUF012

    user_id: Mapped[uuid.UUID] = _user()
    measured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    day: Mapped[date] = mapped_column(Date)
    weight_kg: Mapped[Decimal] = mapped_column(Numeric(6, 3))
    bmi: Mapped[Decimal | None] = mapped_column(Numeric(4, 1))
    body_fat_pct: Mapped[Decimal | None] = mapped_column(Numeric(4, 1))
    body_water_pct: Mapped[Decimal | None] = mapped_column(Numeric(4, 1))
    muscle_mass_kg: Mapped[Decimal | None] = mapped_column(Numeric(6, 3))
    bone_mass_kg: Mapped[Decimal | None] = mapped_column(Numeric(6, 3))
    source: Mapped[str | None] = mapped_column(String(32))


class WeightGoal(Base):
    """The member's current weight goal, if they set one."""

    __tablename__ = "weight_goals"
    __table_args__ = {"schema": SCHEMA}  # noqa: RUF012

    user_id: Mapped[uuid.UUID] = _user()
    target_kg: Mapped[Decimal | None] = mapped_column(Numeric(6, 3))
    starts_on: Mapped[date | None] = mapped_column(Date)


# The facts `renormalize` rebuilds, each keyed by user_id.
FACT_TABLES = (
    DailySummary,
    Sleep,
    HrvNight,
    Sample,
    HeartRateZones,
    FitnessAge,
    Weight,
    WeightGoal,
)
