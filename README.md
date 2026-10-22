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

Needs Docker Desktop, plus uv for the one-time key generation.

First time only:

1. `cp .env.example .env`, then set a real `POSTGRES_PASSWORD`, your email as `HUBNISIO_DEV_USER_EMAIL`, and the Enable Banking application ID. The ID is the name of the `.pem` file the Control Panel gave you when you registered the application, without `.pem`.
2. Put that private key file at `secrets/enable-banking.pem`.
3. In the Enable Banking Control Panel, allow `https://localhost:5173/finance/connections/callback` as the application's redirect URL, and link your own accounts there. In restricted mode that list is only a whitelist: it doesn't give the hub access. The hub still asks each bank for your consent (Bank connections → Link a bank), and Enable Banking returns only the accounts on the list.
4. Generate the key that encrypts provider secrets. Keep a copy of both files in your password manager; backups are useless without them.
   ```bash
   cd backend && uv run python scripts/generate_encryption_key.py ../secrets/encryption-keys
   ```
5. Start the stack. The first start builds the images and creates the database tables.
   ```bash
   docker compose up --build
   ```
6. In another terminal, create your user and household. The API acts as this user until passkey login exists.
   ```bash
   docker compose run --rm api python -m hubnisio.cli bootstrap --email you@example.com --name "Your Name"
   ```

After that, `docker compose up` starts everything.

- App: https://localhost:5173. It uses a self-signed certificate (Enable Banking only redirects
  to https URLs), so the browser warns the first time: accept it once, before linking a bank.
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
