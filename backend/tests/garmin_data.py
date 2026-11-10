"""A fake Garmin Connect Personal API for the health tests. Its replies follow the shapes in
docs/design/m8-garmin-shapes.json; every value is invented, made from the day asked for."""

import base64
import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any

import httpx

TOKEN_PATH = "/personalapitoken-service/personal-api/personal-api-key/token"  # noqa: S105
KEY = "key-1"
TIME_ZONE = "Europe/Lisbon"


def jwt(exp: float, signature: str = "c2ln") -> str:
    """An unsigned JWT with an `exp` claim, as Garmin's token reply holds (as plain text)."""

    def part(value: dict[str, Any]) -> str:
        return base64.urlsafe_b64encode(json.dumps(value).encode()).decode().rstrip("=")

    return (
        f"{part({'alg': 'RS256', 'typ': 'JWT'})}.{part({'exp': int(exp), 'sub': 'x'})}.{signature}"
    )


def ms(moment: datetime) -> int:
    return int(moment.timestamp() * 1000)


def gmt(moment: datetime) -> str:
    """Garmin's GMT times: ISO without a zone."""
    return moment.astimezone(UTC).replace(tzinfo=None).isoformat(timespec="milliseconds")[:-2]


def days(start: date, end: date) -> list[date]:
    return [start + timedelta(days=n) for n in range((end - start).days + 1)]


def _n(day: date) -> int:
    """A small number that changes from day to day."""
    return day.toordinal() % 7


def night(day: date) -> tuple[datetime, datetime]:
    """The night ending on `day`: 23:00 to 07:00 UTC."""
    start = datetime(day.year, day.month, day.day, tzinfo=UTC) - timedelta(hours=1)
    return start, start + timedelta(hours=8)


def daily_summary(day: date) -> dict[str, Any]:
    n = _n(day)
    return {
        "calendarDate": day.isoformat(),
        "uuid": f"u-{day.isoformat()}",
        "userProfilePk": 1,
        "source": "WATCH",
        "includesActivityData": True,
        "includesWellnessData": True,
        "movement": {
            "steps": {"value": 8000 + n, "goal": 10000, "distanceInMeters": 6100.5 + n},
            "floorsAscended": {"value": 7, "goal": 10, "distanceInMeters": 21.0},
            "floorsDescended": {"value": 6, "distanceInMeters": 18.0},
            "pushes": {},
        },
        "calories": {"burnedActive": 600 + n, "burnedResting": 1700, "burnedTotal": 2300 + n},
        "heartRate": {"restingValue": 48 + n, "minValue": 45, "maxValue": 160},
        "intensityMinutes": {"goal": 150, "moderate": 20, "vigorous": 15 + n},
        "stress": {
            "avgLevel": 30 + n,
            "maxLevel": 90,
            "restDurationInMillis": 36_000_000,
            "lowStressDurationInMillis": 18_000_000,
            "mediumStressDurationInMillis": 7_200_000,
            "highStressDurationInMillis": 1_800_000,
            "qualifier": "BALANCED",
        },
        "bodyBattery": {
            "chargedValue": 60,
            "drainedValue": 55 + n,
            "minValue": 20,
            "maxValue": 85,
            "latestValue": 40,
            "activityEvents": [],
        },
        "pulseOx": {"avgValue": 95, "minValue": 89, "latestValue": 96},
        "respiration": {"avgValue": 14, "minValue": 10, "maxValue": 20, "latestValue": 13},
        "hydration": {"goalInMl": 2000, "consumedInMl": 0},
        "jetLag": {},
    }


def sleep_summary(day: date) -> dict[str, Any]:
    start, end = night(day)
    n = _n(day)
    need = {"actual": 480, "baseline": 480, "calendarDate": day.isoformat(), "feedback": "NONE"}
    return {
        "id": 1000 + day.toordinal(),
        "calendarDate": day.isoformat(),
        "sleepStartTimestampGMT": ms(start),
        "sleepEndTimestampGMT": ms(end),
        "sleepStartTimestampLocal": ms(start) + 3_600_000,
        "sleepEndTimestampLocal": ms(end) + 3_600_000,
        "sleepTimeSeconds": 27_000 + n,
        "deepSleepSeconds": 5_400,
        "lightSleepSeconds": 14_400,
        "remSleepSeconds": 7_200 + n,
        "awakeSleepSeconds": 1_800,
        "unmeasurableSleepSeconds": 0,
        "napTimeSeconds": 0,
        "awakeCount": 2,
        "avgHeartRate": 50.5,
        "averageRespirationValue": 13.5,
        "lowestRespirationValue": 9.0,
        "highestRespirationValue": 18.0,
        "averageSpO2Value": 94.5,
        "lowestSpO2Value": 88,
        "highestSpO2Value": 99,
        "avgSleepStress": 12.5,
        "sleepFromDevice": True,
        "sleepScores": {"overall": {"value": 80 + n, "qualifierKey": "GOOD"}},
        "sleepNeed": need,
        "nextSleepNeed": need,
        "dailyNapDTOS": None,
        "userNote": None,
    }


