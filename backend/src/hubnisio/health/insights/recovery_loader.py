"""Reads the member's rows into `DayFacts` for `recovery` (through health/scoping.py)."""

from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import distinct_on
from sqlalchemy.ext.asyncio import AsyncSession

from hubnisio.core.auth import Principal
from hubnisio.health.insights.recovery import (
    AVG_DAYS,
    BAND_DAYS,
    SWING_LONG_DAYS,
    DayFacts,
)
from hubnisio.health.models import DailySummary, HrvNight, Sample, SampleKind, Sleep
from hubnisio.health.scoping import mine

# How far before the window the facts reach: the band for its first night, and the 90-day swing.
LOOKBACK = max(BAND_DAYS, SWING_LONG_DAYS + AVG_DAYS - 1)


async def load_recovery_facts(
    session: AsyncSession, principal: Principal, today: date, days: int
) -> list[DayFacts]:
    start = today - timedelta(days=days - 1 + LOOKBACK)
    rows: dict[date, dict[str, float | None]] = {}

    def put(day: date, **values: float | None) -> None:
        rows.setdefault(day, {}).update(values)

    for hrv in await session.scalars(
        select(HrvNight).where(mine(HrvNight, principal), HrvNight.day.between(start, today))
    ):
        put(hrv.day, hrv=hrv.last_night_avg)

    for s in await session.scalars(
        select(DailySummary).where(
            mine(DailySummary, principal), DailySummary.day.between(start, today)
        )
    ):
        put(
            s.day,
            resting_hr=s.resting_hr,
            battery_charged=s.body_battery_charged,
            battery_drained=s.body_battery_drained,
            stress_avg=s.stress_avg,
            rest_s=s.rest_stress_s,
            low_s=s.low_stress_s,
            medium_s=s.medium_stress_s,
            high_s=s.high_stress_s,
        )

    for sleep in await session.scalars(
        select(Sleep).where(mine(Sleep, principal), Sleep.day.between(start, today))
    ):
        put(
            sleep.day,
            sleep_s=sleep.sleep_s,
            sleep_need_min=sleep.need_minutes,
        )

    # Body Battery at waking: the first reading of the night's day at or after the night's end.
    wake = await session.execute(
        select(Sleep.day, Sample.value)
        .ext(distinct_on(Sleep.day))
        .join(
            Sample,
            (Sample.user_id == Sleep.user_id)
            & (Sample.day == Sleep.day)
            & (Sample.at >= Sleep.ended_at),
        )
        .where(
            mine(Sleep, principal),
            Sample.kind == SampleKind.BODY_BATTERY,
            Sleep.day.between(start, today),
        )
        .order_by(Sleep.day, Sample.at)
    )
    for day, value in wake:
        put(day, battery_wake=float(value))

    return [DayFacts(day=day, **values) for day, values in sorted(rows.items())]
