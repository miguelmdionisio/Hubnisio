"""Recovery over time: HRV against the member's normal range, resting heart rate, Body Battery,
stress, and "Signals today" (ADR-0009, "As built in H4"). Pure: rows in, figures out.

A day without data is a gap (`None`), never a zero. Signals are independent checks, each
ok / watch / no data; they are counted, never merged into one score.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from statistics import fmean, pstdev, stdev
from typing import Literal

BAND_DAYS = 60  # the trailing nights the normal range is drawn from
BAND_MIN_NIGHTS = 14  # fewer nights than this and there is no band
BAND_WIDTH = 0.75  # standard deviations either side of the mean
AVG_DAYS = 7
AVG_MIN = 4  # a 7-day average needs at least this many of its days
SWING_LONG_DAYS = 90
SWING_LONG_MIN = 14  # rolling swings needed for the 90-day value
STALE_DAYS = 2  # a signal's value may be this many days old
RESTING_HR_MARGIN = 3  # bpm above its 7-day average still counts as ok
SLEEP_SHARE = 0.85  # of need
BODY_BATTERY_FLOOR = 60
FORM_FLOOR = -10.0  # provisional until H6's form bands exist

State = Literal["ok", "watch", "no_data"]
Position = Literal["in", "below", "above"]


@dataclass(frozen=True)
class DayFacts:
    """Everything recovery reads about one day; `None` where Garmin sent nothing."""

    day: date
    hrv: float | None = None  # the night's average, ms
    resting_hr: float | None = None
    battery_wake: float | None = None  # Body Battery at waking
    battery_charged: float | None = None
    battery_drained: float | None = None
    stress_avg: float | None = None
    rest_s: float | None = None
    low_s: float | None = None
    medium_s: float | None = None
    high_s: float | None = None
    sleep_s: float | None = None
    sleep_need_min: float | None = None


@dataclass(frozen=True)
class Band:
    low: float
    high: float
    mean: float


@dataclass(frozen=True)
class HrvPoint:
    day: date
    value: float | None
    avg7: float | None
    band_low: float | None
    band_high: float | None
    below: bool  # the night is under the band


@dataclass(frozen=True)
class HrvSummary:
    avg7: float | None
    band_low: float | None
    band_high: float | None
    position: Position | None
    below_nights: int  # in the window
    swing: float | None  # coefficient of variation of the last 7 nights, %
    swing_90: float | None  # the mean of that over the last 90 days, %
    nights: int  # nights with a value in the window


@dataclass(frozen=True)
class HrvOut:
    points: list[HrvPoint]
    summary: HrvSummary


@dataclass(frozen=True)
class RestingPoint:
    day: date
    value: float | None
    avg7: float | None


@dataclass(frozen=True)
class RestingSummary:
    latest: float | None
    avg7: float | None
    change: float | None  # latest less its 7-day average
    average: float | None  # over the window


@dataclass(frozen=True)
class RestingOut:
    points: list[RestingPoint]
    summary: RestingSummary


@dataclass(frozen=True)
class BatteryPoint:
    day: date
    at_wake: float | None
    charged: float | None
    drained: float | None


@dataclass(frozen=True)
class BatterySummary:
    at_wake: float | None
    charged: float | None  # the same day's
    day: date | None


@dataclass(frozen=True)
class BatteryOut:
    points: list[BatteryPoint]
    summary: BatterySummary


@dataclass(frozen=True)
class StressPoint:
    day: date
    rest_min: float | None
    low_min: float | None
    medium_min: float | None
    high_min: float | None
    avg: float | None


@dataclass(frozen=True)
class StressSummary:
    avg: float | None  # the average level over the window
    high_min: float | None  # high-stress minutes per day, averaged


@dataclass(frozen=True)
class StressOut:
    points: list[StressPoint]
    summary: StressSummary


@dataclass(frozen=True)
class Signal:
    """One check. `value` is compared with `reference_low` / `reference_high`:
    hrv: the 7-day average against the band; resting_hr: the latest against its 7-day average
    (`reference_low`) and the most that still passes (`reference_high`); sleep: minutes slept
    against the threshold (`reference_low`) and the need (`reference_high`); body_battery: at
    wake against its floor; form: against its floor."""

    key: Literal["hrv", "resting_hr", "sleep", "body_battery", "form"]
    state: State
    value: float | None
    reference_low: float | None
    reference_high: float | None
    day: date | None  # the day the value is from


@dataclass(frozen=True)
class Signals:
    items: list[Signal]
    ok: int
    total: int  # signals with data: what the count is out of


@dataclass(frozen=True)
class Recovery:
    days: int
    first_day: date
    last_day: date
    hrv: HrvOut
    resting_hr: RestingOut
    body_battery: BatteryOut
    stress: StressOut
    signals: Signals


def _round(value: float | None, places: int = 1) -> float | None:
    return None if value is None else round(value, places)


def _mean(values: Sequence[float | None], minimum: int = 1) -> float | None:
    present = [v for v in values if v is not None]
    return fmean(present) if len(present) >= minimum else None


def band_of(values: Sequence[float | None]) -> Band | None:
    """The normal range from a stretch of nightly values: mean ± 0.75 standard deviations
    (sample), or `None` under 14 nights."""
    present = [v for v in values if v is not None]
    if len(present) < BAND_MIN_NIGHTS:
        return None
    mean = fmean(present)
    spread = BAND_WIDTH * stdev(present)
    return Band(low=mean - spread, high=mean + spread, mean=mean)


def swing_of(values: Sequence[float | None]) -> float | None:
    """The coefficient of variation of the values, in percent (population deviation), with at
    least 4 present; `None` when the mean isn't positive."""
    present = [v for v in values if v is not None]
    if len(present) < AVG_MIN:
        return None
    mean = fmean(present)
    return pstdev(present) / mean * 100 if mean > 0 else None


