# ADR-0002: Tech stack

**Status:** Accepted
**Date:** 2026-10-22
**Deciders:** Miguel Dionísio

## Context

- The backend is Python: the owner's preference, and the strongest ecosystem for data analysis and AI work.
- The frontend doesn't have to be Python.
- The app is a private, authenticated, dashboard-heavy web app (charts, large interactive tables), used on desktop for now.
- From [ADR-0001](0001-modular-monolith.md): one backend codebase with an API and a worker, on Postgres.

## Decision

### Backend

- **Python 3.14**, managed with **uv** (dependencies, lockfile, Python version).
- **FastAPI + Pydantic v2** for the HTTP API. Its OpenAPI schema is the contract with the frontend.
- **SQLAlchemy 2.x (async) + psycopg 3**, with **Alembic** migrations (one history; each module's tables in its own schema).
- **PostgreSQL 18.**
- **Procrastinate** for background jobs and periodic tasks. It's a Postgres-backed queue on psycopg 3, so there's no Redis.
- **httpx** for provider API clients; **PyJWT + cryptography** for Enable Banking's signed JWTs.
- **Analytics in SQL first** (views, materialized views); **Polars** when an analysis needs Python.
- **SQLAdmin** (optional) for an internal admin view of the data while the real UI is being built.

### Frontend

- **React + TypeScript** single-page app, built with **Vite**, managed with **pnpm**.
- **TanStack Query** for server state, **TanStack Router** for typed routes.
- **Generated API client** from FastAPI's OpenAPI schema (e.g. `@hey-api/openapi-ts`). CI regenerates it and fails on drift.
- **Tailwind + shadcn/ui** components. The charting library (ECharts or Recharts) is picked when the first dashboard is built.
- In production the SPA is static files served by the reverse proxy; the backend serves only the API.

### Quality

- Backend: **ruff** (lint + format), **pyright** (types), **pytest** against a real Postgres via **testcontainers**. No SQLite stand-in.
- Frontend: TypeScript strict, **Biome** (lint + format), **Vitest**.
- **pre-commit** hooks: ruff, Biome, gitleaks.
- **CI (GitHub Actions):** lint, type-check, tests, import-linter contracts, API client drift check.

## Options Considered

### Option A: FastAPI + React/TypeScript SPA (chosen)

| Dimension | Assessment |
|-----------|------------|
| Complexity | Medium: two toolchains (uv, pnpm), joined by a generated client |
| Cost | Free, all open source |
| Scalability | Not a concern at household scale |
| Familiarity | Python is the owner's language; TypeScript is accepted for the UI |

**Pros:** typed end to end; the best ecosystem for charts and data-heavy UIs; async-friendly for provider sync.
**Cons:** two languages; no built-in admin or auth, so both are assembled.

### Option B: Django (+ Django Ninja) + React

**Pros:** built-in admin, auth, ORM and migrations; Django "apps" map naturally onto modules.
**Cons:** less natural for multi-schema Postgres and hand-written analytical SQL; the async story is weaker; the admin matters less once we have our own UI (SQLAdmin covers the gap early on).

### Option C: Python-only UI (server-rendered templates + HTMX)

**Pros:** one language and one toolchain.
**Cons:** rich charts and large interactive tables fight the server-rendered model; the UI ceiling is lower for a dashboard-heavy app.

### Option D: Next.js frontend

**Pros:** mature React framework.
**Cons:** server rendering and SEO bring nothing to a private app, and it adds a Node server in production next to the Python one.

## Trade-off Analysis

The UI is where this project is most demanding: charts, filters, big tables. That favors a React SPA. A generated, CI-checked client takes away most of the cost of a second language. Django's batteries are real, but the ones it brings (admin, templates) matter least here, and its ORM is weakest where we need it most (schemas, analytical SQL).

## Consequences

- **Easier:** frontend types always match the API; heavy dashboards are straightforward; provider sync and the API share async code.
- **Harder:** two toolchains to keep updated; auth (sessions, passkeys) is our own code ([ADR-0004](0004-hosting-and-security.md)).
- **Revisit:** the charting library at the first dashboard; whether SQLAdmin earns its keep.

## Action Items

1. [ ] Scaffold `backend/` (uv project) and `frontend/` (Vite + pnpm) in one repo.
2. [ ] Set up pre-commit and CI with the checks above.
3. [ ] Wire OpenAPI client generation and the drift check.
