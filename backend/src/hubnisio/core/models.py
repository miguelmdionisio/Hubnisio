"""Identity and household tables (ADR-0005), AI access (ADR-0006), and push alerts (M9)."""

import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from hubnisio.core.db import Base

SCHEMA = "core"


class HouseholdRole(enum.StrEnum):
    OWNER = "owner"
    MEMBER = "member"


class User(Base):
    __tablename__ = "users"
    __table_args__ = {"schema": SCHEMA}  # noqa: RUF012

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid7)
    email: Mapped[str] = mapped_column(String(320), unique=True)
    display_name: Mapped[str] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Household(Base):
    __tablename__ = "households"
    __table_args__ = {"schema": SCHEMA}  # noqa: RUF012

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid7)
    name: Mapped[str] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class HouseholdMember(Base):
    __tablename__ = "household_members"
    __table_args__ = {"schema": SCHEMA}  # noqa: RUF012

    household_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("core.households.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("core.users.id", ondelete="CASCADE"), primary_key=True
    )
    role: Mapped[HouseholdRole] = mapped_column(
        Enum(
            HouseholdRole,
            name="household_role",
            schema=SCHEMA,
            values_callable=lambda roles: [role.value for role in roles],
        )
    )
    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AiLogin(Base):
    """A member's Postgres login for AI access (ADR-0006), created by `cli ai-login`. The
    `analytics` views find the member through `session_user`, so they show this member's data."""

    __tablename__ = "ai_logins"
    __table_args__ = {"schema": SCHEMA}  # noqa: RUF012

    role_name: Mapped[str] = mapped_column(String(63), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("core.users.id", ondelete="CASCADE"), unique=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AiCall(Base):
    """One AI tool call, written by `analytics.record_call`: who, which tool and its arguments,
    never the data returned. Kept after a login is revoked."""

    __tablename__ = "ai_calls"
    __table_args__ = {"schema": SCHEMA}  # noqa: RUF012

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, server_default=func.uuidv7())
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    role_name: Mapped[str] = mapped_column(String(63))
    tool: Mapped[str] = mapped_column(String(100))
    arguments: Mapped[dict[str, Any]] = mapped_column(JSONB)
    row_count: Mapped[int | None] = mapped_column(Integer)


class AlertKind(enum.StrEnum):
    """What a push alert is about (M9 P6). Each can be turned off per member."""

    BILL_DUE = "bill_due"  # a confirmed recurring payment due tomorrow
    BUDGET_OVER = "budget_over"  # a budget overspent this month
    SYNC_FAILING = "sync_failing"  # a bank or Garmin connection failing for a day
    KEY_LAPSING = "key_lapsing"  # the Garmin key lapses within two weeks


# One type, shared by the tables below.
ALERT_KIND = Enum(
    AlertKind,
    name="alert_kind",
    schema=SCHEMA,
    values_callable=lambda kinds: [kind.value for kind in kinds],
)


class PushSubscription(Base):
    """One device's Web Push subscription (the installed app on a phone), for one member. The
    endpoint is the push service's URL for that device; the keys encrypt what's sent."""

    __tablename__ = "push_subscriptions"
    __table_args__ = {"schema": SCHEMA}  # noqa: RUF012

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid7)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("core.users.id", ondelete="CASCADE"))
    endpoint: Mapped[str] = mapped_column(Text, unique=True)
    p256dh: Mapped[str] = mapped_column(String(200))
    auth: Mapped[str] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AlertPreference(Base):
    """A member's choice for one kind of alert. No row: on."""

    __tablename__ = "alert_preferences"
    __table_args__ = {"schema": SCHEMA}  # noqa: RUF012

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("core.users.id", ondelete="CASCADE"), primary_key=True
    )
    kind: Mapped[AlertKind] = mapped_column(ALERT_KIND, primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean)


class AlertSent(Base):
    """An alert that went out, by its key (e.g. a bill and its date), so each is sent once
    however often the checks run or catch up."""

    __tablename__ = "alerts_sent"
    __table_args__ = {"schema": SCHEMA}  # noqa: RUF012

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("core.users.id", ondelete="CASCADE"), primary_key=True
    )
    key: Mapped[str] = mapped_column(String(200), primary_key=True)
    kind: Mapped[AlertKind] = mapped_column(ALERT_KIND)
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
