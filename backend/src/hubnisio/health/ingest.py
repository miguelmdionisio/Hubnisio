"""Writing normalized rows, and rebuilding them from stored replies (ADR-0009).

A reply's rows are upserted by their natural key (member and day, or member and time), so
reading a day again updates it. A value a reply leaves out never erases one already stored.
The daily summary's own values win over those the stress, steps and Body Battery replies give,
which only fill what it lacks, whatever order they arrive in.
"""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any

from sqlalchemy import delete, func, select, tuple_
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from hubnisio.health.models import (
    FACT_TABLES,
    DailySummary,
    FitnessAge,
    HeartRateZones,
    HrvNight,
    ProviderPayload,
    Sample,
    Sleep,
    Weight,
    WeightGoal,
)
from hubnisio.health.providers.garmin.normalize import Records, Row, normalize
from hubnisio.health.scoping import of_member

CHUNK = 1000  # rows per statement, well under Postgres's limit on parameters
REPLAY_BATCH = 100  # stored replies loaded at a time by renormalize


async def apply(
    session: AsyncSession, user_id: uuid.UUID, kind: str, raw: Any, day_from: date | None
) -> Records:
    """Normalize one reply and write its rows. Returns the rows, e.g. for the time zone."""
    records = normalize(kind, raw, day_from)
    await write(session, user_id, records)
    return records


async def write(session: AsyncSession, user_id: uuid.UUID, records: Records) -> None:
    await _upsert(session, DailySummary, user_id, records.daily, ("day",))
    await _upsert(session, DailySummary, user_id, records.daily_fill, ("day",), fill=True)
    await _upsert(session, Sleep, user_id, records.sleeps, ("day",))
    await _upsert(session, HrvNight, user_id, records.hrv, ("day",))
    await _upsert(session, Sample, user_id, records.samples, ("kind", "at"), replace=True)
    await _upsert(session, FitnessAge, user_id, records.fitness, ("day",))
    await _upsert(session, Weight, user_id, records.weights, ("measured_at",))
    if records.zones is not None:
        await session.execute(delete(HeartRateZones).where(of_member(HeartRateZones, user_id)))
        await _upsert(session, HeartRateZones, user_id, records.zones, ("sport",))
    if records.weight_goal is not None:
        await _upsert(session, WeightGoal, user_id, [records.weight_goal], (), replace=True)
    elif records.clear_weight_goal:
        await session.execute(delete(WeightGoal).where(of_member(WeightGoal, user_id)))


@dataclass(frozen=True, slots=True)
class Replayed:
    payloads: int
    counts: dict[str, int]


async def renormalize_member(session: AsyncSession, user_id: uuid.UUID) -> Replayed:
    """Delete a member's facts and rebuild them from every stored reply, oldest first."""
    for model in FACT_TABLES:
        await session.execute(delete(model).where(of_member(model, user_id)))
    replayed = 0
    after: tuple[Any, uuid.UUID] | None = None
    while True:
        query = (
            select(ProviderPayload)
            .where(of_member(ProviderPayload, user_id))
            .order_by(ProviderPayload.fetched_at, ProviderPayload.id)
            .limit(REPLAY_BATCH)
        )
        if after is not None:
            query = query.where(
                tuple_(ProviderPayload.fetched_at, ProviderPayload.id) > tuple_(*after)
            )
        payloads = list(await session.scalars(query))
        if not payloads:
            break
        for payload in payloads:
            await apply(session, user_id, payload.kind, payload.response, payload.day_from)
        replayed += len(payloads)
        after = (payloads[-1].fetched_at, payloads[-1].id)
        session.expunge_all()  # the replies can be large; don't keep them all
    return Replayed(replayed, await fact_counts(session, user_id))


async def fact_counts(session: AsyncSession, user_id: uuid.UUID) -> dict[str, int]:
    """Rows per fact table, and samples per kind, for the member."""
    counts: dict[str, int] = {}
    for model in FACT_TABLES:
        if model is Sample:
            continue
        counts[model.__tablename__] = (
            await session.scalar(select(func.count()).where(of_member(model, user_id)))
        ) or 0
    samples = await session.execute(
        select(Sample.kind, func.count()).where(of_member(Sample, user_id)).group_by(Sample.kind)
    )
    for kind, count in samples:
        counts[f"samples.{kind.value}"] = count
    return counts


async def _upsert(
    session: AsyncSession,
    model: Any,
    user_id: uuid.UUID,
    rows: Sequence[Row],
    keys: tuple[str, ...],
    *,
    fill: bool = False,
    replace: bool = False,
) -> None:
    """Insert rows, or update the stored ones. On a stored row, a column takes the new value
    when it's given (`replace`: even when it's null; `fill`: only when the stored one is null)."""
    if not rows:
        return
    # A statement can't touch a row twice: the last row for a key wins.
    unique = list({tuple(row[key] for key in keys): row for row in rows}.values())
    table = model.__table__
    for start in range(0, len(unique), CHUNK):
        chunk = [{**row, "user_id": user_id} for row in unique[start : start + CHUNK]]
        statement = insert(model).values(chunk)
        columns = [name for name in chunk[0] if name not in ("user_id", *keys)]
        new = statement.excluded
        if replace:
            values = {name: new[name] for name in columns}
        elif fill:
            values = {name: func.coalesce(table.c[name], new[name]) for name in columns}
        else:
            values = {name: func.coalesce(new[name], table.c[name]) for name in columns}
        if values:
            statement = statement.on_conflict_do_update(
                index_elements=["user_id", *keys], set_=values
            )
        else:
            statement = statement.on_conflict_do_nothing(index_elements=["user_id", *keys])
        await session.execute(statement)
