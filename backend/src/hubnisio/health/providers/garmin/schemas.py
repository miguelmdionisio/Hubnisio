"""The parts of Garmin's replies that are normalized (ADR-0009). Field names follow
docs/design/m8-garmin-shapes.json. Every field is optional and unknown fields are kept out:
Garmin leaves out or nulls whatever the watch didn't measure, and the raw reply is stored anyway.
"""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class _Model(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)


# Daily summaries: GET /usersummary-service/v2/dailysummaries -> {"data": [DailySummary]}


class _Value(_Model):
    value: float | None = None
    goal: float | None = None
    distance_in_meters: float | None = Field(None, alias="distanceInMeters")


class _Movement(_Model):
    steps: _Value | None = None
    floors_ascended: _Value | None = Field(None, alias="floorsAscended")


class _Calories(_Model):
    burned_active: float | None = Field(None, alias="burnedActive")
    burned_resting: float | None = Field(None, alias="burnedResting")
    burned_total: float | None = Field(None, alias="burnedTotal")


class _Range(_Model):
    avg_value: float | None = Field(None, alias="avgValue")
    min_value: float | None = Field(None, alias="minValue")
    max_value: float | None = Field(None, alias="maxValue")
    resting_value: float | None = Field(None, alias="restingValue")


class _Intensity(_Model):
    moderate: float | None = None
    vigorous: float | None = None


class _DayStress(_Model):
    avg_level: float | None = Field(None, alias="avgLevel")
    max_level: float | None = Field(None, alias="maxLevel")
    rest_ms: float | None = Field(None, alias="restDurationInMillis")
    low_ms: float | None = Field(None, alias="lowStressDurationInMillis")
    medium_ms: float | None = Field(None, alias="mediumStressDurationInMillis")
    high_ms: float | None = Field(None, alias="highStressDurationInMillis")


class _DayBodyBattery(_Model):
    charged: float | None = Field(None, alias="chargedValue")
    drained: float | None = Field(None, alias="drainedValue")
    min_value: float | None = Field(None, alias="minValue")
    max_value: float | None = Field(None, alias="maxValue")


class DailySummary(_Model):
    calendar_date: str | None = Field(None, alias="calendarDate")
    movement: _Movement | None = None
    calories: _Calories | None = None
    heart_rate: _Range | None = Field(None, alias="heartRate")
    intensity_minutes: _Intensity | None = Field(None, alias="intensityMinutes")
    stress: _DayStress | None = None
    body_battery: _DayBodyBattery | None = Field(None, alias="bodyBattery")
    pulse_ox: _Range | None = Field(None, alias="pulseOx")
    respiration: _Range | None = None
    includes_wellness_data: bool | None = Field(None, alias="includesWellnessData")


class DailySummaries(_Model):
    data: list[DailySummary] = []


# Sleep: GET /sleep-service/sleep/dailySleepSummariesByDate -> [SleepSummary]


class _Score(_Model):
    value: float | None = None
    qualifier_key: str | None = Field(None, alias="qualifierKey")


class _SleepScores(_Model):
    overall: _Score | None = None


class _SleepNeed(_Model):
    actual: float | None = None


class SleepSummary(_Model):
    id: int | None = None
    calendar_date: str | None = Field(None, alias="calendarDate")
    start_gmt: int | None = Field(None, alias="sleepStartTimestampGMT")
    end_gmt: int | None = Field(None, alias="sleepEndTimestampGMT")
    start_local: int | None = Field(None, alias="sleepStartTimestampLocal")
    sleep_seconds: float | None = Field(None, alias="sleepTimeSeconds")
    deep_seconds: float | None = Field(None, alias="deepSleepSeconds")
    light_seconds: float | None = Field(None, alias="lightSleepSeconds")
    rem_seconds: float | None = Field(None, alias="remSleepSeconds")
    awake_seconds: float | None = Field(None, alias="awakeSleepSeconds")
    unmeasurable_seconds: float | None = Field(None, alias="unmeasurableSleepSeconds")
    nap_seconds: float | None = Field(None, alias="napTimeSeconds")
    awake_count: float | None = Field(None, alias="awakeCount")
    sleep_scores: _SleepScores | None = Field(None, alias="sleepScores")
    sleep_need: _SleepNeed | None = Field(None, alias="sleepNeed")
    avg_heart_rate: float | None = Field(None, alias="avgHeartRate")
    average_respiration: float | None = Field(None, alias="averageRespirationValue")
    lowest_respiration: float | None = Field(None, alias="lowestRespirationValue")
    highest_respiration: float | None = Field(None, alias="highestRespirationValue")
    average_spo2: float | None = Field(None, alias="averageSpO2Value")
    lowest_spo2: float | None = Field(None, alias="lowestSpO2Value")
    avg_sleep_stress: float | None = Field(None, alias="avgSleepStress")
    sleep_from_device: bool | None = Field(None, alias="sleepFromDevice")


# HRV: GET /hrv-service/hrv/daily/{from}/{to} -> {"hrvSummaries": [HrvSummary]};
# GET /hrv-service/hrv/{day} -> HrvDay


class _Baseline(_Model):
    low_upper: float | None = Field(None, alias="lowUpper")
    balanced_low: float | None = Field(None, alias="balancedLow")
    balanced_upper: float | None = Field(None, alias="balancedUpper")