def hrv_summary(day: date) -> dict[str, Any]:
    return {
        "calendarDate": day.isoformat(),
        "lastNightAvg": 60 + _n(day),
        "lastNight5MinHigh": 85,
        "weeklyAvg": 62,
        "status": "BALANCED",
        "feedbackPhrase": "HRV_BALANCED_1",
        "createTimeStamp": gmt(night(day)[1]),
        "baseline": {"lowUpper": 50, "balancedLow": 55, "balancedUpper": 70, "markerValue": 0.4},
    }


def hrv_day(day: date) -> dict[str, Any]:
    start, end = night(day)
    readings = [
        {
            "hrvValue": 55 + i,
            "readingTimeGMT": gmt(start + timedelta(minutes=5 * i)),
            "readingTimeLocal": gmt(start + timedelta(minutes=5 * i, hours=1)),
        }
        for i in range(4)
    ]
    summary = hrv_summary(day) | {"weeklyAvg": None}
    return {
        "userProfilePk": 1,
        "hrvSummary": summary,
        "hrvReadings": readings,
        "startTimestampGMT": gmt(start),
        "endTimestampGMT": gmt(end),
        "sleepStartTimestampGMT": gmt(start),
        "sleepEndTimestampGMT": gmt(end),
    }


def body_battery(day: date) -> dict[str, Any]:
    start = datetime(day.year, day.month, day.day, tzinfo=UTC)
    return {
        "date": day.isoformat(),
        "charged": 61,
        "drained": 50,
        "startTimestampGMT": gmt(start),
        "endTimestampGMT": gmt(start + timedelta(days=1)),
        "bodyBatteryValueDescriptorDTOList": [
            {"bodyBatteryValueDescriptorIndex": 0, "bodyBatteryValueDescriptorKey": "timestamp"},
            {
                "bodyBatteryValueDescriptorIndex": 1,
                "bodyBatteryValueDescriptorKey": "bodyBatteryStatus",
            },
            {
                "bodyBatteryValueDescriptorIndex": 2,
                "bodyBatteryValueDescriptorKey": "bodyBatteryLevel",
            },
        ],
        "bodyBatteryValuesArray": [[ms(start + timedelta(hours=h)), 1, 40 + h] for h in range(3)],
        "bodyBatteryActivityEvent": [],
    }


def stress_day(day: date) -> dict[str, Any]:
    return {
        "calendarDate": day.isoformat(),
        "values": {
            "overallStressLevel": 33,
            "restStressDuration": 30_000,
            "lowStressDuration": 20_000,
            "mediumStressDuration": 5_000,
            "highStressDuration": 1_000,
        },
    }


def steps_day(day: date) -> dict[str, Any]:
    return {
        "calendarDate": day.isoformat(),
        "totalSteps": 9999,
        "stepGoal": 9000,
        "totalDistance": 7000,
    }


def heart_rate_day(day: date) -> dict[str, Any]:
    start = datetime(day.year, day.month, day.day, tzinfo=UTC)
    return {
        "calendarDate": day.isoformat(),
        "userProfilePK": 1,
        "restingHeartRate": 48,
        "minHeartRate": 45,
        "maxHeartRate": 160,
        "heartRateValueDescriptors": [
            {"index": 0, "key": "timestamp"},
            {"index": 1, "key": "heartrate"},
        ],
        # A gap shows as null.
        "heartRateValues": [
            [ms(start + timedelta(minutes=2 * i)), None if i == 2 else 50 + i] for i in range(5)
        ],
    }


def spo2_day(day: date) -> dict[str, Any]:
    start, end = night(day)
    return {
        "calendarDate": day.isoformat(),
        "averageSpO2": 95.0,
        "lowestSpO2": 89,
        "sleepStartTimestampGMT": gmt(start),
        "sleepEndTimestampGMT": gmt(end),
        "spO2HourlyAveragesDescriptorList": [
            {"spo2ValueDescIndex": 0, "spo2ValueDescKey": "timestamp"},
            {"spo2ValueDescIndex": 1, "spo2ValueDescKey": "spo2Reading"},
        ],
        "spO2HourlyAverages": [[ms(start + timedelta(hours=h)), 93 + h] for h in range(3)],
        "spO2SingleValues": None,
    }


def zones() -> list[dict[str, Any]]:
    return [
        {
            "sport": sport,
            "trainingMethod": "HR_RESERVE",
            "maxHeartRateUsed": 190,
            "lactateThresholdHeartRateUsed": 170,
            "restingHeartRateUsed": None,
            "restingHrAutoUpdateUsed": True,
            "zone1Floor": 110,
            "zone2Floor": 130,
            "zone3Floor": 150,
            "zone4Floor": 165,
            "zone5Floor": 178,
        }
        for sport in ("DEFAULT", "RUNNING")
    ]


def fitness_age() -> dict[str, Any]:
    return {
        "chronologicalAge": 40,
        "fitnessAge": 33.5,
        "previousFitnessAge": 34.0,
        "lastUpdated": "2026-01-01T00:00:00.0",
        "components": {
            "rhr": {"value": 48, "stale": False},
            "bmi": {"value": 22.4, "stale": False},
            "vigorousDaysAvg": {"value": 3.5, "stale": False},
            "vigorousMinutesAvg": {"value": 150.0, "stale": False},
        },
    }


