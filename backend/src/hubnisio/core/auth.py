"""Who a request acts for (ADR-0005).

Until passkey login exists (ADR-0004, server milestone), the API acts as one bootstrapped
development user, named by HUBNISIO_DEV_USER_EMAIL. When login arrives only `get_principal`
changes; everything else depends on the `Principal` it returns.
"""

import uuid
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from hubnisio.core.db import get_session
from hubnisio.core.models import HouseholdMember, HouseholdRole, User
from hubnisio.core.settings import Settings, get_settings


@dataclass(frozen=True, slots=True)
class Principal:
    user_id: uuid.UUID
    household_id: uuid.UUID
    role: HouseholdRole


async def household_principals(session: AsyncSession) -> list[Principal]:
    """Every member of every household, as the principal they act as: for background work that
    runs for each member (push alerts), with the same visibility as their own requests."""
    rows = await session.execute(
        select(HouseholdMember.user_id, HouseholdMember.household_id, HouseholdMember.role)
    )
    return [Principal(user_id=r.user_id, household_id=r.household_id, role=r.role) for r in rows]


def check_auth_config(settings: Settings) -> None:
    """Called at startup: without real login, the API must not run outside development."""
    if settings.environment != "development":
        raise RuntimeError(
            "The API has no login yet, only the development user, so it only runs with "
            f"HUBNISIO_ENVIRONMENT=development (got {settings.environment!r})."
        )


async def get_principal(session: Annotated[AsyncSession, Depends(get_session)]) -> Principal:
    """FastAPI dependency: the user and household the request acts for."""
    email = get_settings().dev_user_email
    if not email:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "HUBNISIO_DEV_USER_EMAIL is not set."
        )
    row = (
        await session.execute(
            select(HouseholdMember.user_id, HouseholdMember.household_id, HouseholdMember.role)
            .join(User, User.id == HouseholdMember.user_id)
            .where(User.email == email.lower())
        )
    ).one_or_none()
    if row is None:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "The development user doesn't exist yet: run `python -m hubnisio.cli bootstrap`.",
        )
    return Principal(user_id=row.user_id, household_id=row.household_id, role=row.role)
