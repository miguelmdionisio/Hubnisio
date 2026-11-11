"""Activities: the list and one activity's page (ADR-0009, "As built in H5").

Member-only: every query goes through `health/scoping.py`, so another member gets an empty list
and a 404 for an id that isn't theirs. The numbers come from `health/insights/activity_view.py`.
"""

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Annotated, Any, Literal

from fastapi import APIRouter, HTTPException, Query, Response, status
from pydantic import BaseModel
from sqlalchemy import ColumnElement, Select, and_, exists, func, not_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import undefer

from hubnisio.core.auth import Principal
from hubnisio.health.api import CurrentPrincipal, DbSession
from hubnisio.health.insights import activity_view as view
from hubnisio.health.insights.activity import Family, family, is_pool
from hubnisio.health.insights.series import Series
from hubnisio.health.models import (
    Activity,
    ActivityDerived,
    ActivityFile,
    ActivityLap,
    ActivityLength,
    ActivityStream,
)
from hubnisio.health.scoping import mine

router = APIRouter(prefix="/health", tags=["health"])

DEFAULT_LIMIT = 30
MAX_LIMIT = 100
BASELINE_DAYS = 90
EPOCH = datetime(1970, 1, 1, tzinfo=UTC)

SportFilter = Literal["swim", "bike", "run", "strength", "other"]


def _f(value: object) -> float | None:
    return None if value is None else float(value)  # pyright: ignore[reportArgumentType]


# -- List ---------------------------------------------------------------------------------


class ActivityLeg(BaseModel):
    id: int
    sport: str
    group: view.Group
    name: str | None
    start: datetime  # wall-clock time there, no zone
    duration_s: float | None
    distance_m: float | None
    load: float | None
    figure_kind: view.FigureKind | None
    figure: float | None


class ActivityRow(ActivityLeg):
    legs: list[ActivityLeg]  # a multisport activity's legs; the legs are not rows of their own


class ActivityList(BaseModel):
    items: list[ActivityRow]
    next_cursor: str | None


def _local_start() -> ColumnElement[datetime]:
    return func.coalesce(Activity.start_local, func.timezone("UTC", Activity.started_at))


def _sport_condition(group: SportFilter) -> ColumnElement[bool]:
    """SQL twin of `view.sport_group` (tests keep them in agreement)."""
    key = func.lower(Activity.sport)
    run = key.like("%running")
    bike = or_(key.like("%cycling%"), key.like("%biking%"), key.in_(("virtual_ride", "bmx")))
    swim = key.like("%swimming%")
    strength = and_(key.like("%strength%"), not_(or_(run, bike, swim)))
    match group:
        case "run":
            return run
        case "bike":
            return and_(bike, not_(run))
        case "swim":
            return and_(swim, not_(run), not_(bike))
        case "strength":
            return strength
        case "other":
            return not_(or_(run, bike, swim, key.like("%strength%")))


def _row_fields(activity: Activity, load: float | None) -> dict[str, Any]:
    group = view.sport_group(activity.sport)
    distance = _f(activity.distance_m)
    duration = _f(activity.duration_s)
    kind, figure = view.key_figure(group, distance, duration)
    return {
        "id": activity.activity_id,
        "sport": activity.sport,
        "group": group,
        "name": activity.name,
        "start": view.local_start(activity.started_at, activity.start_local),
        "duration_s": duration,
        "distance_m": distance,
        "load": load,
        "figure_kind": kind,
        "figure": figure,
    }


def _cursor(activity: Activity) -> str:
    micros = (activity.started_at - EPOCH) // timedelta(microseconds=1)
    return f"{micros}.{activity.activity_id}"


def _after(cursor: str) -> ColumnElement[bool]:
    try:
        micros, _, ident = cursor.partition(".")
        at = EPOCH + timedelta(microseconds=int(micros))
        number = int(ident)
    except ValueError:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Bad cursor") from None
    return or_(
        Activity.started_at < at, and_(Activity.started_at == at, Activity.activity_id < number)
    )


