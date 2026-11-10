"""Writing normalized rows, and rebuilding them from stored replies (ADR-0009).

A reply's rows are upserted by their natural key (member and day, or member and time), so
reading a day again updates it. A value a reply leaves out never erases one already stored.
The daily summary's own values win over those the stress, steps and Body Battery replies give,
which only fill what it lacks, whatever order they arrive in. Likewise an activity's search
summary wins over its detail, which only fills.

An activity's stored file is parsed into its stream, laps and lengths, and its results derived
(`ingest_activity_file`); `renormalize` does that again for every stored file.
"""

import dataclasses
import enum
import logging
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any

from sqlalchemy import any_, delete, func, select, tuple_, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from hubnisio.health.insights.activity import Derived, Family, derive, family
from hubnisio.health.insights.curves import Length
from hubnisio.health.insights.load import HeartRateReference, heart_rate_reference
from hubnisio.health.insights.series import Series
from hubnisio.health.models import (
    ACTIVITY_FILE_TABLES,
    FACT_TABLES,
    Activity,
    ActivityDerived,
    ActivityFile,
    ActivityLap,
    ActivityLength,
    ActivityStream,
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
from hubnisio.health.providers.garmin.fit import FitActivity, parse_activity_file
from hubnisio.health.providers.garmin.normalize import Records, Row, normalize
from hubnisio.health.scoping import of_member

logger = logging.getLogger(__name__)

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
    if records.activities or records.activity_fill:
        await _upsert(session, Activity, user_id, records.activities, ("activity_id",))
        await _upsert(
            session, Activity, user_id, records.activity_fill, ("activity_id",), fill=True
        )
        await _link_legs(session, user_id)


async def _link_legs(session: AsyncSession, user_id: uuid.UUID) -> None:
    """Point each multisport leg at its parent, whichever reply arrived first."""
    parent = aliased(Activity)
    await session.execute(
        update(Activity)
        .where(
            of_member(Activity, user_id),
            of_member(parent, user_id),
            Activity.activity_id == any_(parent.child_ids),
            Activity.parent_id.is_distinct_from(parent.activity_id),
        )
        .values(parent_id=parent.activity_id)
        .execution_options(synchronize_session=False)
    )


# Activity files


class FileStatus(enum.StrEnum):
    STORED = "stored"
    NONE = "none"  # nothing to download: a multisport parent, a manual activity
    FAILED = "failed"


async def ingest_activity_file(
    session: AsyncSession, user_id: uuid.UUID, activity_id: int, data: bytes
) -> bool:
    """Parse an activity's stored file into its stream, laps and lengths, derive its results,
    and replace what was there. False when the activity isn't stored (yet)."""
    activity = await session.get(Activity, (user_id, activity_id))
    if activity is None:
        return False
    parsed = parse_activity_file(data, activity.started_at)
    reference, floors = await _heart_rate_reference(session, user_id, activity, parsed)
    series = Series(
        time=parsed.stream.get("time") or [],
        distance=parsed.stream.get("distance") or [],
        heart_rate=parsed.stream.get("heart_rate") or [],
        speed=parsed.stream.get("speed") or [],
        altitude=parsed.stream.get("altitude") or [],
        cadence=parsed.stream.get("cadence") or [],
        power=parsed.stream.get("power") or [],
    )
    pool = parsed.pool_length_m or (
        float(activity.pool_length_m) if activity.pool_length_m is not None else None
    )
    derived = derive(
        series,
        type_key=activity.sport,
        reference=reference,
        zone_floors=floors,
        lengths=[
            Length(elapsed_s=length["elapsed_s"] or 0.0, active=length["active"])
            for length in parsed.lengths
        ],
        pool_length_m=pool,
    )
    key = {"user_id": user_id, "activity_id": activity_id}
    for model in ACTIVITY_FILE_TABLES:
        await session.execute(
            delete(model).where(of_member(model, user_id), model.activity_id == activity_id)
        )
    stream = parsed.stream
    if stream.get("time"):
        session.add(
            ActivityStream(
                **key,
                started_at=parsed.started_at or activity.started_at,
                time_s=stream["time"],
                distance_m=stream.get("distance"),
                heart_rate=_ints(stream.get("heart_rate")),
                speed=stream.get("speed"),
                altitude_m=stream.get("altitude"),
                cadence=stream.get("cadence"),
                power=_ints(stream.get("power")),
                lat=stream.get("lat"),
                lon=stream.get("lon"),
                vertical_oscillation_mm=stream.get("vertical_oscillation"),
                ground_contact_ms=stream.get("stance_time"),
                step_length_mm=stream.get("step_length"),
                vertical_ratio_pct=stream.get("vertical_ratio"),
            )
        )
    session.add_all(ActivityLap(**key, **lap) for lap in parsed.laps)
    session.add_all(ActivityLength(**key, **length) for length in parsed.lengths)
    session.add(ActivityDerived(**key, **_derived_row(derived)))
    await session.flush()
    return True


def _ints(values: list[Any] | None) -> list[int | None] | None:
    if values is None:
        return None
    return [round(value) if value is not None else None for value in values]


def _derived_row(derived: Derived) -> dict[str, Any]:
    row = {
        field.name: getattr(derived, field.name)
        for field in dataclasses.fields(derived)
        if field.name not in ("best_efforts", "climbs")
    }
    row["best_efforts"] = {str(meters): s for meters, s in derived.best_efforts.items()} or None
    row["climbs"] = [dataclasses.asdict(climb) for climb in derived.climbs] or None
    return row


# The member's zones by sport family, as Garmin names them.
_ZONE_SPORTS = {Family.RUN: "RUNNING", Family.RIDE: "CYCLING", Family.SWIM: "SWIMMING"}


async def _heart_rate_reference(
    session: AsyncSession, user_id: uuid.UUID, activity: Activity, parsed: FitActivity
) -> tuple[HeartRateReference | None, list[int | None] | None]:
    """The heart-rate reference and zone floors for an activity: the member's zones for its
    sport, else their default zones, else what the file says (ADR-0009, "Load")."""
    zones = {
        zone.sport: zone
        for zone in await session.scalars(
            select(HeartRateZones).where(of_member(HeartRateZones, user_id))
        )
    }
    sport = _ZONE_SPORTS.get(family(activity.sport))
    chosen = (zones.get(sport) if sport else None) or zones.get("DEFAULT")
    rest = await session.scalar(
        select(DailySummary.resting_hr)
        .where(
            of_member(DailySummary, user_id),
            DailySummary.day <= activity.started_at.date(),
            DailySummary.resting_hr.is_not(None),
        )
        .order_by(DailySummary.day.desc())
        .limit(1)
    )
    reference = heart_rate_reference(
        zones_threshold=chosen.lactate_threshold_hr if chosen else None,
        zones_max=chosen.max_hr if chosen else None,
        zones_rest=chosen.resting_hr if chosen else None,
        file_threshold=parsed.threshold_hr,
        file_max=parsed.max_hr,
        file_rest=parsed.rest_hr,
        rest=rest,
    )
    floors = (
        [
            chosen.zone1_floor,
            chosen.zone2_floor,
            chosen.zone3_floor,
            chosen.zone4_floor,
            chosen.zone5_floor,
        ]
        if chosen
        else None
    )
    return reference, floors


async def rebuild_activity_files(session: AsyncSession, user_id: uuid.UUID) -> tuple[int, int]:
    """Parse every stored file of the member's again. Returns (parsed, failed): a file that no
    longer parses is logged and skipped."""
    ids = list(
        await session.scalars(
            select(ActivityFile.activity_id)
            .where(of_member(ActivityFile, user_id), ActivityFile.status == FileStatus.STORED)
            .order_by(ActivityFile.activity_id)
        )
    )
    parsed = failed = 0
    for activity_id in ids:
        data = await session.scalar(
            select(ActivityFile.data).where(
                of_member(ActivityFile, user_id), ActivityFile.activity_id == activity_id
            )
        )
        if data is None:
            continue
        try:
            async with session.begin_nested():
                if await ingest_activity_file(session, user_id, activity_id, data):
                    parsed += 1
        except Exception:
            logger.exception("Parsing the file of activity %s failed.", activity_id)
            failed += 1
        session.expunge_all()
    return parsed, failed


@dataclass(frozen=True, slots=True)
class Replayed:
    payloads: int
    counts: dict[str, int]
    files: int = 0  # activity files parsed again
    failed_files: int = 0


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
    files, failed = await rebuild_activity_files(session, user_id)
    return Replayed(replayed, await fact_counts(session, user_id), files, failed)


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
    files = (
        await session.scalar(
            select(func.count()).where(
                of_member(ActivityFile, user_id), ActivityFile.status == FileStatus.STORED
            )
        )
    ) or 0
    if files:
        counts["activity_files"] = files
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
