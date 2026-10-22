"""Identity and household tables (ADR-0005)."""

import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, String, func
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