@router.get("/activities", operation_id="listActivities")
async def list_activities(
    session: DbSession,
    principal: CurrentPrincipal,
    sport: SportFilter | None = None,
    from_: Annotated[date | None, Query(alias="from")] = None,
    to: date | None = None,
    q: Annotated[str | None, Query(max_length=100)] = None,
    cursor: str | None = None,
    limit: Annotated[int, Query(ge=1, le=MAX_LIMIT)] = DEFAULT_LIMIT,
) -> ActivityList:
    """The member's activities, newest first. A multisport activity is one row with its legs."""
    parent = Activity.__table__.alias("parent")
    has_parent = exists().where(
        parent.c.user_id == Activity.user_id, parent.c.activity_id == Activity.parent_id
    )
    query: Select[Activity, float | None] = (
        select(Activity, ActivityDerived.hr_load)
        .outerjoin(
            ActivityDerived,
            and_(
                ActivityDerived.user_id == Activity.user_id,
                ActivityDerived.activity_id == Activity.activity_id,
            ),
        )
        .where(mine(Activity, principal), or_(Activity.parent_id.is_(None), not_(has_parent)))
        .order_by(Activity.started_at.desc(), Activity.activity_id.desc())
        .limit(limit + 1)
    )
    if sport is not None:
        query = query.where(_sport_condition(sport))
    if from_ is not None:
        query = query.where(_local_start() >= datetime.combine(from_, time.min))
    if to is not None:
        query = query.where(_local_start() < datetime.combine(to + timedelta(days=1), time.min))
    if q and (needle := q.strip()):
        pattern = f"%{needle.replace('\\', '\\\\').replace('%', r'\%').replace('_', r'\_')}%"
        query = query.where(
            or_(
                Activity.name.ilike(pattern, escape="\\"),
                Activity.sport.ilike(pattern, escape="\\"),
            )
        )
    if cursor:
        query = query.where(_after(cursor))
    rows = (await session.execute(query)).all()
    page = rows[:limit]
    legs = await _legs(session, principal, [a.activity_id for a, _ in page if a.is_parent])
    items: list[ActivityRow] = []
    for activity, load in page:
        mine_legs = legs.get(activity.activity_id, [])
        total = load
        if activity.is_parent:
            loads = [leg.load for leg in mine_legs if leg.load is not None]
            total = round(sum(loads), 1) if loads else None
        items.append(ActivityRow(**_row_fields(activity, _f(total)), legs=mine_legs))
    return ActivityList(
        items=items, next_cursor=_cursor(page[-1][0]) if len(rows) > limit and page else None
    )


async def _legs(
    session: AsyncSession, principal: Principal, parent_ids: list[int]
) -> dict[int, list[ActivityLeg]]:
    if not parent_ids:
        return {}
    rows = await session.execute(
        select(Activity, ActivityDerived.hr_load)
        .outerjoin(
            ActivityDerived,
            and_(
                ActivityDerived.user_id == Activity.user_id,
                ActivityDerived.activity_id == Activity.activity_id,
            ),
        )
        .where(mine(Activity, principal), Activity.parent_id.in_(parent_ids))
        .order_by(Activity.started_at, Activity.activity_id)
    )
    out: dict[int, list[ActivityLeg]] = {}
    for activity, load in rows.all():
        if activity.parent_id is not None:
            out.setdefault(activity.parent_id, []).append(
                ActivityLeg(**_row_fields(activity, _f(load)))
            )
    return out


# -- One activity -------------------------------------------------------------------------


class ActivitySummary(BaseModel):
    distance_m: float | None
    duration_s: float | None
    moving_s: float | None
    elapsed_s: float | None
    avg_speed: float | None  # m/s
    max_speed: float | None
    graded_speed: float | None  # ours: Minetti's, for runs
    avg_hr: int | None
    max_hr: int | None
    elevation_gain_m: float | None
    elevation_loss_m: float | None
    avg_cadence: float | None
    max_cadence: float | None
    avg_power: int | None
    norm_power: int | None
    max_power: int | None
    calories: int | None
    steps: int | None
    pool_length_m: float | None
    lengths: int | None
    avg_swolf: float | None
    avg_strokes: float | None
    vo2max: float | None


