"""An activity's original file (ADR-0009, H2): Garmin's download is a zip holding one `.FIT`.

`parse_activity_file` reads it with Garmin's FIT SDK (`garmin-fit-sdk`) into plain columns,
laps and pool lengths: pure, no database. What the watch records, and what's kept:

- **Records** (about one a second, fewer with smart recording, none while paused): time,
  distance (m), speed (m/s), altitude (m), heart rate, cadence, power (W), position
  (semicircles, kept as degrees), and for runs the running dynamics: vertical oscillation (mm),
  ground contact (ms), step length (mm), vertical ratio (%). Speed and altitude are the
  `enhanced_` fields when present. A run's cadence is in steps per minute (the file holds
  strides per minute and a fraction); other sports keep the file's (rpm, strokes/min).
- **Laps** and, for pool swims, **lengths** (active or rest, stroke, strokes, time).
- **The session**: sport, start, pool length, and the heart-rate zones the watch used
  (`time_in_zone` for the session: threshold, maximum and resting heart rate).

A multisport file holds a session per leg; `started_at` picks the one starting closest to the
activity, and only its records, laps and lengths are kept.
"""

import io
import math
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, cast

from garmin_fit_sdk import Decoder, Stream

MAX_UNZIPPED = 64 * 1024 * 1024  # bytes: a FIT file is a few hundred KB
SEMICIRCLE = 180 / 2**31  # degrees per semicircle
RUN_SPORTS = frozenset({"running", "walking", "hiking"})

Row = dict[str, Any]

# Stream columns: (column, the record's fields in order of preference).
_RECORD_FIELDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("distance", ("distance",)),
    ("heart_rate", ("heart_rate",)),
    ("speed", ("enhanced_speed", "speed")),
    ("altitude", ("enhanced_altitude", "altitude")),
    ("power", ("power",)),
    ("vertical_oscillation", ("vertical_oscillation",)),
    ("stance_time", ("stance_time",)),
    ("step_length", ("step_length",)),
    ("vertical_ratio", ("vertical_ratio",)),
)
STREAM_COLUMNS = (
    "time",
    "distance",
    "heart_rate",
    "speed",
    "altitude",
    "cadence",
    "power",
    "lat",
    "lon",
    "vertical_oscillation",
    "stance_time",
    "step_length",
    "vertical_ratio",
)


class FitError(Exception):
    """Not a FIT file (or a zip holding one), or one with no activity in it."""


@dataclass
class FitActivity:
    sport: str | None = None
    sub_sport: str | None = None
    started_at: datetime | None = None
    pool_length_m: float | None = None
    threshold_hr: int | None = None
    max_hr: int | None = None
    rest_hr: int | None = None
    # Columns of the same length, `time` in seconds from the start; a column with no value at
    # all is None.
    stream: dict[str, list[Any] | None] = field(default_factory=dict[str, list[Any] | None])
    laps: list[Row] = field(default_factory=list[Row])
    lengths: list[Row] = field(default_factory=list[Row])

    @property
    def samples(self) -> int:
        return len(self.stream.get("time") or [])


def fit_bytes(data: bytes) -> bytes:
    """The FIT file in a download: the zip's `.fit` entry, or the bytes themselves."""
    if not data.startswith(b"PK"):
        return data
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            entries = [info for info in archive.infolist() if not info.is_dir()]
            entry = next(
                (info for info in entries if info.filename.lower().endswith(".fit")),
                entries[0] if entries else None,
            )
            if entry is None:
                raise FitError("The zip is empty.")
            if entry.file_size > MAX_UNZIPPED:
                raise FitError("The zip's file is too large.")
            return archive.read(entry)
    except zipfile.BadZipFile as exc:
        raise FitError("Not a zip.") from exc


def parse_activity_file(data: bytes, started_at: datetime | None = None) -> FitActivity:
    fit = fit_bytes(data)
    decoder = Decoder(Stream.from_byte_array(bytearray(fit)))
    if not decoder.is_fit():
        raise FitError("Not a FIT file.")
    decoded, errors = decoder.read(convert_datetimes_to_dates=True, merge_heart_rates=True)
    messages = cast(dict[str, list[Row]], decoded)
    sessions = list(messages.get("session_mesgs", []))
    records = list(messages.get("record_mesgs", []))
    if not sessions and not records:
        raise FitError(f"No activity in the file ({len(errors)} decoding errors).")

    session, index = _session(sessions, started_at)
    start: datetime | None = session.get("start_time") if session else None
    if start is None:
        start = next((r["timestamp"] for r in records if "timestamp" in r), None)
    end = _end(session, start)
    activity = FitActivity(
        sport=_text(session.get("sport")) if session else None,
        sub_sport=_text(session.get("sub_sport")) if session else None,
        started_at=start,
        pool_length_m=_number(session.get("pool_length")) if session else None,
    )
    _zones(activity, messages.get("time_in_zone_mesgs", []), index)
    if start is None:
        return activity
    activity.stream = _stream(records, start, end, activity.sport in RUN_SPORTS)
    activity.laps = [_lap(lap) for lap in messages.get("lap_mesgs", []) if _within(lap, start, end)]
    for number, lap in enumerate(activity.laps):
        lap["lap_index"] = number
    activity.lengths = [
        _length(length)
        for length in messages.get("length_mesgs", [])
        if _within(length, start, end)
    ]
    for number, length in enumerate(activity.lengths):
        length["length_index"] = number
    return activity


