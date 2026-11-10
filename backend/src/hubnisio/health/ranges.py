"""The first and last day stored per kind of fact, for the Garmin page (member-only)."""

import uuid
from datetime import date

from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from hubnisio.health.models import FACT_TABLES, Sample
from hubnisio.health.scoping import of_member


class DateRange(BaseModel):
    first: date
    last: date


async def fact_ranges(session: AsyncSession, user_id: uuid.UUID) -> dict[str, DateRange]:
    """Keyed like `fact_counts`: a table's name, or `samples.<kind>`. Kinds with no rows and
    tables without a `day` are left out."""
    ranges: dict[str, DateRange] = {}
    for model in FACT_TABLES:
        day = getattr(model, "day", None)
        if day is None:
            continue
        if model is Sample:
            rows = await session.execute(
                select(Sample.kind, func.min(day), func.max(day))
                .where(of_member(Sample, user_id))
                .group_by(Sample.kind)
            )
            for kind, first, last in rows:
                ranges[f"samples.{kind.value}"] = DateRange(first=first, last=last)
            continue
        row = (
            await session.execute(
                select(func.min(day), func.max(day)).where(of_member(model, user_id))
            )
        ).one()
        if row[0] is not None:
            ranges[model.__tablename__] = DateRange(first=row[0], last=row[1])
    return ranges