def position_of(value: float, band: Band) -> Position:
    return "below" if value < band.low else "above" if value > band.high else "in"


def _latest(window: Sequence[DayFacts], today: date, field: str) -> tuple[date, float] | None:
    """The newest value of a field, if it is no more than `STALE_DAYS` old."""
    for fact in reversed(window):
        if fact.day > today:
            continue
        if (today - fact.day).days > STALE_DAYS:
            return None
        value = getattr(fact, field)
        if value is not None:
            return fact.day, value
    return None


def recovery(
    facts: Sequence[DayFacts], today: date, days: int, form: float | None = None
) -> Recovery:
    """Recovery over the `days` ending today. `facts` should reach back far enough for the
    band (60 days) and the 90-day swing before the window's first day, in any order, with gaps
    simply missing. `form` is the training form when there is one: absent leaves its signal out."""
    by_day = {f.day: f for f in facts}
    first = today - timedelta(days=days - 1)

    def get(day: date) -> DayFacts:
        return by_day.get(day) or DayFacts(day=day)

    def trailing(day: date, length: int, field: str) -> list[float | None]:
        return [getattr(get(day - timedelta(days=i)), field) for i in range(length - 1, -1, -1)]

    window = [get(first + timedelta(days=i)) for i in range(days)]

    # HRV
    hrv_points: list[HrvPoint] = []
    for fact in window:
        band = band_of(trailing(fact.day, BAND_DAYS, "hrv"))
        hrv_points.append(
            HrvPoint(
                day=fact.day,
                value=fact.hrv,
                avg7=_round(_mean(trailing(fact.day, AVG_DAYS, "hrv"), AVG_MIN)),
                band_low=_round(band.low if band else None),
                band_high=_round(band.high if band else None),
                below=fact.hrv is not None and band is not None and fact.hrv < band.low,
            )
        )
    last_band = band_of(trailing(today, BAND_DAYS, "hrv"))
    avg7 = _mean(trailing(today, AVG_DAYS, "hrv"), AVG_MIN)
    swings = [
        swing_of(trailing(today - timedelta(days=i), AVG_DAYS, "hrv"))
        for i in range(SWING_LONG_DAYS)
    ]
    swings_present = [s for s in swings if s is not None]
    hrv = HrvOut(
        points=hrv_points,
        summary=HrvSummary(
            avg7=_round(avg7),
            band_low=_round(last_band.low if last_band else None),
            band_high=_round(last_band.high if last_band else None),
            position=position_of(avg7, last_band) if avg7 is not None and last_band else None,
            below_nights=sum(p.below for p in hrv_points),
            swing=_round(swing_of(trailing(today, AVG_DAYS, "hrv"))),
            swing_90=(
                _round(fmean(swings_present)) if len(swings_present) >= SWING_LONG_MIN else None
            ),
            nights=sum(p.value is not None for p in hrv_points),
        ),
    )

    # Resting heart rate
    rhr_latest = _latest(window, today, "resting_hr")
    rhr_avg7 = _mean(trailing(today, AVG_DAYS, "resting_hr"), AVG_MIN)
    resting = RestingOut(
        points=[
            RestingPoint(
                day=f.day,
                value=f.resting_hr,
                avg7=_round(_mean(trailing(f.day, AVG_DAYS, "resting_hr"), AVG_MIN)),
            )
            for f in window
        ],
        summary=RestingSummary(
            latest=rhr_latest[1] if rhr_latest else None,
            avg7=_round(rhr_avg7),
            change=(
                _round(rhr_latest[1] - rhr_avg7) if rhr_latest and rhr_avg7 is not None else None
            ),
            average=_round(_mean([f.resting_hr for f in window])),
        ),
    )

    # Body Battery
    wake = _latest(window, today, "battery_wake")
    battery = BatteryOut(
        points=[
            BatteryPoint(f.day, f.battery_wake, f.battery_charged, f.battery_drained)
            for f in window
        ],
        summary=BatterySummary(
            at_wake=wake[1] if wake else None,
            charged=get(wake[0]).battery_charged if wake else None,
            day=wake[0] if wake else None,
        ),
    )

    # Stress
    def minutes(seconds: float | None) -> float | None:
        return None if seconds is None else round(seconds / 60, 1)

    stress = StressOut(
        points=[
            StressPoint(
                f.day,
                minutes(f.rest_s),
                minutes(f.low_s),
                minutes(f.medium_s),
                minutes(f.high_s),
                f.stress_avg,
            )
            for f in window
        ],
        summary=StressSummary(
            avg=_round(_mean([f.stress_avg for f in window])),
            high_min=_round(_mean([minutes(f.high_s) for f in window])),
        ),
    )

    items = _signals(window, today, hrv.summary, resting.summary, form)
    return Recovery(
        days=days,
        first_day=first,
        last_day=today,
        hrv=hrv,
        resting_hr=resting,
        body_battery=battery,
        stress=stress,
        signals=Signals(
            items=items,
            ok=sum(s.state == "ok" for s in items),
            total=sum(s.state != "no_data" for s in items),
        ),
    )


