# Hubnisio: notes for Claude

A private, self-hosted personal hub, one app per domain; finance first. Decisions live in [docs/adr](docs/adr/README.md): read the index, and [ADR-0007](docs/adr/0007-finance-domain-model.md) for the finance model and what the banks actually send. Running it: [README](README.md).

## Where things stand

- **Done:** M1 (Enable Banking link and sync: BPI and Revolut, about 1,650 transactions); M2 (categories, merchants, rules, transfer pairs, notes and tags, and their pages).
- **Next:** M3 insights (budgets with rollover/overspend, recurring payments, FX rates, net worth, first charts). Then M4 AI (analytics views, `hub_ai` role, MCP server); M5 server (Tailscale, Caddy, passkey login replacing the dev user, Postgres roles, backups); M6 Trading 212.

## Layout and rules of the code

- `backend/`: FastAPI, SQLAlchemy 2.1 async, Alembic, Procrastinate; managed with uv. `frontend/`: Vite, React, TanStack Query/Router, shadcn/ui; pnpm via corepack. `compose.yaml` runs it all.
- **Import layers** (import-linter): `main | worker | cli` > `jobs` > `finance` > `core`.
- **Scoping:** every finance query goes through `finance/scoping.py` (household + account visibility). Another member's private accounts never show, not even by name.
- **Bank facts vs user layer:** only the sync writes `transactions` and `balance_snapshots`. Everything decided about a transaction lives in the user-layer tables. Precedence: manual > rule > counterparty default > ai.
- **Migrations:** autogenerate against a throwaway Postgres container, then finish by hand: named constraints, enum types created once, downgrade drops them. `tests/test_migrations.py` checks models and migrations agree.
- **Tests:**
  - Backend tests use a real Postgres via testcontainers (Docker must be running).
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
  - The frontend dev server is HTTPS with a self-signed certificate: `https://localhost:5173`.
  - On Windows outside Docker, start uvicorn with `--reload`: psycopg async can't use the default Proactor event loop.
