"""Invented health data for one member, for the analytics and MCP tests (ADR-0009, H9): about
two months of days, nights and activities, a triathlon with its legs, laps, zones, weigh-ins,
a goal and fitness ages. No overnight heart rate, HRV or SpO2 readings: those stay out of the
views, so the Sleep page's night agrees with the MCP server's without them."""

import uuid
from datetime import UTC, date, datetime, time, timedelta

from analytics_data import save

from hubnisio.health.insights.curves import CURVE_DURATIONS
from hubnisio.health.models import (
    Activity,
    ActivityDerived,
    ActivityLap,
    ActivityStream,
    Connection,
    ConnectionStatus,
    DailySummary,
    FitnessAge,
    HeartRateZones,
    HrvNight,
    ProviderName,
    Sample,
    SampleKind,
    Sleep,
    Weight,
    WeightGoal,
)
from hubnisio.health.sync import today_in

TIME_ZONE = "Europe/Lisbon"
DAYS = 70


def curve(base: float) -> list[float | None]:
    return [round(base + 3000 / t, 2) for t in CURVE_DURATIONS]


async def seed_health(user_id: uuid.UUID) -> date:
    """The member's health data up to their today, which this returns."""
    today = today_in(TIME_ZONE)

    def at(ago: int, hour: int = 7) -> datetime:
        return datetime.combine(today - timedelta(days=ago), time(hour), UTC)

    facts: list[object] = [
        Connection(
            user_id=user_id,
            provider=ProviderName.GARMIN,
            status=ConnectionStatus.ACTIVE,
            key_file="invented.json",
            time_zone=TIME_ZONE,
        ),
        HeartRateZones(user_id=user_id, sport="DEFAULT", zone3_floor=148, max_hr=190),
        HeartRateZones(user_id=user_id, sport="RUNNING", zone3_floor=152, max_hr=192),
        WeightGoal(user_id=user_id, target_kg=68),
    ]
    for ago in range(DAYS):
        day = today - timedelta(days=ago)
        facts.append(
            DailySummary(
                user_id=user_id,
                day=day,
                steps=8000 + ago * 37 % 4000,
                resting_hr=48 + ago % 5,
                stress_avg=25 + ago % 9,
                rest_stress_s=30000,
                low_stress_s=12000 + ago * 60,
                medium_stress_s=4000,
                high_stress_s=900 + ago % 4 * 300,
                body_battery_charged=60 + ago % 20,
                body_battery_drained=55 + ago % 15,
            )
        )
        if ago % 11 == 3:  # a night the watch wasn't worn
            continue
        ended = at(ago, 7) - timedelta(minutes=ago % 40)
        started = ended - timedelta(hours=7, minutes=ago % 50)
        slept = int((ended - started).total_seconds()) - 1800
        facts += [
            Sleep(
                user_id=user_id,
                day=day,
                started_at=started,
                ended_at=ended,
                utc_offset_minutes=0,
                sleep_s=slept,
                deep_s=slept // 6,
                light_s=slept // 2,
                rem_s=slept - slept // 6 - slept // 2,
                awake_s=1800,
                awake_count=1 + ago % 3,
                score=70 + ago % 21,
                score_qualifier="GOOD",
                need_minutes=480,
                avg_hr=50.5,
                avg_respiration=14.2,
                min_respiration=11.0,
                max_respiration=18.5,
                avg_spo2=95.5,
                min_spo2=89,
            ),
            HrvNight(
                user_id=user_id,
                day=day,
                last_night_avg=52 + ago % 7,
                last_night_5min_high=70 + ago % 5,
                status="BALANCED",
            ),
            # Body Battery before the night ends (not counted) and at waking.
            Sample(
                user_id=user_id,
                kind=SampleKind.BODY_BATTERY,
                at=ended - timedelta(minutes=10),
                day=day,
                value=60,
            ),
            Sample(
                user_id=user_id,
                kind=SampleKind.BODY_BATTERY,
                at=ended + timedelta(minutes=2),
                day=day,
                value=70 + ago % 25,
            ),
        ]
    for ago in (2, 30, 60):
        facts += [
            Weight(
                user_id=user_id,
                measured_at=at(ago),
                day=today - timedelta(days=ago),
                weight_kg=70 + ago / 30,
                bmi=22.1,
                body_fat_pct=15.5,
            ),
            FitnessAge(
                user_id=user_id,
                day=today - timedelta(days=ago),
                fitness_age=31.5 - ago / 60,
                chronological_age=38,
                resting_hr=49,
                bmi=22.1,
                vigorous_days_avg=3.5,
                vigorous_minutes_avg=150.0,
            ),
        ]

    activities: list[Activity] = []
    for n, ago in enumerate(range(1, DAYS, 3)):
        sport = ("running", "road_biking", "lap_swimming")[n % 3]
        activities.append(
            Activity(
                user_id=user_id,
                activity_id=1000 + n,
                name=f"Invented {sport} {n}",
                sport=sport,
                started_at=at(ago, 18),
                start_local=datetime.combine(today - timedelta(days=ago), time(18)),
                duration_s=3000 + n * 60,
                distance_m={"running": 10000, "road_biking": 40000, "lap_swimming": 2000}[sport]
                + n * 10,
                elevation_gain_m=50 + n,
                avg_hr=140 + n % 10,
                hr_zone_s=[600, 1200, 900, 300, 0],
                raw={"invented": True},
            )
        )
    # A triathlon: a parent and its three legs.
    activities.append(
        Activity(
            user_id=user_id,
            activity_id=2000,
            name="Invented triathlon",
            sport="multi_sport",
            started_at=at(12, 9),
            duration_s=7200,
            distance_m=51500,
            is_parent=True,
            child_ids=[2001, 2002, 2003],
            raw={},
        )
    )
    for leg, (sport, seconds, metres) in enumerate(
        (
            ("open_water_swimming", 1500, 1500),
            ("road_biking", 3900, 40000),
            ("running", 1800, 10000),
        )
    ):
        activities.append(
            Activity(
                user_id=user_id,
                activity_id=2001 + leg,
                name="Invented triathlon",
                sport=sport,
                started_at=at(12, 9) + timedelta(seconds=leg * 2000),
                duration_s=seconds,
                distance_m=metres,
                avg_hr=150,
                parent_id=2000,
                raw={},
            )
        )
    await save(*facts, *activities)

    derived: list[object] = []
    for activity in activities:
        if activity.is_parent or activity.activity_id % 4 == 3:  # some without a file
            continue
        running = "running" in activity.sport
        swimming = "swimming" in activity.sport
        derived += [
            ActivityDerived(
                user_id=user_id,
                activity_id=activity.activity_id,
                moving_s=int(activity.duration_s or 0) - 30,
                hr_threshold=170,
                hr_load=40.0 + activity.activity_id % 13,
                hr_zone_s=[100, 900, 1000, 600, 300, 100],
                power_curve=curve(250 + activity.activity_id % 7) if running else None,
                hr_curve=curve(150),
                speed_curve=curve(3.5 if running else (1.0 if swimming else 8.0)),
                best_efforts=(
                    {"1000": 230.0, "5000": 1240.0 + activity.activity_id % 9}
                    if running
                    else ({"200": 170.0, "400": 350.0} if swimming else None)
                ),
                efficiency_factor=1.5 + activity.activity_id % 5 / 100 if running else None,
                steady=True if running else None,
                vo2max=49.0 + activity.activity_id % 4 if running else None,
                climbs=[
                    {
                        "start_s": 0,
                        "duration_s": 600,
                        "distance_m": 2000.0,
                        "gain_m": 110.0,
                        "grade": 0.055,
                        "vam": 660.0,
                    }
                ]
                if activity.sport == "road_biking"
                else None,
                best_vam=660.0 if activity.sport == "road_biking" else None,
            ),
            ActivityLap(
                user_id=user_id,
                activity_id=activity.activity_id,
                lap_index=0,
                started_at=activity.started_at,
                elapsed_s=1500.0,
                distance_m=float(activity.distance_m or 0) / 2,
                avg_hr=140,
            ),
            ActivityLap(
                user_id=user_id,
                activity_id=activity.activity_id,
                lap_index=1,
                elapsed_s=1500.0,
                distance_m=float(activity.distance_m or 0) / 2,
                avg_hr=150,
            ),
            # Per-second samples with positions: never in a view.
            ActivityStream(
                user_id=user_id,
                activity_id=activity.activity_id,
                started_at=activity.started_at,
                time_s=[0, 1],
                lat=[38.7, 38.7001],
                lon=[-9.1, -9.1001],
            ),
        ]
    await save(*derived)
    return today