def _signals(
    window: Sequence[DayFacts],
    today: date,
    hrv: HrvSummary,
    resting: RestingSummary,
    form: float | None,
) -> list[Signal]:
    def state(good: bool | None) -> State:
        return "no_data" if good is None else "ok" if good else "watch"

    items = [
        Signal(
            "hrv",
            state(None if hrv.position is None else hrv.position == "in"),
            hrv.avg7,
            hrv.band_low,
            hrv.band_high,
            today if hrv.avg7 is not None else None,
        )
    ]

    rhr = _latest(window, today, "resting_hr")
    limit = None if resting.avg7 is None else resting.avg7 + RESTING_HR_MARGIN
    items.append(
        Signal(
            "resting_hr",
            state(None if rhr is None or limit is None else rhr[1] <= limit),
            rhr[1] if rhr else None,
            resting.avg7,
            limit,
            rhr[0] if rhr else None,
        )
    )

    night = next(
        (
            f
            for f in reversed(window)
            if f.day <= today
            and (today - f.day).days <= STALE_DAYS
            and f.sleep_s is not None
            and f.sleep_need_min
        ),
        None,
    )
    if night is None or night.sleep_s is None or night.sleep_need_min is None:
        items.append(Signal("sleep", "no_data", None, None, None, None))
    else:
        slept = night.sleep_s / 60
        need = night.sleep_need_min
        items.append(
            Signal(
                "sleep",
                state(slept >= SLEEP_SHARE * need),
                round(slept, 1),
                round(SLEEP_SHARE * need, 1),
                need,
                night.day,
            )
        )

    battery = _latest(window, today, "battery_wake")
    items.append(
        Signal(
            "body_battery",
            state(None if battery is None else battery[1] >= BODY_BATTERY_FLOOR),
            battery[1] if battery else None,
            BODY_BATTERY_FLOOR,
            None,
            battery[0] if battery else None,
        )
    )

    if form is not None:
        items.append(Signal("form", state(form >= FORM_FLOOR), form, FORM_FLOOR, None, today))
    return items