class ActivityLoads(BaseModel):
    ours: float | None  # hrTSS-style, from the member's heart-rate reference
    garmin: float | None
    aerobic_te: float | None
    anaerobic_te: float | None
    te_label: str | None


class ActivityDurability(BaseModel):
    decoupling_pct: float
    efficiency_factor: float
    steady: bool | None
    efficiency_90d: float | None  # the member's mean over the 90 days before, same sport
    first: view.ActivityHalf | None
    second: view.ActivityHalf | None


class ActivityPair(BaseModel):
    value: float | None
    avg_90d: float | None


class ActivityForm(BaseModel):
    cadence: ActivityPair
    stride_cm: ActivityPair
    ground_contact_ms: ActivityPair
    vertical_oscillation_cm: ActivityPair
    vertical_ratio_pct: ActivityPair
    power: ActivityPair


class ActivityClimb(BaseModel):
    start_s: float
    duration_s: float
    distance_m: float
    gain_m: float
    grade: float
    vam: float


class ActivitySplits(BaseModel):
    kind: Literal["km", "lap"]
    rows: list[view.ActivitySplit]


class ActivityPool(BaseModel):
    sets: list[view.SwimSet]
    lengths: list[view.SwimLength]


class ActivityDetail(BaseModel):
    id: int
    sport: str
    group: view.Group
    family: Family
    name: str | None
    start: datetime
    pool: bool
    parent_id: int | None
    legs: list[ActivityLeg]
    has_file: bool
    summary: ActivitySummary
    loads: ActivityLoads
    streams: view.ActivityStreams | None
    splits: ActivitySplits | None
    pool_sets: ActivityPool | None
    zones: view.ActivityZones | None
    durability: ActivityDurability | None
    form: ActivityForm | None
    climbs: list[ActivityClimb]
    best_vam: float | None
    route: list[tuple[float, float]] | None


@dataclass(frozen=True, slots=True)
class _Baseline:
    values: dict[str, float | None]
    efficiency: float | None


async def _baseline(session: AsyncSession, principal: Principal, a: Activity) -> _Baseline:
    """The member's mean of an activity's figures over the 90 days before it, same sport."""
    window = and_(
        mine(Activity, principal),
        Activity.sport == a.sport,
        Activity.activity_id != a.activity_id,
        Activity.is_parent.is_(False),
        Activity.started_at < a.started_at,
        Activity.started_at >= a.started_at - timedelta(days=BASELINE_DAYS),
    )
    cols = {
        "cadence": Activity.avg_cadence,
        "stride_cm": Activity.stride_length_cm,
        "ground_contact_ms": Activity.ground_contact_ms,
        "vertical_oscillation_cm": Activity.vertical_oscillation_cm,
        "vertical_ratio_pct": Activity.vertical_ratio_pct,
        "power": Activity.avg_power,
    }
    row = (await session.execute(select(*(func.avg(c) for c in cols.values())).where(window))).one()
    efficiency = await session.scalar(
        select(func.avg(ActivityDerived.efficiency_factor))
        .join(
            Activity,
            and_(
                Activity.user_id == ActivityDerived.user_id,
                Activity.activity_id == ActivityDerived.activity_id,
            ),
        )
        .where(window)
    )
    return _Baseline(
        values={name: _f(value) for name, value in zip(cols, row, strict=True)},
        efficiency=_f(efficiency),
    )


def _pair(value: object, baseline: float | None, places: int) -> ActivityPair:
    v = _f(value)
    return ActivityPair(
        value=None if v is None else round(v, places),
        avg_90d=None if baseline is None else round(baseline, places),
    )


async def _get(
    session: AsyncSession, principal: Principal, activity_id: int
) -> tuple[Activity, ActivityDerived | None]:
    activity = await session.scalar(
        select(Activity).where(mine(Activity, principal), Activity.activity_id == activity_id)
    )
    if activity is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such activity")
    derived = await session.scalar(
        select(ActivityDerived).where(
            mine(ActivityDerived, principal), ActivityDerived.activity_id == activity_id
        )
    )
    return activity, derived


