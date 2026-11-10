"""Synthetic .FIT files for the health tests, written with Garmin's FIT SDK encoder. Every value
is invented: steady speeds and heart rates that make the derived results easy to check."""

import io
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

from garmin_fit_sdk import Encoder, Profile

MESG = Profile["mesg_num"]
DEGREE = 2**31 / 180  # semicircles per degree


@dataclass(frozen=True)
class Leg:
    """One session: `seconds` of records at one a second from `start`."""

    sport: str  # FIT sport: running, cycling, swimming
    start: datetime
    seconds: int
    speed: float = 3.0  # m/s
    heart_rate: Callable[[int], int | None] = lambda _s: 150
    power: Callable[[int], int | None] = lambda _s: None
    altitude: Callable[[int], float | None] = lambda _s: 100.0
    cadence: int | None = 85  # the file's cadence: strides per minute for a run
    sub_sport: str = "generic"
    laps: int = 1
    # Pool lengths: (seconds, active, strokes) each. A pool swim has no records.
    lengths: tuple[tuple[float, bool, int], ...] = ()
    pool_length: float | None = None


def activity_file(
    *legs: Leg,
    threshold_hr: int | None = 170,
    max_hr: int | None = 190,
    rest_hr: int | None = 50,
    skip_seconds: tuple[int, ...] = (),
) -> bytes:
    """A FIT activity file with a session (laps, records, lengths) per leg."""
    encoder = Encoder()
    first = legs[0].start
    encoder.write_mesg(
        {
            "mesg_num": MESG["FILE_ID"],
            "type": "activity",
            "manufacturer": "development",
            "time_created": first,
        }
    )
    for index, leg in enumerate(legs):
        if leg.lengths:
            _lengths(encoder, leg)
            elapsed = sum(seconds for seconds, _, _ in leg.lengths)
        else:
            _records(encoder, leg, skip_seconds)
            elapsed = leg.seconds - 1
        per_lap = elapsed / leg.laps
        for lap in range(leg.laps):
            lap_start = leg.start + timedelta(seconds=per_lap * lap)
            encoder.write_mesg(
                {
                    "mesg_num": MESG["LAP"],
                    "message_index": lap,
                    "timestamp": lap_start + timedelta(seconds=per_lap),
                    "start_time": lap_start,
                    "total_elapsed_time": per_lap,
                    "total_timer_time": per_lap,
                    "total_distance": leg.speed * per_lap,
                    "avg_heart_rate": 150,
                    "sport": leg.sport,
                    "intensity": "active",
                    "lap_trigger": "distance",
                }
            )
        session = {
            "mesg_num": MESG["SESSION"],
            "message_index": index,
            "timestamp": leg.start + timedelta(seconds=elapsed),
            "start_time": leg.start,
            "total_elapsed_time": float(elapsed),
            "total_timer_time": float(elapsed),
            "sport": leg.sport,
            "sub_sport": leg.sub_sport,
        }
        if leg.pool_length is not None:
            session["pool_length"] = leg.pool_length
        encoder.write_mesg(session)
        zones = {
            "mesg_num": MESG["TIME_IN_ZONE"],
            "timestamp": leg.start + timedelta(seconds=elapsed),
            "reference_mesg": "session",
            "reference_index": index,
        }
        for name, value in (
            ("threshold_heart_rate", threshold_hr),
            ("max_heart_rate", max_hr),
            ("resting_heart_rate", rest_hr),
        ):
            if value is not None:
                zones[name] = value
        encoder.write_mesg(zones)
    return encoder.close()


def zipped(fit: bytes, name: str = "123_ACTIVITY.fit") -> bytes:
    """As Garmin's download sends it: a zip holding the one file."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(name, fit)
    return buffer.getvalue()


def _records(encoder: Encoder, leg: Leg, skip: tuple[int, ...]) -> None:
    for second in range(leg.seconds):
        if second in skip:
            continue
        record: dict[str, object] = {
            "mesg_num": MESG["RECORD"],
            "timestamp": leg.start + timedelta(seconds=second),
            "distance": leg.speed * second,
            "enhanced_speed": leg.speed,
            "position_lat": round((38.7 + second * 1e-5) * DEGREE),
            "position_long": round(-9.1 * DEGREE),
        }
        for name, value in (
            ("heart_rate", leg.heart_rate(second)),
            ("power", leg.power(second)),
            ("enhanced_altitude", leg.altitude(second)),
            ("cadence", leg.cadence),
        ):
            if value is not None:
                record[name] = value
        if leg.sport == "running":
            record |= {
                "fractional_cadence": 0.5,
                "vertical_oscillation": 80.0,
                "stance_time": 250.0,
                "step_length": 1050.0,
                "vertical_ratio": 7.5,
            }
        encoder.write_mesg(record)


def _lengths(encoder: Encoder, leg: Leg) -> None:
    at = leg.start
    for index, (seconds, active, strokes) in enumerate(leg.lengths):
        length: dict[str, object] = {
            "mesg_num": MESG["LENGTH"],
            "message_index": index,
            "timestamp": at + timedelta(seconds=seconds),
            "start_time": at,
            "total_elapsed_time": seconds,
            "total_timer_time": seconds,
            "length_type": "active" if active else "idle",
        }
        if active:
            length |= {
                "swim_stroke": "freestyle",
                "total_strokes": strokes,
                "avg_speed": (leg.pool_length or 25.0) / seconds,
            }
        encoder.write_mesg(length)
        at += timedelta(seconds=seconds)
