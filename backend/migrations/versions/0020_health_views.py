"""Health in `analytics` (ADR-0009, slice H9): the member's own health facts for the MCP server.

Health data belongs to one member (health/scoping.py): each view keeps the rows whose user_id
is the member this login acts for (`core.ai_logins`, by `session_user`), never another
member's, not even the owner's of the same household. The raw replies, activity files,
per-second streams (with their GPS positions) and the overnight samples stay out; the one
thing taken from the samples is each night's Body Battery at waking, as the recovery loader
reads it. tests/test_analytics.py checks the views against the scoped queries.

Revision ID: 0020
Revises: 0019
Create Date: 2026-11-11
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0020"
down_revision: str | None = "0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# The member this login acts for, joined on each table's user_id.
_MINE = "JOIN core.ai_logins l ON l.user_id = {alias}.user_id AND l.role_name = session_user::text"


def _mine(alias: str) -> str:
    return _MINE.format(alias=alias)


# Each view with its comment, in creation order.
VIEWS: list[tuple[str, str, str]] = [
    (
        "health_connection",
        "The member's own Garmin link, if any: its status, their time zone (an IANA name: what "
        "today is for them) and the last sync. Never the key.",
        f"""
        SELECT c.provider::text AS provider, c.status::text AS status, c.time_zone,
               c.key_expires_on, c.created_at, c.last_synced_at
        FROM health.connections c
        {_mine("c")}
        """,  # noqa: S608 (constants only)
    ),
    (
        "health_activities",
        "The member's own activities, Garmin's summary and what Hubnisio derived from each "
        "one's file (null without a file). Units: s, m, m/s, bpm, W; cadence in steps/min for "
        "runs, rpm for rides. A multisport parent (is_parent) has legs (parent_id) that are "
        "activities of their own: totals count the legs, never the parent. day: the local "
        "start's date. duration_s is Garmin's; derived_moving_s is from the file. hr_zone_s: "
        "seconds in Garmin's five zones; derived_hr_zone_s: below zone 1, then zones 1 to 5. "
        "hr_load: an hrTSS-style load. Curves are best averages for the durations of "
        "health/insights/curves.py; best_efforts: seconds by distance in metres; vo2max: "
        "Hubnisio's estimate; climbs: distance_m, gain_m, duration_s, grade, vam.",
        f"""
        SELECT a.activity_id, a.name, a.sport, a.event_type, a.started_at, a.start_local,
               coalesce(a.start_local, a.started_at AT TIME ZONE 'UTC')::date AS day,
               a.time_zone, a.duration_s, a.elapsed_s, a.moving_s, a.distance_m,
               a.elevation_gain_m, a.elevation_loss_m, a.min_elevation_m, a.max_elevation_m,
               a.avg_hr, a.max_hr, a.avg_speed, a.max_speed, a.avg_gap_speed, a.avg_power,
               a.max_power, a.norm_power, a.avg_cadence, a.max_cadence, a.calories, a.steps,
               a.garmin_load, a.aerobic_te, a.anaerobic_te, a.te_label, a.moderate_minutes,
               a.vigorous_minutes, a.body_battery_change, a.hr_zone_s, a.power_zone_s,
               a.ground_contact_ms, a.vertical_oscillation_cm, a.vertical_ratio_pct,
               a.stride_length_cm, a.pool_length_m, a.active_lengths, a.strokes, a.avg_strokes,
               a.avg_swolf, a.avg_stroke_distance_m, a.fastest_splits, a.lap_count, a.manual,
               a.is_parent, a.parent_id, a.child_ids,
               d.activity_id IS NOT NULL AS has_derived,
               d.moving_s AS derived_moving_s, d.hr_threshold, d.hr_max, d.hr_rest,
               d.hr_reference_source, d.hr_load, d.hr_zone_s AS derived_hr_zone_s,
               d.power_curve, d.hr_curve, d.speed_curve, d.best_efforts, d.gap_speed,
               d.ngp_speed, d.efficiency_factor, d.decoupling_pct, d.steady, d.vo2max, d.climbs,
               d.best_vam
        FROM health.activities a
        {_mine("a")}
        LEFT JOIN health.activity_derived d
            ON d.user_id = a.user_id AND d.activity_id = a.activity_id
        """,  # noqa: S608 (constants only)
    ),
    (
        "health_activity_laps",
        "The laps in the member's own activities' files. Units: s, m, m/s, bpm, W.",
        f"""
        SELECT p.activity_id, p.lap_index, p.started_at, p.elapsed_s, p.timer_s, p.distance_m,
               p.avg_hr, p.max_hr, p.avg_speed, p.max_speed, p.avg_power, p.max_power,
               p.normalized_power, p.avg_cadence, p.ascent_m, p.descent_m, p.calories,
               p.intensity, p.trigger, p.swim_stroke, p.active_lengths, p.strokes
        FROM health.activity_laps p
        {_mine("p")}
        """,  # noqa: S608 (constants only)
    ),
    (
        "health_daily_summaries",
        "The member's own days: steps, distance (m), calories, resting heart rate (bpm), "
        "intensity minutes, stress (0 to 100; seconds per level), Body Battery charged and "
        "drained, SpO2 (%) and respiration (breaths/min).",
        f"""
        SELECT s.day, s.steps, s.step_goal, s.distance_m, s.floors_ascended, s.active_kcal,
               s.resting_kcal, s.total_kcal, s.resting_hr, s.min_hr, s.max_hr,
               s.moderate_minutes, s.vigorous_minutes, s.stress_avg, s.stress_max,
               s.rest_stress_s, s.low_stress_s, s.medium_stress_s, s.high_stress_s,
               s.body_battery_charged, s.body_battery_drained, s.body_battery_min,
               s.body_battery_max, s.spo2_avg, s.spo2_min, s.respiration_avg,
               s.respiration_min, s.respiration_max, s.includes_wellness
        FROM health.daily_summaries s
        {_mine("s")}
        """,  # noqa: S608 (constants only)
    ),
    (
        "health_sleeps",
        "The member's own nights, each under the day it ends. Seconds per stage; "
        "need_minutes: Garmin's sleep need; score 0 to 100; utc_offset_minutes: local time "
        "less UTC. A night with no time slept is a night the watch wasn't worn.",
        f"""
        SELECT s.day, s.started_at, s.ended_at, s.utc_offset_minutes, s.sleep_s, s.deep_s,
               s.light_s, s.rem_s, s.awake_s, s.unmeasurable_s, s.nap_s, s.awake_count, s.score,
               s.score_qualifier, s.need_minutes, s.avg_hr, s.avg_respiration,
               s.min_respiration, s.max_respiration, s.avg_spo2, s.min_spo2, s.avg_sleep_stress,
               s.from_device
        FROM health.sleeps s
        {_mine("s")}
        """,  # noqa: S608 (constants only)
    ),
    (
        "health_hrv_nights",
        "The member's own overnight HRV (ms): the night's average and 5-minute high, Garmin's "
        "weekly average, status and baseline.",
        f"""
        SELECT h.day, h.last_night_avg, h.last_night_5min_high, h.weekly_avg, h.status,
               h.baseline_low_upper, h.baseline_balanced_low, h.baseline_balanced_upper
        FROM health.hrv_nights h
        {_mine("h")}
        """,  # noqa: S608 (constants only)
    ),
    (
        "health_wake_battery",
        "The member's own Body Battery at waking (0 to 100): the first reading of a night's "
        "day at or after the night's end.",
        f"""
        SELECT DISTINCT ON (s.day) s.day, b.value AS body_battery
        FROM health.sleeps s
        {_mine("s")}
        JOIN health.samples b
            ON b.user_id = s.user_id AND b.day = s.day AND b.at >= s.ended_at
            AND b.kind = 'body_battery'
        ORDER BY s.day, b.at
        """,  # noqa: S608 (constants only)
    ),
    (
        "health_heart_rate_zones",
        "The member's own heart-rate zones per sport (floors in bpm), with their maximum, "
        "resting and lactate threshold heart rates.",
        f"""
        SELECT z.sport, z.training_method, z.max_hr, z.lactate_threshold_hr, z.resting_hr,
               z.zone1_floor, z.zone2_floor, z.zone3_floor, z.zone4_floor, z.zone5_floor
        FROM health.heart_rate_zones z
        {_mine("z")}
        """,  # noqa: S608 (constants only)
    ),
    (
        "health_weights",
        "The member's own weigh-ins (kg, %).",
        f"""
        SELECT w.measured_at, w.day, w.weight_kg, w.bmi, w.body_fat_pct, w.body_water_pct,
               w.muscle_mass_kg, w.bone_mass_kg, w.source
        FROM health.weights w
        {_mine("w")}
        """,  # noqa: S608 (constants only)
    ),
    (
        "health_weight_goal",
        "The member's own weight goal (kg), if they set one.",
        f"""
        SELECT g.target_kg, g.starts_on
        FROM health.weight_goals g
        {_mine("g")}
        """,  # noqa: S608 (constants only)
    ),
    (
        "health_fitness_ages",
        "The member's own fitness age as Garmin read it on a day, with what it was drawn from.",
        f"""
        SELECT f.day, f.fitness_age, f.previous_fitness_age, f.chronological_age, f.resting_hr,
               f.bmi, f.vigorous_days_avg, f.vigorous_minutes_avg
        FROM health.fitness_ages f
        {_mine("f")}
        """,  # noqa: S608 (constants only)
    ),
]


def upgrade() -> None:
    for name, comment, query in VIEWS:
        op.execute(f"CREATE VIEW analytics.{name} WITH (security_barrier) AS {query}")
        op.execute(f"COMMENT ON VIEW analytics.{name} IS '{comment.replace("'", "''")}'")
        op.execute(f"GRANT SELECT ON analytics.{name} TO hub_ai")


def downgrade() -> None:
    for name, _, _ in reversed(VIEWS):
        op.execute(f"DROP VIEW analytics.{name}")