class HrvSummary(_Model):
    calendar_date: str | None = Field(None, alias="calendarDate")
    last_night_avg: float | None = Field(None, alias="lastNightAvg")
    last_night_5min_high: float | None = Field(None, alias="lastNight5MinHigh")
    weekly_avg: float | None = Field(None, alias="weeklyAvg")
    status: str | None = None
    baseline: _Baseline | None = None


class HrvRange(_Model):
    hrv_summaries: list[HrvSummary] = Field([], alias="hrvSummaries")


class HrvReading(_Model):
    hrv_value: float | None = Field(None, alias="hrvValue")
    reading_time_gmt: str | None = Field(None, alias="readingTimeGMT")


class HrvDay(_Model):
    hrv_summary: HrvSummary | None = Field(None, alias="hrvSummary")
    hrv_readings: list[HrvReading] | None = Field(None, alias="hrvReadings")


# Body Battery: GET /wellness-service/wellness/bodyBattery/reports/daily -> [BodyBatteryDay]


class _BodyBatteryDescriptor(_Model):
    index: int | None = Field(None, alias="bodyBatteryValueDescriptorIndex")
    key: str | None = Field(None, alias="bodyBatteryValueDescriptorKey")


class BodyBatteryDay(_Model):
    date: str | None = None
    charged: float | None = None
    drained: float | None = None
    descriptors: list[_BodyBatteryDescriptor] | None = Field(
        None, alias="bodyBatteryValueDescriptorDTOList"
    )
    values: list[list[Any]] | None = Field(None, alias="bodyBatteryValuesArray")


# Stress and steps: GET /usersummary-service/stats/{stress,steps}/daily/{from}/{to}


class _StressValues(_Model):
    overall_stress_level: float | None = Field(None, alias="overallStressLevel")
    rest_seconds: float | None = Field(None, alias="restStressDuration")
    low_seconds: float | None = Field(None, alias="lowStressDuration")
    medium_seconds: float | None = Field(None, alias="mediumStressDuration")
    high_seconds: float | None = Field(None, alias="highStressDuration")


class StressDay(_Model):
    calendar_date: str | None = Field(None, alias="calendarDate")
    values: _StressValues | None = None


class StepsDay(_Model):
    calendar_date: str | None = Field(None, alias="calendarDate")
    total_steps: float | None = Field(None, alias="totalSteps")
    step_goal: float | None = Field(None, alias="stepGoal")
    total_distance: float | None = Field(None, alias="totalDistance")


# Heart rate: GET /wellness-service/wellness/dailyHeartRate?date


class _IndexKey(_Model):
    index: int | None = None
    key: str | None = None


class HeartRateDay(_Model):
    calendar_date: str | None = Field(None, alias="calendarDate")
    descriptors: list[_IndexKey] | None = Field(None, alias="heartRateValueDescriptors")
    values: list[list[Any]] | None = Field(None, alias="heartRateValues")


# SpO2: GET /wellness-service/wellness/daily/spo2acclimation/{day}


class _Spo2Descriptor(_Model):
    index: int | None = Field(None, alias="spo2ValueDescIndex")
    key: str | None = Field(None, alias="spo2ValueDescKey")


class Spo2Day(_Model):
    calendar_date: str | None = Field(None, alias="calendarDate")
    descriptors: list[_Spo2Descriptor] | None = Field(
        None, alias="spO2HourlyAveragesDescriptorList"
    )
    hourly: list[list[Any]] | None = Field(None, alias="spO2HourlyAverages")


# Heart-rate zones: GET /biometric-service/heartRateZones/v2 -> [Zones]


class Zones(_Model):
    sport: str | None = None
    training_method: str | None = Field(None, alias="trainingMethod")
    max_hr: float | None = Field(None, alias="maxHeartRateUsed")
    lactate_threshold_hr: float | None = Field(None, alias="lactateThresholdHeartRateUsed")
    resting_hr: float | None = Field(None, alias="restingHeartRateUsed")
    zone1_floor: float | None = Field(None, alias="zone1Floor")
    zone2_floor: float | None = Field(None, alias="zone2Floor")
    zone3_floor: float | None = Field(None, alias="zone3Floor")
    zone4_floor: float | None = Field(None, alias="zone4Floor")
    zone5_floor: float | None = Field(None, alias="zone5Floor")


# Fitness age: GET /fitnessage-service/fitnessage/v2/{day}


class _Component(_Model):
    value: float | None = None


class _FitnessComponents(_Model):
    rhr: _Component | None = None
    bmi: _Component | None = None
    vigorous_days_avg: _Component | None = Field(None, alias="vigorousDaysAvg")
    vigorous_minutes_avg: _Component | None = Field(None, alias="vigorousMinutesAvg")


class FitnessAgeReply(_Model):
    fitness_age: float | None = Field(None, alias="fitnessAge")
    previous_fitness_age: float | None = Field(None, alias="previousFitnessAge")
    chronological_age: float | None = Field(None, alias="chronologicalAge")
    components: _FitnessComponents | None = None


# Profile: GET /userprofile-service/userprofile/settings (only the time zone is used)


class Profile(_Model):
    time_zone: str | None = Field(None, alias="timeZone")