@router.get("/activities/{activity_id}", operation_id="getActivity")
async def get_activity(
    activity_id: int, session: DbSession, principal: CurrentPrincipal
) -> ActivityDetail:
    """One of the member's activities, shaped for its page; a section the activity can't give
    is null or empty."""
    a, derived = await _get(session, principal, activity_id)
    sport = family(a.sport)
    pool = is_pool(a.sport)
    row = await session.scalar(
        select(ActivityStream).where(
            mine(ActivityStream, principal), ActivityStream.activity_id == activity_id
        )
    )
    data = (
        view.StreamData(
            time=row.time_s,
            distance=row.distance_m,
            heart_rate=row.heart_rate,
            speed=row.speed,
            altitude=row.altitude_m,
            cadence=row.cadence,
            power=row.power,
            lat=row.lat,
            lon=row.lon,
        )
        if row
        else None
    )
    laps = (
        await session.scalars(
            select(ActivityLap)
            .where(mine(ActivityLap, principal), ActivityLap.activity_id == activity_id)
            .order_by(ActivityLap.lap_index)
        )
    ).all()
    lengths = (
        await session.scalars(
            select(ActivityLength)
            .where(mine(ActivityLength, principal), ActivityLength.activity_id == activity_id)
            .order_by(ActivityLength.length_index)
        )
    ).all()
    file_status = await session.scalar(
        select(ActivityFile.status).where(
            mine(ActivityFile, principal), ActivityFile.activity_id == activity_id
        )
    )
    legs = (await _legs(session, principal, [activity_id])).get(activity_id, [])

    splits: ActivitySplits | None = None
    if sport is Family.RUN and data is not None:
        km = view.km_splits(data)
        splits = ActivitySplits(kind="km", rows=km) if km else None
    if splits is None and not pool:
        lap_rows = view.lap_splits(
            [
                view.LapIn(
                    index=lap.lap_index + 1,
                    distance_m=lap.distance_m,
                    duration_s=lap.timer_s or lap.elapsed_s,
                    avg_hr=lap.avg_hr,
                    avg_speed=lap.avg_speed,
                    avg_power=lap.avg_power,
                    ascent_m=lap.ascent_m,
                    descent_m=lap.descent_m,
                )
                for lap in laps
            ]
        )
        splits = ActivitySplits(kind="lap", rows=lap_rows) if len(lap_rows) > 1 else None

    pool_sets: ActivityPool | None = None
    if pool and lengths and a.pool_length_m:
        sets, swum = view.swim_sets(
            [
                view.LengthIn(
                    index=x.length_index,
                    active=x.active,
                    stroke=x.swim_stroke,
                    strokes=x.strokes,
                    duration_s=x.elapsed_s,
                    swolf=x.swolf,
                )
                for x in lengths
            ],
            float(a.pool_length_m),
        )
        pool_sets = ActivityPool(sets=sets, lengths=swum) if sets else None

    durability: ActivityDurability | None = None
    baseline: _Baseline | None = None
    if sport in (Family.RUN, Family.RIDE):
        baseline = await _baseline(session, principal, a)
    if (
        derived is not None
        and derived.decoupling_pct is not None
        and derived.efficiency_factor is not None
    ):
        halves = (
            view.half_figures(
                a.sport,
                Series(
                    time=data.time,
                    distance=data.distance or (),
                    heart_rate=data.heart_rate or (),
                    speed=data.speed or (),
                    altitude=data.altitude or (),
                    cadence=data.cadence or (),
                    power=data.power or (),
                ),
            )
            if data is not None
            else None
        )
        durability = ActivityDurability(
            decoupling_pct=round(derived.decoupling_pct, 1),
            efficiency_factor=round(derived.efficiency_factor, 3),
            steady=derived.steady,
            efficiency_90d=None
            if baseline is None or baseline.efficiency is None
            else round(baseline.efficiency, 3),
            first=halves[0] if halves else None,
            second=halves[1] if halves else None,
        )

    form: ActivityForm | None = None
    if (
        sport is Family.RUN
        and baseline is not None
        and any(
            v is not None
            for v in (
                a.ground_contact_ms,
                a.vertical_oscillation_cm,
                a.vertical_ratio_pct,
                a.stride_length_cm,
            )
        )
    ):
        b = baseline.values
        form = ActivityForm(
            cadence=_pair(a.avg_cadence, b["cadence"], 0),
            stride_cm=_pair(a.stride_length_cm, b["stride_cm"], 0),
            ground_contact_ms=_pair(a.ground_contact_ms, b["ground_contact_ms"], 0),
            vertical_oscillation_cm=_pair(
                a.vertical_oscillation_cm, b["vertical_oscillation_cm"], 1
            ),
            vertical_ratio_pct=_pair(a.vertical_ratio_pct, b["vertical_ratio_pct"], 1),
            power=_pair(a.avg_power, b["power"], 0),
        )

    return ActivityDetail(
        id=a.activity_id,
        sport=a.sport,
        group=view.sport_group(a.sport),
        family=sport,
        name=a.name,
        start=view.local_start(a.started_at, a.start_local),
        pool=pool,
        parent_id=a.parent_id,
        legs=legs,
        has_file=file_status == "stored",
        summary=ActivitySummary(
            distance_m=_f(a.distance_m),
            duration_s=_f(a.duration_s),
            moving_s=_f(a.moving_s),
            elapsed_s=_f(a.elapsed_s),
            avg_speed=_f(a.avg_speed),
            max_speed=_f(a.max_speed),
            graded_speed=derived.gap_speed if derived else None,
            avg_hr=a.avg_hr,
            max_hr=a.max_hr,
            elevation_gain_m=_f(a.elevation_gain_m),
            elevation_loss_m=_f(a.elevation_loss_m),
            avg_cadence=_f(a.avg_cadence),
            max_cadence=_f(a.max_cadence),
            avg_power=a.avg_power,
            norm_power=a.norm_power,
            max_power=a.max_power,
            calories=a.calories,
            steps=a.steps,
            pool_length_m=_f(a.pool_length_m),
            lengths=a.active_lengths,
            avg_swolf=_f(a.avg_swolf),
            avg_strokes=_f(a.avg_strokes),
            vo2max=derived.vo2max if derived else None,
        ),
        loads=ActivityLoads(
            ours=derived.hr_load if derived else None,
            garmin=_f(a.garmin_load),
            aerobic_te=_f(a.aerobic_te),
            anaerobic_te=_f(a.anaerobic_te),
            te_label=a.te_label,
        ),
        streams=view.shape_streams(a.sport, data) if data is not None else None,
        splits=splits,
        pool_sets=pool_sets,
        zones=view.heart_rate_zones(
            derived.hr_zone_s if derived else None,
            a.hr_zone_s,
            derived.hr_threshold if derived else None,
        ),
        durability=durability,
        form=form,
        climbs=[ActivityClimb(**c) for c in (derived.climbs or [])] if derived else [],
        best_vam=derived.best_vam if derived else None,
        route=None if data is None else view.simplified_route(data.lat, data.lon),
    )


@router.get("/activities/{activity_id}/file", operation_id="downloadActivityFile")
async def download_activity_file(
    activity_id: int, session: DbSession, principal: CurrentPrincipal
) -> Response:
    """The file as Garmin sent it (a zip holding the .FIT)."""
    stored = await session.scalar(
        select(ActivityFile)
        .options(undefer(ActivityFile.data))
        .where(
            mine(ActivityFile, principal),
            ActivityFile.activity_id == activity_id,
            ActivityFile.status == "stored",
        )
    )
    if stored is None or stored.data is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No file for this activity")
    return Response(
        content=stored.data,
        media_type=stored.content_type or "application/zip",
        headers={"Content-Disposition": f'attachment; filename="activity-{activity_id}.zip"'},
    )
