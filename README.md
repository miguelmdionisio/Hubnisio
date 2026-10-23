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

## Using the hub from Claude

Claude Code and Claude Desktop can read your data through the hub's MCP server ([ADR-0006](docs/adr/0006-ai-access.md)). It runs in the api container and connects as your own Postgres login, which can only read the `analytics` views and suggest categories. So it sees what you see in the app (your view by default, or the household's), and the only thing it can change is a category suggestion. Every tool call is recorded in `core.ai_calls`, without the data it returned.

1. Turn it on: set `HUBNISIO_AI_ENABLED=true` in `.env`, then rebuild and recreate the containers. The stack must be running whenever Claude uses the server.
   ```bash
   docker compose up -d
   ```
2. Create your login. The command prints its role name (`hub_ai_…`) and writes its connection string to `secrets/ai/<role>`.
   ```bash
   docker compose exec api python -m hubnisio.cli ai-login --email you@example.com
   ```
3. Register the server in Claude Code. Replace `/path/to/Hubnisio` with the folder you cloned into (on Windows, for example `C:/Users/you/projects/Hubnisio`) and `<role>` with your role name. Add `--scope user` to use it from any folder. In Git Bash, put `MSYS_NO_PATHCONV=1` in front, or it turns `/run/secrets/…` into a Windows path.
   ```bash
   claude mcp add hubnisio -- docker compose -f /path/to/Hubnisio/compose.yaml exec -T -e HUBNISIO_AI_DSN_FILE=/run/secrets/ai/<role> api python -m hubnisio.ai
   ```
   `claude mcp list` should then show it as connected; "Failed to connect" usually means a wrong path or a stopped stack. The tools show up in Claude Code sessions started after that.
   For Claude Desktop, add the same command to `claude_desktop_config.json` (Settings → Developer → Edit Config):
   ```json
   {
     "mcpServers": {
       "hubnisio": {
         "command": "docker",
         "args": ["compose", "-f", "/path/to/Hubnisio/compose.yaml", "exec", "-T",
                  "-e", "HUBNISIO_AI_DSN_FILE=/run/secrets/ai/<role>",
                  "api", "python", "-m", "hubnisio.ai"]
       }
     }
   }
   ```

The tools: `list_accounts`, `list_categories`, `search_transactions`, `spending_summary`, `cashflow`, `budget_status`, `recurring_payments`, `balances`, `net_worth_history`, `uncategorized_overview`, and `query_sql` for anything else (one read-only query over the views, at most 500 rows, 5 seconds).

To categorize with Claude, run the server's `categorize_uncategorized` prompt (in Claude Code: `/mcp__hubnisio__categorize_uncategorized`). Claude goes through what has no category, merchant by merchant, and saves its picks with `suggest_categories`. A suggestion counts at once but has the lowest precedence: it never replaces a category you, a rule or a merchant's default set, and a rule or default that applies later replaces it. The Transactions page marks each one "AI" and filters them under "Suggested by AI"; the overview counts them. Approve one with the ✓ next to it, or every one listed with "Approve the N shown", and it becomes yours, as if you'd picked it. Picking another category replaces it.

To turn it off, set `HUBNISIO_AI_ENABLED=false` and run `docker compose up -d` again. To cut off one member, add `--revoke` to the `ai-login` command. Each member who wants it gets their own login and registers it in their own Claude.

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