def weight_range(start: date, end: date, weigh_ins: list[date]) -> dict[str, Any]:
    summaries = [
        {
            "summaryDate": day.isoformat(),
            "numOfWeightEntries": 1,
            "allWeightMetrics": [
                {
                    "samplePk": day.toordinal(),
                    "calendarDate": day.isoformat(),
                    "timestampGMT": ms(datetime(day.year, day.month, day.day, 7, tzinfo=UTC)),
                    "weight": 70_500.0,
                    "bmi": 22.1,
                    "bodyFat": 15.5,
                    "bodyWater": 60.1,
                    "muscleMass": 32_000,
                    "boneMass": 3_100,
                    "sourceType": "INDEX_SCALE",
                }
            ],
        }
        for day in weigh_ins
        if start <= day <= end
    ]
    return {
        "dailyWeightSummaries": summaries,
        "totalAverage": {},
        "previousDateWeight": {},
        "nextDateWeight": {},
    }


def profile() -> dict[str, Any]:
    return {"displayName": "someone", "timeZone": TIME_ZONE, "measurementSystem": "metric"}


Handler = Callable[[httpx.Request], httpx.Response]


@dataclass
class FakeGarmin:
    """Answers like Garmin. `fail` maps a payload kind to a status code to answer it with;
    `queued` holds responses answered first, whatever the request."""

    now: Callable[[], float] = lambda: datetime.now(UTC).timestamp()
    key: str = KEY
    weigh_ins: list[date] = field(default_factory=list[date])
    weight_goal_kg: float | None = None
    fail: dict[str, int] = field(default_factory=dict[str, int])
    queued: list[httpx.Response] = field(default_factory=list[httpx.Response])
    requests: list[httpx.Request] = field(default_factory=list[httpx.Request])
    tokens: list[str] = field(default_factory=list[str])

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.queued:
            return self.queued.pop(0)
        auth = request.headers.get("authorization", "")
        if request.url.path == TOKEN_PATH:
            if request.method != "POST" or auth != f"ApiKey {self.key}":
                return httpx.Response(401)
            token = jwt(self.now() + 86_400, f"sig{len(self.tokens)}")
            self.tokens.append(token)
            return httpx.Response(200, text=token, headers={"content-type": "text/plain"})
        if not self.tokens or auth != f"Bearer {self.tokens[-1]}":
            return httpx.Response(401)
        kind, body = self.route(request)
        if kind in self.fail:
            return httpx.Response(self.fail[kind], json={"message": "invented failure"})
        return httpx.Response(200, json=body)

    def route(self, request: httpx.Request) -> tuple[str, Any]:
        path, params = request.url.path, request.url.params

        def span() -> list[date]:
            return days(
                date.fromisoformat(params["startDate"]), date.fromisoformat(params["endDate"])
            )

        def tail_span() -> tuple[date, date]:
            first, last = path.rsplit("/", 2)[-2:]
            return date.fromisoformat(first), date.fromisoformat(last)

        if path.endswith("/userprofile/settings"):
            return "profile", profile()
        if path.endswith("/heartRateZones/v2"):
            return "hr_zones", zones()
        if path.endswith("/v2/dailysummaries"):
            return "daily_summaries", {"data": [daily_summary(day) for day in span()]}
        if path.endswith("/dailySleepSummariesByDate"):
            return "sleep", [sleep_summary(day) for day in span()]
        if path.endswith("/bodyBattery/reports/daily"):
            return "body_battery", [body_battery(day) for day in span()]
        if path.endswith("/wellness/dailyHeartRate"):
            return "heart_rate", heart_rate_day(date.fromisoformat(params["date"]))
        if "/hrv-service/hrv/daily/" in path:
            first, last = tail_span()
            return "hrv", {"hrvSummaries": [hrv_summary(d) for d in days(first, last)]}
        if match := re.search(r"/hrv-service/hrv/([\d-]+)$", path):
            return "hrv_readings", hrv_day(date.fromisoformat(match[1]))
        if "/stats/stress/daily/" in path:
            return "stress", [stress_day(day) for day in days(*tail_span())]
        if "/stats/steps/daily/" in path:
            return "steps", [steps_day(day) for day in days(*tail_span())]
        if match := re.search(r"/spo2acclimation/([\d-]+)$", path):
            return "spo2", spo2_day(date.fromisoformat(match[1]))
        if "/fitnessage-service/" in path:
            return "fitness_age", fitness_age()
        if "/weight-service/weight/range/" in path:
            return "weight", weight_range(*tail_span(), self.weigh_ins)
        if "/weightgoal/" in path:
            goals = (
                [{"goalValue": self.weight_goal_kg * 1000, "startDate": "2026-01-01"}]
                if self.weight_goal_kg
                else []
            )
            return "weight_goal", {"userGoals": goals, "userGoalRanges": None}
        raise AssertionError(f"No fake route for {path}")

    def calls(self, fragment: str) -> list[httpx.Request]:
        return [request for request in self.requests if fragment in request.url.path]
