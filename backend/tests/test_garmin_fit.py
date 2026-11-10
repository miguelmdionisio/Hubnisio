"""Reading an activity's .FIT file (health/providers/garmin/fit.py), from synthetic files
written by the FIT SDK's encoder with invented values."""

from datetime import UTC, datetime, timedelta

import pytest
from fit_data import Leg, activity_file, zipped

from hubnisio.health.providers.garmin.fit import FitError, fit_bytes, parse_activity_file

START = datetime(2026, 3, 1, 8, 0, tzinfo=UTC)


def test_a_run_becomes_columns_laps_and_zones() -> None:
    data = zipped(
        activity_file(Leg("running", START, 10, power=lambda s: 250 + s, laps=2), skip_seconds=(4,))
    )

    parsed = parse_activity_file(data)

    assert parsed.sport == "running" and parsed.started_at == START
    stream = parsed.stream
    assert stream["time"] == [0, 1, 2, 3, 5, 6, 7, 8, 9]
    assert stream["distance"] is not None and stream["distance"][4] == pytest.approx(15)
    assert stream["heart_rate"] == [150] * 9
    assert stream["speed"] == [pytest.approx(3.0)] * 9
    assert stream["power"] is not None and stream["power"][0] == 250
    assert stream["altitude"] is not None and stream["altitude"][0] == pytest.approx(100, abs=0.2)
    # Strides and their fraction, as steps per minute.
    assert stream["cadence"] == [171.0] * 9
    assert stream["lat"] is not None and stream["lat"][0] == pytest.approx(38.7, abs=1e-6)
    assert stream["lon"] is not None and stream["lon"][0] == pytest.approx(-9.1, abs=1e-6)
    assert stream["vertical_oscillation"] == [80.0] * 9
    assert stream["stance_time"] == [250.0] * 9
    assert stream["step_length"] == [1050.0] * 9
    assert stream["vertical_ratio"] == [7.5] * 9
    assert [lap["lap_index"] for lap in parsed.laps] == [0, 1]
    assert parsed.laps[0]["elapsed_s"] == pytest.approx(4.5)
    assert parsed.laps[0]["trigger"] == "distance"
    assert (parsed.threshold_hr, parsed.max_hr, parsed.rest_hr) == (170, 190, 50)
    assert parsed.lengths == []


def test_a_ride_keeps_its_cadence_and_has_no_power_column() -> None:
    parsed = parse_activity_file(activity_file(Leg("cycling", START, 5, cadence=90)))
    assert parsed.stream["cadence"] == [90.0] * 5
    assert parsed.stream["power"] is None  # none recorded at all
    assert parsed.stream["vertical_oscillation"] is None


def test_a_pool_swim_has_lengths() -> None:
    lengths = ((30.0, True, 16), (40.0, False, 0), (28.0, True, 15))
    parsed = parse_activity_file(
        activity_file(
            Leg("swimming", START, 0, sub_sport="lap_swimming", lengths=lengths, pool_length=25.0)
        )
    )
    assert parsed.pool_length_m == 25.0
    assert parsed.samples == 0
    assert [(n["length_index"], n["active"], n["strokes"]) for n in parsed.lengths] == [
        (0, True, 16),
        (1, False, None),
        (2, True, 15),
    ]
    assert parsed.lengths[0]["swolf"] == 46
    assert parsed.lengths[0]["swim_stroke"] == "freestyle"
    assert parsed.lengths[1]["swolf"] is None


def test_a_multisport_file_keeps_the_leg_asked_for() -> None:
    ride = Leg("cycling", START, 20, heart_rate=lambda _s: 140)
    run = Leg("running", START + timedelta(seconds=60), 10, heart_rate=lambda _s: 160)
    data = activity_file(ride, run)

    second = parse_activity_file(data, START + timedelta(seconds=60))
    assert second.sport == "running" and second.stream["heart_rate"] == [160] * 10
    assert len(second.laps) == 1

    first = parse_activity_file(data, START)
    assert first.sport == "cycling" and first.samples == 20


def test_not_a_fit_file() -> None:
    with pytest.raises(FitError):
        parse_activity_file(b"not a fit file at all")
    with pytest.raises(FitError):
        fit_bytes(b"PK\x03\x04 broken zip")
    assert fit_bytes(b".FIT bytes") == b".FIT bytes"
