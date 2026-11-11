# ADR-0009: Health from Garmin

**Status:** Accepted
**Date:** 2026-11-10
**Deciders:** Miguel Dionísio

## Context

- M8 adds Health, the hub's second domain: training, sleep and recovery from the user's Garmin watch ([plan](../design/m8-health.md), approved 2026-11-10). This ADR settles the plan's "Shape of the code" and records slice H1 as built.
- The source is Garmin's Connect Personal API (October 2026). A personal key, made on connect.garmin.com and valid a year at most, is exchanged for a 24-hour token; the API is read-only. [m8-garmin-shapes.json](../design/m8-garmin-shapes.json) holds the shape of every reply from the probe: names and types, no values.
- Health data is personal in a way bank data isn't. The household model ([ADR-0005](0005-household-data-model.md)) shares accounts; nothing in Health is shared.
- One schema per domain, boundaries checked by import-linter ([ADR-0001](0001-modular-monolith.md)). Trading 212 ([ADR-0008](0008-investments.md)) is the closest precedent: a key in a file, a CLI to link it, raw replies kept, a daily sync.

## Decision

### Package, schema and layers

- **`hubnisio/health`**, Postgres schema `health`. Its tables refer to `core.users` only.
- **Import layers:** `main | worker | cli | ai` > `jobs` > `finance | health` > `core`. The `|` makes `finance` and `health` independent: neither imports the other (checked by `lint-imports`). A later cross-domain view goes through events or the entrypoints, never a direct import.
- **Routers:** `health/api.py` now; later slices add `health/sleep_api.py` and the like. `hubnisio.main.ROUTERS` lists every router by domain, the one place to register a new one.

### Visibility: one member, no household

- Every health row carries `user_id`, the member it belongs to, and no `household_id`. Nobody else in the household sees it, the owner included; there's no Mine / Household switch.
- **`health/scoping.py`** is the one place this lives: `mine(model, principal)` for requests, `of_member(model, user_id)` for code acting for a member it was handed (the sync, the CLI), `own_connection(session, principal)`. Every health query goes through them. Tests prove a second member of the same household gets nothing: no connection, no counts, no rows in any table, 404 on "Sync now".
- Each member links their own watch, with their own key.

### The key and the connection

- **The key is a file,** `secrets/garmin/<name>`, one line `key=<personal API key>` (blank lines and `#` comments ignored). The folder is `HUBNISIO_GARMIN_KEYS_DIR` (default `../secrets/garmin`), mounted read-only at `/run/secrets/garmin` in the api and worker containers. The database records the file's name, never the key.
- **`cli garmin-link --email … --key-file … --key-expires YYYY-MM-DD`** exchanges the key, reads the profile (its time zone), creates or updates the member's connection (one per member and provider) and queues the first sync. The API doesn't report when a key lapses, and the token's `exp` is the token's own 24 hours, so the member gives the date Garmin showed when making the key. Linking again with a new key reactivates the same connection.
- **Expiry:** the Garmin page (H3) warns from two weeks before `key_expires_on` (`key_expires_soon` in the API). A sync after that day marks the connection `expired` without calling Garmin; so does a key the token exchange refuses.

### The client

- `POST /personalapitoken-service/personal-api/personal-api-key/token` with `Authorization: ApiKey <key>`; the 200 reply's body is the token as plain text, a JWT. Its `exp` is read (without checking the signature) to know when to exchange again, five minutes early; a token without a readable `exp` is kept 23 hours. Data calls send `Authorization: Bearer <token>`. There's no refresh token: a 401 exchanges the key once more and retries once; a second 401 is `KEY_REJECTED`.
- **Politeness, since the limits are unknown:** one call at a time, half a second between calls, an explicit User-Agent. A 429 waits for `Retry-After`, else 5 s doubling, at most 5 minutes at once, and gives up after 5 tries as `RATE_LIMITED`; the task tries the sync again in an hour.
- Each endpoint is declared once, with the most days one call may cover:

