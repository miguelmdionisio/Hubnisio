"""Whose health data a query may touch (ADR-0009). Every health query goes through here.

Health data belongs to one member. There is no household view: another member of the same
household, the owner included, sees nothing of it, not even whether a watch is linked. Rows
are found by `user_id` alone; a principal's household plays no part.
"""

import uuid
from typing import Any

from sqlalchemy import ColumnElement, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute

from hubnisio.core.auth import Principal
from hubnisio.health.models import Connection, ProviderName


def of_member(model: Any, user_id: uuid.UUID) -> ColumnElement[bool]:
    """SQL condition: the row belongs to this member. For code acting for a member it was
    handed (the sync, the CLI), not for a request: requests use `mine`."""
    column: InstrumentedAttribute[uuid.UUID] = model.user_id
    return column == user_id


def mine(model: Any, principal: Principal) -> ColumnElement[bool]:
    """SQL condition: the row belongs to the principal."""
    return of_member(model, principal.user_id)


async def own_connection(
    session: AsyncSession, principal: Principal, provider: ProviderName = ProviderName.GARMIN
) -> Connection | None:
    """The principal's own connection to the provider, if they linked one."""
    return await session.scalar(
        select(Connection).where(mine(Connection, principal), Connection.provider == provider)
    )
