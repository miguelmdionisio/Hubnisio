# Hubnisio: notes for Claude

A private, self-hosted personal hub, one app per domain; finance first. Decisions live in [docs/adr](docs/adr/README.md): read the index, and [ADR-0007](docs/adr/0007-finance-domain-model.md) for the finance model and what the banks actually send. Running it: [README](README.md).

## Where things stand

- **Done:**
  - M1: Enable Banking link and sync (BPI and Revolut, about 1,650 transactions).
  - M2: categories, merchants, rules, transfer pairs, notes and tags, and their pages.
  - M3: daily FX rates into EUR; spending, cash flow and net worth, computed on read; budgets with rollover and overspend; detected recurring payments the user confirms; the Budgets, Recurring and overview pages (Recharts).
  - Gaps G1–G6: an overall budget, hiding and deleting accounts, Revolut brand rules, the spending donut, shared pots with the Mine / Household view, repayments that lower their category.
  - M4 AI (ADR-0006): the `analytics` views and per-member logins (A1, `5cc86b6`); the MCP server with read tools (A2, `b3fb32c`); AI category suggestions (A3, `210d80e`); `net_worth_history` and net worth's inputs in the views (A4). Live since 2026-10-23: the user's AI login exists, `HUBNISIO_AI_ENABLED` is on, and the read tools work from Claude Code. The first categorization pass suggested 175 categories, which the user approves on the Transactions page (one click each, or "Approve the N shown"). IBANs in descriptions reach the AI masked as `[IBAN]`.
  - M6 T1 (ADR-0008): Trading 212 as a provider (`finance/providers/trading212`). `cli t212-link` links a member's key file; the sync turns the summary into a `TVAL` balance and cash movements and dividends into transactions (bank codes `T212_<type>`); seeded Dividends category and bank-code rules; the account shows on Accounts and Connections, outside net worth. Not linked live yet.
  - M6 T2 (ADR-0008, migration 0016): trades and holdings. The sync also reads positions, the order history and the instrument list (trimmed to what's held or traded) into `instruments` (global), `fills` (never transactions) and `portfolio_snapshots` with their `holding_snapshots`; renormalize rebuilds them. `GET /api/finance/investments` and the Investments page: value, cash, cost, result, holdings with weights, dividends and interest by month.
- **Deferred:** M5 server (Tailscale, Caddy, passkey login replacing the dev user, Postgres roles, backups) waits until the user has an always-on machine. Don't start it, and don't build anything that needs one, until they say so.
- **Next:** M6 Trading 212, planned in [ADR-0008](docs/adr/0008-investments.md) (accepted 2026-10-24): T1 (provider and cash) and T2 (trades and holdings) are done; then T3 (prices and net worth over time), T4 (returns and AI).
- **Waiting on the user:**
  - applying migrations 0015 and 0016 to the live database (`docker compose run --rm migrate`), then `docker compose up -d` for the Trading 212 keys mount and `docker compose restart worker`. Until then the running API (which reloads code) fails on accounts, connections and investments;
  - creating a read-only Trading 212 API key (account data, history, portfolio, metadata) at `secrets/trading212/<name>` (ADR-0008, action item 1; format in the README);
  - in the existing household, before the first Trading 212 sync: the Income › Dividends category and the four `T212_*` rules (ADR-0008, "As built in T1"), which seeding gives only new households. Then `t212-link`, and checking the signs of the first sync's withdrawals and fees, and of its fills' quantities, net values and taxes (ADR-0008, "As built in T2");
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
  - Writes to the live data need the user's approval in the session doing them: skip them, list them at the end, and keep going.

## Layout and rules of the code

- `backend/`: FastAPI, SQLAlchemy 2.1 async, Alembic, Procrastinate; managed with uv. `frontend/`: Vite, React, TanStack Query/Router, shadcn/ui; pnpm via corepack. `compose.yaml` runs it all.
- **Import layers** (import-linter): `main | worker | cli | ai` > `jobs` > `finance` > `core`.
- **Scoping:** every finance query goes through `finance/scoping.py` (household + account visibility). Another member's private accounts never show, not even by name.
- **Bank facts vs user layer:** only the sync writes `transactions` and `balance_snapshots`. Everything decided about a transaction lives in the user-layer tables. Precedence: manual > rule > counterparty default > ai.
- **Migrations:** autogenerate against a throwaway Postgres container, then finish by hand: named constraints, enum types created once, downgrade drops them. `tests/test_migrations.py` checks models and migrations agree.
- **Analytics views** (ADR-0006): the AI reads only the `analytics` schema, as a per-member login in the `hub_ai` group; the views filter on `session_user`. They're the SQL twins of `finance/scoping.py`, `finance/kinds.py`, `monthly_sums` and net worth's `load_inputs`: a change there needs the same change in the views.
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

- **Real data:** the live database holds real bank data. Report counts and aggregates, not transaction details.
- **Secrets:** they live in `secrets/` (gitignored). Never open or print key files.
- **Cost:** the user watches usage. Work inline, use subagents only when clearly worth it, keep tool output small, and prefer page text over screenshots.

## Gotchas

- **Enable Banking:**
  - at most 4 unattended fetches per account per day;
  - full history only in about the first hour after linking, and BPI gives about 90 days even then;
  - neither bank sends pending transactions or MCCs;
  - Revolut merchant names are per branch, so use brand rules (`bank_counterparty starts_with`).
- **Running services:**
  - The Compose worker doesn't reload code: after backend changes, run `docker compose restart worker`. The API reloads itself.
  - The frontend dev server is HTTPS with a self-signed certificate: `https://localhost:5173`. Claude's built-in browser pane can't open it, so check pages with tests, or fetch modules with `curl -k`.
  - The frontend container keeps its own `node_modules` and runs `pnpm install` only on start: after adding a frontend dependency, run `docker compose restart frontend`, or Vite can't resolve the import.
  - On Windows outside Docker, start uvicorn with `--reload`: psycopg async can't use the default Proactor event loop.
  - Admin commands run in the API container: `docker compose exec api python -m hubnisio.cli --help` (`recategorize`, `detect-recurring`, `fx-backfill`, `ai-login`, …). New migrations: `docker compose run --rm migrate`.
