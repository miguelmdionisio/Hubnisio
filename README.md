# Hubnisio

A personal hub with one app per domain: finance first, fitness later. Self-hosted and private.

- Architecture and decisions: [docs/adr](docs/adr/README.md)
- Research notes: [docs/research](docs/research/oss-finance-analysis.md)

## Layout

```
backend/    Python: FastAPI API + Procrastinate worker, SQLAlchemy, Alembic (uv project)
frontend/   React + TypeScript SPA, Vite, TanStack Query/Router, Tailwind (pnpm project)
compose.yaml  Development stack: Postgres, migrations, API, worker, frontend
```

## Run it

Needs Docker Desktop.

```bash
cp .env.example .env    # then set a real POSTGRES_PASSWORD
docker compose up --build
```

- App: http://localhost:5173
- API docs: http://localhost:8000/docs

## Work on it without Docker

Needs [uv](https://docs.astral.sh/uv/) and Node 24 (pnpm comes through corepack). The database still runs in Compose: `docker compose up db migrate`.

```bash
cd backend && uv sync && uv run uvicorn hubnisio.main:app --reload
cd frontend && corepack pnpm install && corepack pnpm dev
```

## Checks

These are the same checks CI runs.

```bash
cd backend && uv run ruff check . && uv run ruff format --check . && uv run pyright && uv run lint-imports && uv run pytest
cd frontend && corepack pnpm check && corepack pnpm typecheck && corepack pnpm test && corepack pnpm build
```

The database tests start a throwaway Postgres in Docker. They're skipped locally if Docker isn't running.

After changing the API, regenerate the typed client (CI fails if you forget):

```bash
cd backend && uv run python scripts/export_openapi.py && cd ../frontend && corepack pnpm generate:api
```

Git hooks (ruff, Biome, gitleaks): `uv tool install pre-commit && pre-commit install`.
