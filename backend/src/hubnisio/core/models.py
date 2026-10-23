"""Identity and household tables (ADR-0005), and AI access (ADR-0006)."""

import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String, func
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
