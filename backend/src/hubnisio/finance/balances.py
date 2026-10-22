"""The latest bank-reported balance of each account (ADR-0007: snapshots are the truth)."""

import uuid
from collections.abc import Sequence

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from hubnisio.finance.models import BalanceSnapshot

# Shown on the Accounts page first: what's spendable, then the booked balance.
SPENDABLE_FIRST = ("ITAV", "CLAV", "ITBD", "CLBD", "XPCD", "OPAV", "OPBD")
# For net worth: the booked balance first, since an available one can include an overdraft.
BOOKED_FIRST = ("CLBD", "ITBD", "XPCD", "ITAV", "CLAV", "OPBD", "OPAV")


async def latest_balances(
    session: AsyncSession,
    account_ids: Sequence[uuid.UUID],
    preference: Sequence[str] = SPENDABLE_FIRST,
) -> dict[uuid.UUID, BalanceSnapshot]:
    """Per account, the preferred balance from its most recent sync."""
    if not account_ids:
        return {}
    latest = (
        select(BalanceSnapshot.account_id, func.max(BalanceSnapshot.fetched_at).label("at"))
        .where(BalanceSnapshot.account_id.in_(account_ids))
        .group_by(BalanceSnapshot.account_id)
        .subquery()
    )
    snapshots = await session.scalars(
        select(BalanceSnapshot).join(
            latest,
            (BalanceSnapshot.account_id == latest.c.account_id)
            & (BalanceSnapshot.fetched_at == latest.c.at),
        )
    )

    def rank(snapshot: BalanceSnapshot) -> int:
        if snapshot.balance_type in preference:
            return preference.index(snapshot.balance_type)
        return len(preference)

    chosen: dict[uuid.UUID, BalanceSnapshot] = {}
    for snapshot in snapshots:
        current = chosen.get(snapshot.account_id)
        if current is None or rank(snapshot) < rank(current):
            chosen[snapshot.account_id] = snapshot
    return chosen
