# Hubnisio: notes for Claude

A private, self-hosted personal hub, one app per domain; finance first. Decisions live in [docs/adr](docs/adr/README.md): read the index, and [ADR-0007](docs/adr/0007-finance-domain-model.md) for the finance model and what the banks actually send. Running it: [README](README.md).

## Where things stand

- **Done:**
  - M1: Enable Banking link and sync (BPI and Revolut, about 1,650 transactions).
  - M2: categories, merchants, rules, transfer pairs, notes and tags, and their pages.
  - M3: daily FX rates into EUR; spending, cash flow and net worth, computed on read; budgets with rollover and overspend; detected recurring payments the user confirms; the Budgets, Recurring and overview pages (Recharts).
  - Gaps G1–G6: an overall budget, hiding and deleting accounts, Revolut brand rules, the spending donut, shared pots with the Mine / Household view, repayments that lower their category.
  - M4 AI (ADR-0006): the `analytics` views and per-member logins (A1, `5cc86b6`); the MCP server with read tools (A2, `b3fb32c`); AI category suggestions (A3, `210d80e`); `net_worth_history` and net worth's inputs in the views (A4). Live since 2026-10-23: the user's AI login exists, `HUBNISIO_AI_ENABLED` is on, and the read tools work from Claude Code. The first categorization pass suggested 175 categories, which the user approves on the Transactions page (one click each, or "Approve the N shown"). IBANs in descriptions reach the AI masked as `[IBAN]`.
  - M6 T1 (ADR-0008): Trading 212 as a provider (`finance/providers/trading212`). `cli t212-link` links a member's key file; the sync turns the summary into a `TVAL` balance and cash movements and dividends into transactions (bank codes `T212_<type>`); seeded Dividends category and bank-code rules; the account shows on Accounts and Connections, outside net worth. Linked live on 2026-10-24; its first sync reconciled to the cent (ADR-0008, "As built in T2").
  - M6 T2 (ADR-0008, migration 0016): trades and holdings. The sync also reads positions, the order history and the instrument list (trimmed to what's held or traded) into `instruments` (global), `fills` (never transactions) and `portfolio_snapshots` with their `holding_snapshots`; renormalize rebuilds them. `GET /api/finance/investments` and the Investments page: value, cash, cost, result, holdings with weights, dividends and interest by month.
  - M6 T3 (ADR-0008, migration 0017): prices and value over time. `finance.instrument_prices` (global) holds a close per instrument and day from Yahoo Finance (`finance/prices`; daily task `fetch_prices`, `cli prices-backfill`, `cli prices-symbol`), else the broker's own prices from syncs and fills. `insights/portfolio.py` rebuilds an investment account's cash and holdings from its latest snapshot and trades; net worth counts it at that value, and the Investments page checks it against Trading 212's total. The `analytics` views gained `portfolios`, `holdings`, `fills`, `instruments` and `instrument_prices`. Live since 2026-10-24: all 19 instruments traded have a symbol and their closes, and the check against Trading 212 is exact.
  - M6 T4 (ADR-0008, no migration): returns. `insights/returns.py` splits an investment account's result over a period, the change in value less net deposits, into realised and unrealised price movements (average cost), dividends, interest, and fees and taxes, to the cent; the time-weighted return chained daily; the money-weighted one as an XIRR; and the value against net deposits. `GET /api/finance/investments/returns`, a Returns card on the Investments page, and the `investments` MCP tool, loaded from T3's views. Live since 2026-10-28. M6 is done.
- **M7 done** (2026-10-29), the frontend rework ([plan](docs/design/m7-frontend-rework.md), [navigation](docs/design/navigation.md), [DESIGN.md](DESIGN.md)), slices F1–F6.
  - F1 done: the "Calm" tokens in `frontend/src/index.css` (dark by default; light and system in `lib/theme.tsx`, kept per browser), Figtree, the B1 sidebar and phone tab bar from the per-domain config in `components/domains.ts`, the More page, search on Ctrl K, and `PageHeader` (title, sync freshness, Mine / Household, actions). The pages inside are unchanged until F3–F6. Spending joins the sidebar and the tabs in F3.
  - F2 done: `GET /api/finance/insights/spending/month` (`insights/spending_month.py`, pure `month_spending` over `DayRow`s from `daily_rows`, which shares `_grouped_rows` with `monthly_sums`): per day, per category and merchant, the month before; no frontend yet.
  - F3 done: the Spending page (`routes/finance/spending/`): `/finance/spending` with account, month, Category / Merchant and chart pills (bars per day, running total, donut; month, account, group, chart and day live in the URL), the ranked list, and the category and merchant pages (`…/category/$id`, `…/merchant/$id`) with their budget bar, merchants and transactions by day. Category icons and colours live in one place, `components/category-chip.tsx` (seeded names, then the group, then a hue from the name); pills in `components/pills.tsx`.
  - F4 done: the transaction sheet (`transaction-sheet.tsx`; a side panel on desktop, a bottom sheet on the phone): chip, merchant and amount, date, account and who set the category, a category grid that sets it in one click (or approves an AI suggestion), "All from <merchant>", then kind, merchant, note, tags and the bank's fields. Rows grouped by day (`transaction-rows.tsx`) on Transactions and Spending; Transactions has search and category, account and kind pills, and All / Review in the header.
  - F5 done: the shorter Overview (`routes/home.tsx`): sync status, four figures that open their pages (spent this month against the month before, left to spend, due in 7 days, net worth), budgets with a pace tick, coming up, spent per day, and a review pill in the header. The spending, donut, cash-flow and net-worth cards left it; `overview/net-worth-card.tsx` waits for Accounts in F6.
  - F6 done: the shadcn primitives restyled (pill buttons, soft cards, inputs and tabs), no sentences under page titles (`PageHeader` lost `description`), Merchants and Accounts as rows with chips, net worth's chart on Accounts (`finance/net-worth.tsx`), raw colours replaced by `good` / `destructive`; an impeccable critique pass at desktop and 375px (P1s fixed: tables scrolling sideways on the phone, explanatory sentences).
- **M8 Health done** (2026-11-11; [plan](docs/design/m8-health.md), [ADR-0009](docs/adr/0009-health-garmin.md), mock in `docs/design/m8-mock/`): the hub's second domain, from the user's Garmin watch through Garmin's Connect Personal API. Health rows belong to one member: no household view anywhere.
  - Source: `health/providers/garmin` (key in `secrets/garmin/<file>`, exchanged for a 24-hour token returned as plain text; send no `Accept` header, Garmin answers 406). `cli garmin-link --email --key-file --key-expires`, `garmin-sync`, `garmin-backfill [--kind …]`, `garmin-renormalize`; daily task `health:schedule_syncs`. Linked live on 2026-11-10; the key lapses on 2027-11-10 and the Garmin page warns from 14 days before.
  - Data (migrations 0018–0019): daily summaries, sleep, HRV, overnight samples, zones, weight, fitness age; activities with their original files parsed by `garmin-fit-sdk` into streams, laps and lengths, and `activity_derived` (our heart-rate load, zones, curves, best efforts, graded pace, EF and decoupling, estimated VO2max, climbs). Raw replies and files are kept, so renormalize rebuilds everything.
  - Pages (`routes/health/`, APIs `health/*_api.py`, pure functions in `health/insights/`): Today (`/health`), Activities and the activity page, Training (fitness 42-day, fatigue 7-day, form), Performance (run power and pace curves, critical power and speed, VO2max trend, race predictions with marathon shape, bike heart-rate curve and climbs, records), Recovery (HRV against a 60-day band, Signals today), Sleep, Body, Garmin. The shell follows the domain: `data-domain` on `<html>` switches the accent (Health: orange).
  - AI (migration 0020): 11 `analytics.health_*` views and the tools `health_training`, `health_sleep`, `health_recovery`, `health_performance`, `health_body`, `health_activities`. Streams, GPS, overnight samples, raw replies and files stay out of the views.
  - What Garmin doesn't send: a sleep stage timeline (only seconds per stage), its own VO2max, Training Readiness and Status. The user's rides have no power; runs do. Open-water stroke distance arrives in centimetres.
  - Not done: the impeccable critique pass (H10) beyond measured checks at 375px (no sideways overflow, no text under 11px).
- **M9 iPhone done** (2026-11-17; [plan](docs/design/m9-iphone.md)): the hub as an installed web app on the user's iPhone, over Tailscale while the PC runs. README, "On the iPhone".
  - Reach (P1): the `phone` Compose service serves a production build with `vite preview` on `127.0.0.1:4173` (plain HTTP; `tailscale serve --bg http://127.0.0.1:4173` adds the certificate; never Funnel). It builds on start: `docker compose restart phone` after frontend changes. Vite answers to `HUBNISIO_PHONE_HOST` (the PC's `.ts.net` name) from `.env`.
  - Installed (P2): manifest and Apple tags in `vite.config.ts` and `index.html` (vite-plugin-pwa, injectManifest); icons from one SVG, `public/app-icon.svg`, by `corepack pnpm icons`. The service worker (`frontend/sw/sw.ts`, its own tsconfig) keeps the build's files only, never `/api`; a new build shows "New version" with Reload. With the hub unreachable the shell opens and says so (`lib/reachability.ts`). `lib/standalone.ts` knows when the app is installed.
  - Touch (P3): the `tap-area` utility widens a control's tap area to 44px on touch screens without changing its look (`--tap-x`, `--tap-y`); inputs are 16px on the phone; pressed dim on `:active`; search in the phone header.
  - Gestures (P4, own code; vaul is unmaintained): bottom sheets drag down to close (`lib/drag-to-close.ts`, a handle in `ui/sheet.tsx`), pull to refresh refetches the page's queries, edge swipe back in the installed app only (`SWIPE_BACK` in `edge-swipe-back.tsx`). Tests fire touches with `touch` from `test/render.tsx`.
  - Motion (P5): detail pages (category, merchant, activity) slide in and out by view-transition types (`lib/transitions.ts`, CSS in `index.css`); scroll restoration on; Overview's skeletons hold the room their content takes.
  - Push (P6, migration 0021): `core/push.py` (VAPID key in `secrets/push`, `cli push-keys`, never printed; `cli push-test --email`), `core/push_api.py` (`/api/push`), alert rules in `finance/alerts.py` and `health/alerts.py`, sent by each domain's `send_alerts` every 30 minutes, once per key, 08:00–22:00 in `HUBNISIO_ALERTS_TIME_ZONE`. The page is More → Notifications (`/settings/notifications`). Live since 2026-11-17: the key exists; no device subscribed yet.
  - Checked in WebKit at iPhone 15 size (playwright-cli; WebKit installed): no target under 44px, no input under 16px, no sideways overflow, no layout shift on the main pages, both themes. Use the 4173 build for checks: the dev server is too slow in WebKit. The P7 pass found no P1; left: the active tab's blue on white is 4.39:1 in light; the phone search button sits before Health's freshness in the header.
  - Not checked on the device (the user's): Tailscale, install, push delivery, gestures, swipe back (iOS may already give it), and how bold weights render (WebKit on Windows draws Figtree's bold light).
- **Deferred:** M5 server (Tailscale, Caddy, passkey login replacing the dev user, Postgres roles, backups) waits until the user has an always-on machine. Don't start it, and don't build anything that needs one, until they say so.
- **Waiting on the user:**
  - M9 on the iPhone: install Tailscale on the PC and the iPhone, turn on MagicDNS and HTTPS certificates, set `HUBNISIO_PHONE_HOST`, run `tailscale serve` (README, "On the iPhone"); then add the app to the Home Screen, turn on notifications, and try the gestures;
  - the app icon: replace the placeholder `frontend/public/app-icon.svg`, run `corepack pnpm icons`;
  - switching on "Include in net worth" for the Trading 212 account on the Accounts page (ADR-0008, action item 3);
  - reviewing the 175 AI category suggestions;
  - hiding or deleting their unused Revolut accounts on the Accounts page;
  - deciding on a BPI `pagserv` → Utilities rule and an Uber rule (Uber Eats is a separate merchant).
- **Ideas, not planned:**
  - Hub-wide:
    - iPhone alerts (bills due, overspending, a weekly AI summary); needs the server;
    - a vault for papers and renewals (insurance, ID cards, contracts, warranties);
    - a home area shared with the partner (utilities, maintenance);
    - a car area (fuel per km, inspection, IUC road tax).
  - Finance:
    - IRS / e-Fatura deductions;
    - savings goals;
    - trips;
    - supermarket receipt line items;
    - linking repayments to the payment they cover, with an "owed to me" list (option B in ADR-0007).
- **How work runs:**
  - Plan a milestone with the user. Then build one slice per fresh session; each slice session starts the next itself.
  - Within an approved plan, each finished slice is committed and pushed to `main` once its checks pass. Outside a plan, ask before pushing.
  - Live steps are approved standing (the user, 2026-10-24): once a slice is pushed and CI is green, apply its migrations to the live database, restart the worker, run its backfills and seed what existing households lack. Check each, report counts only, and list what's left for the user. Ask first before anything that deletes or overwrites real data outside those steps. Never open key files.

## Layout and rules of the code

- `backend/`: FastAPI, SQLAlchemy 2.1 async, Alembic, Procrastinate; managed with uv. `frontend/`: Vite, React, TanStack Query/Router, shadcn/ui; pnpm via corepack. `compose.yaml` runs it all.
- **Import layers** (import-linter): `main | worker | cli | ai` > `jobs` > `finance | health` > `core`; `finance` and `health` never import each other.
- **Scoping:** every finance query goes through `finance/scoping.py` (household + account visibility). Another member's private accounts never show, not even by name.
- **Bank facts vs user layer:** only the sync writes `transactions` and `balance_snapshots`. Everything decided about a transaction lives in the user-layer tables. Precedence: manual > rule > counterparty default > ai.
- **Migrations:** autogenerate against a throwaway Postgres container, then finish by hand: named constraints, enum types created once, downgrade drops them. `tests/test_migrations.py` checks models and migrations agree.
- **Analytics views** (ADR-0006): the AI reads only the `analytics` schema, as a per-member login in the `hub_ai` group; the views filter on `session_user`. They're the SQL twins of `finance/scoping.py`, `finance/kinds.py`, `monthly_sums`, net worth's `load_inputs` with `load_portfolios` and `PriceTable.load`, and investments' `load_investments` and `load_returns`; and Health's `health/scoping.py` (the member's own rows only, never a household view) with the loaders `load_activity_rows`, `load_recovery_facts`, `load_activity_facts`, `load_run_zone3_floor`, `load_weight`, `load_body_facts` and sleep's `load_nights`, `load_night_days` and `load_hrv_nights`: a change there needs the same change in the views and `ai/views.py`.
  - A view changes only by a new migration. `CREATE OR REPLACE VIEW` keeps its grants but can only add columns at the end. A new view needs `GRANT SELECT … TO hub_ai`.
  - The agreement and security tests in `tests/test_analytics.py` must pass.
  - The MCP server (`hubnisio/ai`, run as `python -m hubnisio.ai`) loads the views into the app's dataclasses and calls its pure functions; `tests/test_ai.py` checks each tool against the app. A shape the API returns comes from a pure function both can call.
  - The AI's one write is `analytics.suggest_category` (an `ai` category, never over a higher source), called only by the `suggest_categories` tool in a read-write transaction; every other tool runs read-only.
- **Tests:**
  - Backend tests use a real Postgres via testcontainers (Docker must be running). Finance API tests share the `home` fixture (`tests/households.py`): two members, the seeded categories, three accounts (one private). The database isn't reset between tests, so `fx_rates`, being global, needs test-only currency codes such as `XTS`.
  - Frontend tests render the whole app with `src/test/render.tsx` (`renderAt`, `mockApi`) and `src/test/fixtures.ts`.
- **Display:** one locale, `en-GB`, in `frontend/src/lib/format.ts`.

## Before every commit

Run with `set -o pipefail`. Never pipe a check into `tail`/`grep` without it: a failure gets swallowed.

```bash
cd backend && uv run ruff format --check . && uv run ruff check . && uv run pyright && uv run lint-imports && REQUIRE_DOCKER=1 uv run pytest
cd frontend && corepack pnpm check:ci && corepack pnpm typecheck && corepack pnpm test && corepack pnpm build
uvx pre-commit run --all-files
```

After changing the API, regenerate the client (CI fails on drift):

```bash
cd backend && uv run python scripts/export_openapi.py && cd ../frontend && corepack pnpm generate:api
```

The user commits to `main` and approves pushes. Check CI with `gh run list` afterwards.

## Dependencies

- Pin new dependencies to releases at least 14 days old.
- pnpm only works as `corepack pnpm` here.
- **shadcn CLI:** pinned to `shadcn@4.21.4`. It calls `pnpm` directly, so it needs a `pnpm` shim on PATH. After adding components:
  - point imports from the `cn` package at `@/lib/utils`;
  - remove `cn` and `next-themes`;
  - decline overwriting existing components.

## Data, privacy, cost

- **Real data:** the live database holds real bank and health data. Report counts and aggregates, not transaction details or health values.
- **Secrets:** they live in `secrets/` (gitignored). Never open or print key files.
- **Cost:** the user watches usage. Work inline, use subagents only when clearly worth it, keep tool output small, and prefer page text over screenshots.

## Gotchas

- **Prices** (ADR-0008): Yahoo Finance is keyless but unofficial, and answers httpx's default User-Agent with 429. An instrument without a symbol needs `cli prices-symbol`.
- **Enable Banking:**
  - at most 4 unattended fetches per account per day;
  - full history only in about the first hour after linking, and BPI gives about 90 days even then;
  - neither bank sends pending transactions or MCCs;
  - Revolut merchant names are per branch, so use brand rules (`bank_counterparty starts_with`).
- **Running services:**
  - The Compose worker doesn't reload code: after backend changes, run `docker compose restart worker`. The API reloads itself.
  - Schedules fire only while the machine and worker run, and Procrastinate doesn't replay missed ones. `catch_up_syncs` (both domains, every 30 minutes) syncs any active connection with no attempt in 20 hours, so switching the machine on catches up.
  - The frontend dev server is HTTPS with a self-signed certificate: `https://localhost:5173`. Claude's built-in browser pane can't open it. Check pages with `playwright-cli` (installed globally, `%APPDATA%\npm\playwright-cli.cmd` when it isn't on PATH), run from the repo root so it picks up `.playwright/cli.config.json`, which ignores the certificate. Prefer `snapshot` and `find` over screenshots. Its output lands in `.playwright-cli/` (gitignored, since it holds real data).
  - The frontend container keeps its own `node_modules` and runs `pnpm install` only on start: after adding a frontend dependency, run `docker compose restart frontend`, or Vite can't resolve the import.
  - On Windows outside Docker, start uvicorn with `--reload`: psycopg async can't use the default Proactor event loop.
  - Admin commands run in the API container: `docker compose exec api python -m hubnisio.cli --help` (`recategorize`, `detect-recurring`, `fx-backfill`, `ai-login`, …). New migrations: `docker compose run --rm migrate`.
