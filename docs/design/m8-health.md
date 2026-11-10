# M8: Health (plan)

Drafted with the user on 2026-11-10 from the mock at <https://claude.ai/artifact/NyeRSQhXv1X1ZMYAwt82U1> (private; its figures are made up). The mock is the reference for pages, charts and layout; its artboards are in [m8-mock/](m8-mock/). Approved by the user on 2026-11-10.

[m8-garmin-shapes.json](m8-garmin-shapes.json) holds the shape of each Garmin reply from the probe: field names and types only, no values.

Health is the hub's second domain: training, sleep and recovery from the user's Garmin watch, read through Garmin's Connect Personal API (launched October 2026).

## What the source gives (probed 2026-11-10)

- **Auth:** a personal key (made on connect.garmin.com, valid a year at most) is POSTed to the token endpoint as `Authorization: ApiKey <key>`. The reply is the token as plain text, a JWT valid 24 hours. Data calls use `Authorization: Bearer <token>` on `https://personal.connectapi.garmin.com`. No refresh token; exchange the key again.
- **Activities:** history from February 2025. The search returns up to 100 per page with load, Training Effect, time in zones, running dynamics, swim fields and fastest splits. Each activity's original `.FIT` file downloads as a zip (about 300 KB) with per-second data.
- **Daily:** a year of daily summaries in one call; sleep (stages, score, need), HRV (nightly, weekly, Garmin's baseline), Body Battery, stress, steps, heart rate, SpO2, respiration, fitness age, heart-rate zones with lactate-threshold heart rate. Most range calls take 28 or 31 days at most.
- **Missing:** Garmin's VO2max, Training Readiness, Training Status and race predictor. Hubnisio computes its own.
- **The user's data:** swim, bike and run (a triathlete), one watch. Runs have power and running dynamics from the watch. Rides have heart rate only, no power. Hydration and nutrition aren't logged.
- **Unknown:** rate limits; how far back sleep and HRV go; the weight-history call returned 400 and needs its parameters checked.

## Decided (2026-11-10)

- **Visibility:** health data belongs to one member. Nobody else in the household sees it, and Health has no Mine / Household switch. Enforced in one place (`health/scoping.py`), with tests that a second member gets nothing.
- **Cycling without power:** bike load comes from heart rate. Performance shows a heart-rate curve and climbing speed for the bike; a bike power curve appears only when rides carry power.
- **AI:** the MCP server reads health data, as the last slice, filtered to the member's own rows like finance (ADR-0006).
- **Scope:** all of the mock: Today, Activities and the activity page, Training, Performance, Recovery, Sleep, Body, and the Garmin source page.
- **Accent:** orange, as in the mock. The sleep charts' "awake" colour moves off orange so the One Accent Rule holds.
- **Readiness:** "Signals today" is Hubnisio's own check (HRV in range, resting heart rate, sleep against need, form, Body Battery). It shows the five signals, never one invented score.

## Shape of the code (ADR-0009 settles these in H1)

- **Package and schema:** `hubnisio/health`, Postgres schema `health` (ADR-0001). In the import layers it sits beside `finance`, above `core`; neither imports the other.
- **Provider:** `health/providers/garmin` (client, schemas, normalize), like `finance/providers/trading212`. `cli garmin-link` links a member's key file in `secrets/garmin/` and records the key's expiry. The Garmin page warns from two weeks before it lapses.
- **Facts and derived data:** the sync alone writes what Garmin sent (activities, their files, daily rows, nights). Raw replies and `.FIT` files are kept so `renormalize` can rebuild everything. Per-activity results that need the per-second data (load, time in zones, best efforts per duration, graded pace, efficiency, decoupling, estimated VO2max) are computed at ingest into a derived table. Everything over time (fitness and fatigue, baselines, curves across a season, predictions) is computed on read by pure functions, as `finance/insights` does.
- **Load:** one load number per activity that is comparable across the three sports, from heart rate against the member's threshold. Garmin's own load is stored and shown beside it on the activity page. Fitness is its 42-day weighted average, fatigue the 7-day one, form the difference.
- **Sync:** a daily worker task plus "Sync now". It pulls what's new since the last run, in 28-day windows, politely (rate limits are unknown). The first run backfills from February 2025.
- **Frontend:** a `HEALTH` entry in `components/domains.ts` with its own accent, routes under `/health/…`, the domain switcher listing both domains. Phone tabs: Today, Activities, Sleep, Recovery, More.
- **Dependency:** a `.FIT` parser, pinned to a release at least 14 days old; chosen in H2.

## Slices

Each slice is one fresh session, committed and pushed to `main` once its checks pass; the session starts the next. Live steps (migrate, restart the worker, backfill) follow each push under the standing approval. API slices regenerate the client.

1. **H1 Foundation and daily data.** ADR-0009. The `health` package, schema and scoping; the Garmin client with token exchange; `cli garmin-link`; sync of daily summaries, sleep, HRV, Body Battery, stress, heart-rate zones, fitness age and weight (fixing the 400); the worker task and backfill. Tests with recorded-shape fixtures holding invented values. Live: link the key, backfill, report counts.
2. **H2 Activities and `.FIT` files.** Activity summaries; download and parse of each file into per-second streams and laps; the derived table; `renormalize`. Live: backfill all activities since February 2025.
3. **H3 Shell, Garmin page and Sleep.** The Health domain in the sidebar, switcher and tab bar; the Garmin page (sync status, key expiry, Sync now). Sleep API and page: the night (stages with heart rate, split by stage, overnight heart rate, HRV, respiration, SpO2), 30 / 90 / 365 nights against need, sleep debt, bedtime and wake spread, sleep against next morning's HRV, score by weekday.
4. **H4 Recovery.** API and page: HRV against the member's normal range (7-day average inside a 60-day band), night-to-night swing, resting heart rate, Body Battery charged and drained, stress per day, Signals today.
5. **H5 Activities.** The list (sport and date pills, search) and the activity page per sport: figures, streams over distance or time, splits, route, zones, durability (decoupling, efficiency, halves), running form; swim sets and SWOLF for swims; download of the `.FIT`.
6. **H6 Training.** API and page: fitness, fatigue, form with its bands, ramp rate, daily load, hours per week by sport, time in zones per sport against 80 / 20, monthly totals.
7. **H7 Performance.** Run power curve with the critical-power model, run pace curve, both against last season; estimated VO2max per run; race predictions with marathon shape; easy-run efficiency; swim threshold pace; bike heart-rate curve and climbing speed; records per sport.
8. **H8 Today and Body.** Today: four linked figures, fitness over 90 days, the last 7 days by sport, last night, HRV over 30 nights, recent activities, the signals strip on the phone. Body: weight against goal, fitness age.
9. **H9 AI.** `analytics` views for health (new migration, `GRANT SELECT … TO hub_ai`, filtered on `session_user`), read tools on the MCP server (training, sleep, recovery, activities), agreement and security tests as in `tests/test_analytics.py` and `tests/test_ai.py`.
10. **H10 Critique pass.** An impeccable pass over every Health page at desktop and 375px; `DESIGN.md` gains the Health accent, the sport colours and the sleep-stage colours; `CLAUDE.md` updated.

## Rules that carry over

- Real health data: report counts and date ranges, never values. Test fixtures hold invented values. The probe's raw replies in the scratchpad are deleted once H1's backfill is checked.
- The key file is never opened or printed by Claude; the client reads it at run time.
- No sentences on screen, `en-GB`, every chart with a screen-reader list of its values, every page designed for 375px and desktop together.
- Honest gaps: a night the watch wasn't worn, or a day without sync, shows a short marker rather than a zero.

## Not in M8

- Planned workouts, a training calendar or race goals.
- Pushing anything to the watch (the API is read-only).
- Alerts (they need the server, M5).
- Links between Health and Finance (gear and race spending).
- Manual logging of food, water or how a session felt.