| Kind | Endpoint | Days per call |
|---|---|---|
| `profile` | `/userprofile-service/userprofile/settings` | — |
| `hr_zones` | `/biometric-service/heartRateZones/v2` | — |
| `daily_summaries` | `/usersummary-service/v2/dailysummaries?startDate&endDate` | 364 |
| `sleep` | `/sleep-service/sleep/dailySleepSummariesByDate?startDate&endDate` | 31 |
| `hrv` | `/hrv-service/hrv/daily/{from}/{to}` | 28 |
| `body_battery` | `/wellness-service/wellness/bodyBattery/reports/daily?startDate&endDate` | 31 |
| `stress`, `steps` | `/usersummary-service/stats/{stress,steps}/daily/{from}/{to}` | 28 |
| `weight` | `/weight-service/weight/range/{from}/{to}` | 180 (`WEIGHT_WINDOW`) |
| `hrv_readings` | `/hrv-service/hrv/{day}` | 1 |
| `heart_rate` | `/wellness-service/wellness/dailyHeartRate?date` | 1 |
| `spo2` | `/wellness-service/wellness/daily/spo2acclimation/{day}` | 1 |
| `fitness_age` | `/fitnessage-service/fitnessage/v2/{day}` | today only |
| `weight_goal` | `/goal-service/goal/user/effective/weightgoal/{from}/{to}` | the last 364 days |

- **Weight:** the probe's 400 came from a 365-day range; 364 days work (checked live, 2026-11-10). The `range` call returns `dailyWeightSummaries` (and `totalAverage`, `previousDateWeight`, `nextDateWeight`); the `all` call returns a list. No weigh-in was seen, so the normalizer reads entries defensively (`allWeightMetrics`, else `latestWeight`; weight in grams; `timestampGMT`, else `date`, else `calendarDate`) and accepts both replies.

### Facts and derived data

- **Only the sync writes facts,** and `renormalize` rebuilds them all from `provider_payloads`: every reply, kept append-only with its kind, the days it covers and the request. Later slices keep `.FIT` files the same way (H2).
- **Per-activity results that need the per-second data** (load, time in zones, best efforts, graded pace, efficiency, decoupling, estimated VO2max) are computed at ingest into a derived table (H2). **Everything over time** (fitness and fatigue, baselines, curves, predictions) is computed on read by pure functions, as `finance/insights` does.
- **Load:** one number per activity comparable across swim, bike and run, from heart rate against the member's threshold; Garmin's own load is stored beside it. Fitness is its 42-day weighted average, fatigue the 7-day one, form the difference (H2, H6).
- **Upserts by natural key** (member and day, or member and time), so reading a day again updates it. A value a reply leaves out never erases one already stored. The daily summary's values win; the stress, steps and Body Battery replies only fill what it lacks, so the order replies arrive in doesn't matter.

### Tables (H1, migration 0018)