def _session(sessions: list[Row], started_at: datetime | None) -> tuple[Row | None, int]:
    if not sessions:
        return None, 0
    if started_at is None or len(sessions) == 1:
        return sessions[0], 0

    def distance(item: tuple[int, Row]) -> float:
        start = item[1].get("start_time")
        return abs((start - started_at).total_seconds()) if start else math.inf

    index, session = min(enumerate(sessions), key=distance)
    return session, index


def _end(session: Row | None, start: datetime | None) -> datetime | None:
    if session is None or start is None:
        return None
    elapsed = _number(session.get("total_elapsed_time"))
    if elapsed is None:
        return None
    return start + timedelta(seconds=elapsed + 1)


def _within(message: Row, start: datetime, end: datetime | None) -> bool:
    moment = message.get("start_time") or message.get("timestamp")
    if not isinstance(moment, datetime):
        return True
    return moment >= start and (end is None or moment <= end)


def _zones(activity: FitActivity, zones: list[Row], session_index: int) -> None:
    """The zones the watch used for the session (else for any message)."""
    chosen = next(
        (
            zone
            for zone in zones
            if _text(zone.get("reference_mesg")) == "session"
            and zone.get("reference_index") == session_index
        ),
        zones[0] if zones else None,
    )
    if chosen is None:
        return
    activity.threshold_hr = _int(chosen.get("threshold_heart_rate"))
    activity.max_hr = _int(chosen.get("max_heart_rate"))
    activity.rest_hr = _int(chosen.get("resting_heart_rate"))


def _stream(
    records: list[Row], start: datetime, end: datetime | None, run: bool
) -> dict[str, list[Any] | None]:
    by_second: dict[int, Row] = {}
    for record in records:
        moment = record.get("timestamp")
        if not isinstance(moment, datetime) or moment < start or (end and moment > end):
            continue
        by_second[round((moment - start).total_seconds())] = record  # the last one wins
    seconds = sorted(by_second)
    columns: dict[str, list[Any]] = {name: [] for name in STREAM_COLUMNS}
    for second in seconds:
        record = by_second[second]
        columns["time"].append(second)
        for name, fields in _RECORD_FIELDS:
            columns[name].append(
                next((v for f in fields if (v := _number(record.get(f))) is not None), None)
            )
        columns["cadence"].append(_cadence(record, run))
        lat, lon = _number(record.get("position_lat")), _number(record.get("position_long"))
        columns["lat"].append(lat * SEMICIRCLE if lat is not None and lon is not None else None)
        columns["lon"].append(lon * SEMICIRCLE if lat is not None and lon is not None else None)
    return {
        name: (values if name == "time" or any(v is not None for v in values) else None)
        for name, values in columns.items()
    }


def _cadence(record: Row, run: bool) -> float | None:
    cadence = _number(record.get("cadence"))
    if cadence is None:
        return None
    cadence += _number(record.get("fractional_cadence")) or 0.0
    return cadence * 2 if run else cadence


def _lap(lap: Row) -> Row:
    return {
        "started_at": lap.get("start_time"),
        "elapsed_s": _number(lap.get("total_elapsed_time")),
        "timer_s": _number(lap.get("total_timer_time")),
        "distance_m": _number(lap.get("total_distance")),
        "avg_hr": _int(lap.get("avg_heart_rate")),
        "max_hr": _int(lap.get("max_heart_rate")),
        "avg_speed": _number(lap.get("enhanced_avg_speed") or lap.get("avg_speed")),
        "max_speed": _number(lap.get("enhanced_max_speed") or lap.get("max_speed")),
        "avg_power": _int(lap.get("avg_power")),
        "max_power": _int(lap.get("max_power")),
        "normalized_power": _int(lap.get("normalized_power")),
        "avg_cadence": _number(lap.get("avg_cadence")),
        "ascent_m": _int(lap.get("total_ascent")),
        "descent_m": _int(lap.get("total_descent")),
        "calories": _int(lap.get("total_calories")),
        "intensity": _text(lap.get("intensity")),
        "trigger": _text(lap.get("lap_trigger")),
        "swim_stroke": _text(lap.get("swim_stroke")),
        "active_lengths": _int(lap.get("num_active_lengths")),
        "strokes": _int(lap.get("total_cycles")),
    }


def _length(length: Row) -> Row:
    elapsed = _number(length.get("total_elapsed_time"))
    strokes = _int(length.get("total_strokes"))
    active = _text(length.get("length_type")) != "idle"
    return {
        "started_at": length.get("start_time"),
        "elapsed_s": elapsed,
        "active": active,
        "swim_stroke": _text(length.get("swim_stroke")) if active else None,
        "strokes": strokes,
        "avg_speed": _number(length.get("avg_speed")),
        # SWOLF: seconds plus strokes for the length.
        "swolf": round(elapsed + strokes) if active and elapsed and strokes is not None else None,
    }


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _int(value: Any) -> int | None:
    number = _number(value)
    return round(number) if number is not None else None


def _text(value: Any) -> str | None:
    if isinstance(value, str):
        return value[:32]
    return str(value)[:32] if isinstance(value, int) and not isinstance(value, bool) else None