| Table | Key | What |
|---|---|---|
| `connections` | `id`; unique `(user_id, provider)` | provider `garmin`, status `active` / `expired`, `key_file`, `key_expires_on`, `time_zone`, `last_synced_at` |
| `sync_runs` | `id` | trigger (`initial`, `scheduled`, `user`, `backfill`), status, `error_code`, `payloads`, `skipped` (kinds whose calls failed without failing the run) |
| `provider_payloads` | `id` | kind, `day_from`, `day_to`, request, raw response (JSON, null for an empty body) |
| `sync_cursors` | `(connection_id, kind)` | `synced_through`: the last day of the last window applied |
| `daily_summaries` | `(user_id, day)` | steps, goal, distance, floors, calories, resting / min / max heart rate, intensity minutes, stress (average, maximum, time per level), Body Battery charged / drained / min / max, SpO2, respiration |
| `sleeps` | `(user_id, day)` | the night ending that day: start, end, UTC offset, time per stage, awake count, score and qualifier, need, average heart rate, respiration, SpO2, sleep stress |
| `hrv_nights` | `(user_id, day)` | last night's average and 5-minute high, weekly average, status, Garmin's baseline band |
| `samples` | `(user_id, kind, at)` | readings over time: `heart_rate` (all day), `hrv` (the night's 5-minute readings), `spo2` (hourly), `body_battery`; `day` is the reply's calendar day |
| `heart_rate_zones` | `(user_id, sport)` | the zones' floors, maximum and lactate-threshold heart rate, method; replaced on each sync |
| `fitness_ages` | `(user_id, day)` | fitness age as read that day, and its components |
| `weights` | `(user_id, measured_at)` | weight, BMI, body fat and water, muscle and bone mass, source |
| `weight_goals` | `user_id` | the current goal's target and start; deleted when Garmin has none |

- **The night's detail:** the probed sleep replies are summaries only; neither the range nor the one-day call carries a stage timeline. The night's detail comes from the per-day calls instead: the overnight heart rate (the day's heart-rate samples between the night's start and end), the HRV readings and the hourly SpO2. Respiration is the night's average, lowest and highest. If a call with the stage timeline turns up, it's a new kind and table, and a `renormalize` fills nothing in the past it didn't fetch.
- `usersummary/daily` duplicates the daily summary for one day and isn't read.

### The sync

- **Order:** profile and zones; the range kinds, each in windows no longer than its endpoint allows; the per-day kinds; then fitness age and the weight goal as of today. "Today" is in the member's time zone, from the profile.
- **From where:** each kind from its cursor less two days (`OVERLAP`: today's reply is partial, and last night is filled in later), or from **1 February 2025** (`BACKFILL_START`) the first time. A backfill reads every kind from a given day whatever its cursor; cursors never move back.
- **Progress survives failures:** each reply is committed before it's applied, and each applied window moves its kind's cursor, so a sync cut short (a 429, a crash) resumes where it stopped.
- **Optional kinds:** a failing call to `weight`, `weight_goal` or `fitness_age` is logged, added to the run's `skipped`, and the run goes on. Any other failure ends the run (`error_code`: `KEY_REJECTED`, `RATE_LIMITED`, `HTTP_<status>`, `NETWORK`); a reply that fails to apply is logged, stops its kind and marks the run `APPLY_FAILED`.
- **Schedule:** the `health:schedule_syncs` task at 09:00 UTC queues `health:sync_connection` for every active connection; "Sync now" (`POST /api/health/sync`) queues one with trigger `user`. A connection's syncs never run at the same time (a Procrastinate lock). The first backfill makes about three calls per day since February 2025 (the per-day kinds), so it runs for tens of minutes; later syncs make a few dozen calls.

### Commands and API (H1)

- `cli garmin-link --email E --key-file NAME --key-expires YYYY-MM-DD`
- `cli garmin-sync [--email E]`: sync now, in the CLI, from the cursors.
- `cli garmin-backfill [--email E] [--since YYYY-MM-DD] [--kind K …]`: read again from a day (default 2025-02-01).
- `cli garmin-renormalize [--email E]`: rebuild the facts from the stored replies.
- Each prints counts per table, never values.
- `GET /api/health/connection`: linked or not, status, key expiry and `key_expires_soon`, last sync and last run, `synced_through` per kind, row counts per kind. `POST /api/health/sync`: 202 with `queued`; 404 when nothing is linked, 409 when the connection has expired.

## Options Considered

### Who sees health data

| Option | Pros | Cons |
|---|---|---|
| The member only, no household view (chosen) | Matches what health data is; one simple rule, tested in one place | A shared view (a partner's training) would need explicit sharing later |
| Visibility per row like accounts | Flexible | A switch on every chart; easy to leak by mistake |

### Where the facts' detail lives

| Option | Pros | Cons |
|---|---|---|
| Typed tables per kind plus one `samples` table (chosen) | Queries and pure functions get columns; one table for every reading over time | A new kind of reading needs an enum value |
| Only the raw replies, parsed on read | No schema to keep | Every page parses JSON; nothing indexable |

### How far a sync goes back

| Option | Pros | Cons |
|---|---|---|
| A cursor per kind, less two days (chosen) | Resumes after a failure; a skipped kind catches up alone | One more table |
| One date per connection | Simple | A failure in one kind re-reads, or loses, the others |

### The .FIT parser (H2)

| Option | Pros | Cons |
|---|---|---|
| Garmin's `garmin-fit-sdk` (chosen, pinned `21.218.0`, released 2026-10-06) | Official, follows each FIT profile release; typed stubs; decodes developer fields and expands components; has an encoder, so tests write synthetic files | Large generated profile module; releases every few weeks, so the pin needs bumping by hand |
| `fitdecode` | Small, streaming | One release since 2021 (0.11.0); profile lags new message types; no encoder |

## As built in H2 (Activities and .FIT files)

Migration 0019. Activities belong to one member like everything else; every query goes through `scoping.py`.

| Table | Key | What |
|---|---|---|
| `activities` | `(user_id, activity_id)` (Garmin's id) | the search summary: sport (type key), start (UTC and local), durations, distance, elevation, heart rate, speed and Garmin's graded speed, power, cadence, calories, Garmin's load and training effects, time in Garmin's heart-rate and power zones, running dynamics, swim fields (pool length, lengths, strokes, SWOLF), fastest splits, `is_parent` / `child_ids` / `parent_id`, `raw` |
| `activity_files` | `(user_id, activity_id)` | the download as received (a zip holding one `.FIT`), status `stored` / `none` / `failed`, `attempts`, `error_code`. Raw, like `provider_payloads`: never rebuilt, no foreign key to `activities` |
| `activity_streams` | `(user_id, activity_id)` | one row per activity, an array per column, all as long as `time_s` (seconds from the start): distance, heart rate, speed, altitude, cadence, power, lat / lon (degrees), vertical oscillation, ground contact, step length, vertical ratio; a column the activity lacks is null |
| `activity_laps` | `(user_id, activity_id, lap_index)` | the file's laps |
| `activity_lengths` | `(user_id, activity_id, length_index)` | a pool swim's lengths, swum or rest, with stroke, strokes and SWOLF |
| `activity_derived` | `(user_id, activity_id)` | Hubnisio's results (below), rebuilt by `renormalize` |

- **The file:** records come about once a second (fewer with smart recording, none while paused); the run sample had no developer fields. Speed and altitude are the `enhanced_` fields; positions are semicircles, stored as degrees; a run's cadence is stored as steps per minute (twice the file's strides plus its fraction). The session's `time_in_zone` gives the watch's threshold, maximum and resting heart rate.
- **Multisport:** the search is asked for legs too (`excludeChildren=false`). A parent (`is_parent`) gets its detail but no file; its `childIds` link the legs (`parent_id`), and a leg the search left out is created from its own detail. Each leg's file is parsed for the session starting closest to the leg's start, so a shared file gives each leg its part. Totals count legs, never the parent. Manual activities have no file.
- **Sync:** `activities` is a kind with a cursor. Summaries are searched in 90-day windows, 100 per page, oldest first (cursor less two days, or from 2025-02-01). Then each activity without a stored file, oldest first: its detail (stored as an `activity_detail` payload; it only fills what the search left empty), then its file, downloaded at most one every 2 seconds, stored, then parsed and derived in its own transaction. A failed call or a file that won't parse is that activity's alone: recorded on its `activity_files` row, `activity_files` added to the run's `skipped`, and the run goes on; a failed call is tried again by the next syncs, three times in all. A rejected key or a rate limit still ends the run, which resumes where it stopped.
- **Commands:** `cli garmin-backfill --kind activities [--since YYYY-MM-DD]` reads the summaries again and fetches what's missing; `cli garmin-renormalize` also parses every stored file again. Counts per table (`activities`, `activity_streams`, …, `activity_files`) join `GET /api/health/connection`'s `counts`; no other API yet.

### Derived per activity (`health/insights/`, pure)

All on a one-second grid of moving time (`series.moving`): gaps up to 5 s are filled, longer ones too when the distance shows movement at 0.5 m/s or more (smart recording, up to 5 min); other gaps are pauses and are cut out.

- **Reference** (`load.heart_rate_reference`): the member's zones for the sport (`RUNNING`, `CYCLING`, `SWIMMING`), else `DEFAULT`; a value missing there comes from the file; then threshold ≈ 0.89 × max, max ≈ threshold / 0.89; resting heart rate from the zones, else the member's latest daily resting heart rate up to that day, else the file, else 60. No threshold and no maximum: no load.
- **Load** (`load.hr_load`), hrTSS-style: `100 × TRIMP / (60 × w(threshold))`, with Banister's `TRIMP = Σ (1/60) × w(HR)` per second and `w(HR) = r × 0.64 × e^(1.92 r)`, `r = (HR − rest) / (max − rest)` held to 0…1. One hour at threshold scores 100 in every sport.
- **Time in zones** (`load.time_in_zones`): seconds below zone 1 and in zones 1–5, by the member's zone floors, else 70 / 85 / 90 / 95 / 100 % of threshold.
- **Mean-maximal curves** (`curves.mean_max`) of power, heart rate and speed over 1, 5, 10, 15, 30 s, 1, 2, 5, 10, 20, 30 min, 1, 1.5, 2 h; a window must have a value every second.
- **Best efforts** (`curves.best_efforts`, `curves.swim_best_efforts`): runs over 400 m, 1 km, 1 mile, 5 km, 10 km, half and marathon, the stretch's start interpolated between samples; pool swims over 100, 200, 400, 800, 1500 m from the lengths, within unbroken runs of swum lengths; open water from the distance.
- **Graded pace** (`running`): Minetti's cost of running `C(i) = 155.4i⁵ − 30.4i⁴ − 43.3i³ + 46.3i² + 19.5i + 3.6` (grade over ±10 s, at least 10 m run, held to ±45 %); graded speed = speed × C(i) / C(0); normalized graded speed = the fourth-power mean of its 30 s rolling average.
- **Efficiency and decoupling** (`durability`), for 20 minutes or more with heart rate: EF = output / heart rate (runs: normalized graded speed in m/min; rides: normalized power, else speed); decoupling = (EF first half − EF second half) / EF first half × 100. `steady` when the 30 s rolling output's coefficient of variation is at most 0.15.
- **Estimated VO2max** (`running.estimated_vo2max`), Runalyze's "effective VO2max": Daniels and Gilbert's oxygen cost of the average graded speed v (m/min), `−4.60 + 0.182258 v + 0.000104 v²`, over the share of VO2max implied by average heart rate / max by Swain, `(%HRmax − 0.2812) / 0.7303`. Graded speed is the elevation correction (in place of Runalyze's fixed metres per metre climbed). Runs of 10 minutes or more at 60–100 % of max only; not calibrated against races.
- **Climbing speed** (`climbs`), rides: a climb runs from a low to the highest point after it until the road drops 10 m below that peak; it counts with 50 m gained over 5 minutes at 3 % or more; VAM = metres gained per hour. `best_vam` is the fastest.

## As built in H4 (Recovery)

`GET /api/health/recovery?days=30|90|365` (`health/recovery_api.py`) returns what `health/insights/recovery.py` computes from the member's own rows (`recovery_loader.py`, through `scoping.py`). A day without data is a gap, never a zero.

- **Normal range:** a band around the mean of the nightly HRV over the trailing 60 days (the night included): mean ± 0.75 sample standard deviations. Under 14 nights in those 60 days there is no band, and the figure says so. A night below the band is flagged. Garmin's own baseline (`hrv_nights.baseline_*`) is stored but not used.
- **7-day averages** (HRV, resting heart rate) need at least 4 of their 7 days. **Night-to-night swing** is the coefficient of variation of the last 7 nights (population deviation, in %); its 90-day value is the mean of that swing over the last 90 days (at least 14 of them).
- **Body Battery at wake:** the first reading of the night's day at or after the night's end. Charged and drained are the day's totals.
- **Signals today:** independent checks, each ok / watch / no data, counted and never merged: the HRV 7-day average inside the band; resting heart rate at most 3 bpm above its 7-day average; last night's sleep at least 85% of need; Body Battery at wake at least 60. A value older than 2 days is no data. Training form joins when it exists (H6), as ok at -10 or more: a provisional floor until H6's form bands replace it.

## As built in H7 (Performance)

`GET /api/health/performance?period=season|90d|all` (`health/performance_api.py`) returns what `health/insights/performance.py` computes from the member's own activities and their `activity_derived` rows (`insights/performance_loader.py`, through `scoping.py`). No migration. The season is the calendar year; "last season" is the year before, and the curves are always drawn against it. Rides here carry heart rate only, so the power curve is the run's (the watch's run power), and the bike gets a heart-rate curve and climbing speed; a bike power curve appears only when a ride in the period carries power.

- **Season curves:** per duration of the mean-maximal grid, the best of the activities' own curves in the period, with its day and activity: run power, run speed (shown as pace), ride heart rate.
- **Critical power** (Monod and Scherrer's two-parameter model): P(t) = CP + W′/t, fitted by ordinary least squares on work against time, W = CP·t + W′, over the period's bests from 3 to 20 minutes (on the grid: 5, 10 and 20 minutes). It needs at least 3 durations, the longest 12 minutes or more, and a positive CP and W′; else no model. W/kg from the latest weigh-in, only when one is stored. **Critical speed** is the same fit on distance against time (D = CS·t + D′) from the speed curve; threshold pace = 1000 / CS. **Critical swim speed:** CSS = (400 − 200) / (t400 − t200) from the period's best 400 m and 200 m (pool or open water), shown as seconds per 100 m; none when either is missing.
- **VO2max trend:** each run's estimate (H2) as a point, and a line: on each day, the mean of the best half (rounded up) of the estimates in the trailing 42 days, so easy runs, whose estimates read low, don't drag it down. The latest value is that line today; its change, today's against the value 90 days ago.
- **Race predictions** (shown as estimates): Daniels and Gilbert's VDOT, VO2 = −4.60 + 0.182258v + 0.000104v² (v in m/min) over %max = 0.8 + 0.1894393e^(−0.012778t) + 0.2989558e^(−0.1932605t) (t in minutes), solved for t by bisection at the current VO2max. Beside it, Riegel, T2 = T1·(D2/D1)^1.06, from the run best effort of 5 km or more in the last 90 days with the highest VDOT.
- **Marathon shape** (after Runalyze's "Marathonform", over the last 26 weeks): weekly target km = VO2max^1.135, weekly share = (km run / 26) / target; long-run target km = 12·ln(VO2max / 4), each run of 13 km or more scores ((km − 13) / (target − 13))², and the long-run share is their sum over 13 (one run at target every two weeks); shape = ⅔ weekly share + ⅓ long-run share, uncapped. A distance needs a shape of (km − 5) / (42.195 − 5), held to 0–100% (5 km none, half 43%, marathon 100%). When the shape falls short of what a distance needs, its prediction uses VDOT × (1 − 0.25 × (1 − shape / needs)): a marathon at 71% shape runs at 92.75% of the VDOT. This slowing is Hubnisio's own rule, not Runalyze's.
- **Easy-run efficiency:** EF (H2) of steady runs of 20 minutes or more whose average heart rate is under zone 3's floor (the member's running zones, else default zones, else 90% of the run's threshold). The trend is the least-squares line from the first to the last point; the change over 6 months is that line's end against its start, in %, over the easy runs of the last 182 days (at least 3, on more than one day).
- **Bike:** the heart-rate curve, and the five fastest climbs (H2's VAM) with day, length and gain.
- **Records:** in the period, with the all-time best beside it when another activity holds it (not for "all"): run best efforts over 1 km, 5 km, 10 km, half and marathon; swims over 100, 400 and 1500 m, pool or open water; rides' longest distance, most climbing and best 20- and 60-minute average speed; multisport results (the parent's totals, else its legs' sums), newest first.

## As built in H9 (AI access to Health)

Migration 0020 adds health views to `analytics` (ADR-0006), each `WITH (security_barrier)`, granted to `hub_ai`, and filtered by joining the table's `user_id` to `core.ai_logins` on `session_user`: the SQL twin of `scoping.py`. A login sees only its own member's rows; the household's other member, the owner included, sees not a row nor a count, and `hub_ai` has no right on the `health` schema itself.

- **Views:** `health_connection` (status, time zone, last sync; never the key file), `health_activities` (Garmin's summary without `raw`, plus `activity_derived` under its own names: `has_derived`, `derived_moving_s`, `derived_hr_zone_s`, the curves, best efforts, graded pace, EF, decoupling, VO2max, climbs; and `day`, the local start's date), `health_activity_laps`, `health_daily_summaries`, `health_sleeps`, `health_hrv_nights`, `health_wake_battery` (each night's first Body Battery reading at or after its end, as the recovery loader reads it), `health_heart_rate_zones`, `health_weights`, `health_weight_goal`, `health_fitness_ages`.
- **Left out:** the raw replies (`provider_payloads`, `activities.raw`), the activity files, the per-second streams (with their GPS positions: no route or position reaches the AI), pool lengths, the overnight samples (heart rate, HRV, SpO2, Body Battery) beyond the wake reading, sync runs and cursors. The streams and samples are large and more detailed than any question needs; what the pages compute from them is stored (`activity_derived`) or summarized per night.
- **Tools** (`ai/server.py`, read-only transactions): `health_training(days)`, `health_sleep(nights, on)`, `health_recovery(days)`, `health_performance(period)`, `health_body(days)` take the pages' own periods and return the pages' own shapes, loaded by `ai/views.py`'s twins of the Health loaders (`training_loader`, `recovery_loader`, `performance_loader`, `body_loader`, sleep's `load_*`) and computed by the same pure functions (`training_api.training`, extracted for this, `recovery`, `performance`, `body`, sleep's `trends` and `night_detail`); `tests/test_ai.py` checks each against the API. The sleep night comes without the overnight readings, so its heart rate, HRV and SpO2 are the night's averages, lows and highs only. `health_activities(activity_id, sport, date_from, date_to, text, limit)` searches the activities, newest first, or gives one in full with its derived results and laps.

## Consequences

- **Easier:** later slices read typed rows through `scoping.py`; a normalizer fix is a `garmin-renormalize` away; a new endpoint is one line in `ENDPOINTS` and one normalizer.
- **Harder:** an unofficial-feeling API with unknown limits; per-day calls make the first backfill slow; the key needs replacing yearly, by hand.
- **Revisit:** the windows and pause once the rate limits are known; the stage timeline if an endpoint gives it; the weight entries' fields once a weigh-in is seen; whether a multisport leg's download is the whole race's file or its own (both parse); the activity files' size in the database (a few hundred KB each) if it grows.

## Action Items

1. [ ] The user makes a personal API key on connect.garmin.com, saves it as `secrets/garmin/<name>` (README, "Linking Garmin"), and notes its expiry date.
2. [ ] After H1 is pushed (standing approval): migrate, restart the worker, `garmin-link`, let the first sync backfill, and report counts and date ranges only.
3. [ ] Delete the probe's raw replies from the scratchpad once the backfill is checked.
