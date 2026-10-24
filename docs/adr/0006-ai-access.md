# ADR-0006: AI access to hub data

**Status:** Accepted
**Date:** 2026-10-22
**Deciders:** Miguel Dionísio

## Context

- The owner wants AI to explore the data, find patterns, and help categorize.
- Sending finance data to the Claude API is acceptable.
- The data is sensitive: the AI must see only what the asking user may see, must never be able to change anything but its own category suggestions *(amended in M4)*, and must never touch secrets such as provider tokens or keys.
- LLMs are good at exploring and explaining, and unreliable as the source of truth for numbers.

## Decision

### Deterministic analysis lives in the app

- Recurring and subscription detection, transfer matching, anomaly flags and cash-flow forecasts run as background jobs.
- Their results are stored in finance tables.
- The AI reads and explains those results; it doesn't compute them.

### A read-only analytics layer

- An `analytics` schema of curated views, e.g. `analytics.transactions` (enriched), `analytics.monthly_category_spend`, `analytics.net_worth_daily`, `analytics.recurring_payments`, `analytics.budget_status`.
- Views leave out raw payloads, provider identifiers and secrets.
- A dedicated read-only Postgres role, `hub_ai`, can read only `analytics`.
- Results are scoped to the acting user's household and visibility ([ADR-0005](0005-household-data-model.md)), preferably with row-level security on this role.

**As built in M4** *(amended in M4)*:
- **The views** (migration `0011`) are `me`, `visible_accounts`, `accounts`, `transactions`, `monthly_category_spend`, `categories`, `merchants`, `budgets`, `budget_limits`, `recurring_payments` and `balances`. *(Slice A4, migration `0013`)* `daily_movements`, `account_connections` and `fx_rates` add net worth's inputs.
  - `transactions` has the date, amount, EUR amount, derived kind, description, bank counterparty, merchant, category and group, category source, tags, note, recurring series and bank code. It has no IBAN, entry reference, fingerprint or payload ID.
    - *(After M4, migration `0014`)* Banks write the other party's IBAN into some descriptions (26 of 1,663 on 2026-10-23, nearly all BPI SEPA transfers). So its description, bank counterparty and note show `[IBAN]` in place of anything shaped like one, compact or in groups of four. Every tool and `query_sql` read the view, so none can see or search for one. The app's own pages still show the full text.
  - `accounts` has no IBAN, holder name or hash. Its name leaves out the IBAN digits the app's default name uses.
  - `monthly_category_spend` is `monthly_sums` in SQL, for both views (household, and personal with pot moves in the pot's category).
  - Net worth has no view of its own (the `net_worth_daily` above). As with spending, the views hold its inputs and the app's code computes it: `balances` (each account's anchor), `daily_movements` (booked sums per account and day), `account_connections` (which connection each account comes through, for where its history starts) and `fx_rates` (public rates, the one view not scoped to the member).
  - Each view is `security_barrier`, has a comment for the AI, and is the SQL twin of `finance/scoping.py`, `finance/kinds.py` or `monthly_sums`. Agreement tests (`tests/test_analytics.py`) check that they match the app's figures for the same member and view. A view changes only by a new migration.
- **One Postgres login per member, not one shared role.** `cli ai-login --email <member>` creates `hub_ai_<12 hex of the user ID>` in the group role `hub_ai`. It sets `default_transaction_read_only`, a `statement_timeout` and `search_path = analytics` on it, maps it to the member in `core.ai_logins`, and writes its connection string to `secrets/ai/<role>`. The password is hashed before it reaches the server and is never printed. `--revoke` removes the mapping, ends the login's sessions and drops it.
- **Views filter on `session_user`, not row-level security.** A query can't change `session_user`: `SET ROLE` to another member's login is refused, and the group itself changes nothing. So `query_sql` is as safe as the tools, and a connection that isn't a mapped login sees nothing.
- **The grants are the boundary:** `USAGE` on `analytics`, `SELECT` on its views, and `EXECUTE` on `analytics.record_call` and *(slice A3)* `analytics.suggest_category`. Nothing else, so writes fail even in a read-write transaction. The read-only default only makes reads the default.

### An MCP server

- Built with the official Python MCP SDK, so Claude Desktop and Claude Code can use the data directly. Later, an in-app chat uses the same tools through the Claude API.
- Tools: `search_transactions`, `spending_summary`, `cashflow`, `net_worth_history`, `recurring_payments`, `budget_status`.
- A `query_sql` escape hatch: SELECT-only, on `analytics` only, with a statement timeout and a row limit.
- Reachable only on the private network, with a per-client token. *(Amended in M4: until the server exists (M5) it runs over local stdio, started by Claude Code or Desktop with `docker compose exec`, so it has no port and no token.)*
- *(Added in M4)* The AI's numbers come from the app's own code: the server loads the views into the dataclasses the app uses (`MonthlySums`, `CategoryInfo`, budget limits) and calls the same pure functions (`spent`, `total_spending`, `compute_budgets`).
- *(As built in M4, slice A2)* The package `hubnisio/ai`, run as `python -m hubnisio.ai` in the api container (README, "Using the hub from Claude"). Its tools are `list_accounts`, `list_categories`, `search_transactions`, `spending_summary`, `cashflow`, `budget_status`, `recurring_payments`, `balances` (each account's latest balance, and net worth today), `net_worth_history` *(slice A4)*, `uncategorized_overview` and `query_sql`. The insight tools take `view` (`personal` by default), as the API does, and `spending_summary`, `cashflow` and `budget_status` return the API's own shapes from the same pure functions. `tests/test_ai.py` checks every tool against the app.
  - Each call opens its own connection as the member's login. Its reads run in a `READ ONLY` transaction; then the call is recorded in a read-write one. A call that fails is recorded too, without a row count.
  - `query_sql` runs `SELECT * FROM (<query>) q LIMIT 501` with one bind parameter, so psycopg sends it as a single prepared statement and nothing can be chained after it. Postgres accepts only a query in that place, and no data-modifying `WITH` below the top level. It returns at most 500 rows, with `statement_timeout` set to 5 s for its transaction.
  - *(Slice A4)* `finance/insights/net_worth.py` is split into a loader and a pure `compute_net_worth`. `balances` and `net_worth_history` load the same inputs from the views and call it, so they give the Net worth page's figures and convert other currencies at each day's rate; until A4, `balances` converted only balances in euros. `net_worth_history` takes `date_from`, `view` and `every`: `day`, `week` (the default: each Sunday) or `month` (each month's last day), always ending with today, to keep a long series short.

### LLM-assisted categorization

- Uncategorized transactions get a suggested category from the Claude API.
- Suggestions are marked as such and never overwrite a manual categorization.
- *(Amended in M4)* The categorizing runs in the user's own Claude Code or Desktop session through MCP, so there's no API key and no per-call bill. Its only write is a category with source `ai`, the lowest precedence, through one `SECURITY DEFINER` function. Suggestions count at once, shown muted with an "AI" label, and picking a category overrides one.
- Only the fields needed are sent: description, counterparty name, amount, date. No IBANs or account numbers.
- Results are cached by a merchant/description fingerprint, so repeats don't call the API again.
- *(As built in M4, slice A3)* The cache isn't needed: a merchant's suggestion is one write for all its transactions, and the session decides when to run.
  - **The write:** `analytics.suggest_category(transaction_ids, category_id)` (migration `0012`), `SECURITY DEFINER`, returns how many it wrote and skipped. It finds the member from `session_user` and takes only transactions in `analytics.transactions` (so visible to them), booked and not transfers, with no `manual`, `rule` or `counterparty` category. It replaces an earlier `ai` one. The category must be in `analytics.categories` and not archived, or the call fails. It refuses a read-only transaction outright, so `query_sql` can't call it, and nothing but an AI login may.
  - **The tool:** `suggest_categories([{category_id, transaction_ids | merchant_id | description}])`, the one tool not marked read-only. It runs in a read-write transaction: every suggestion in a call is saved, or none. A merchant, or a description group from `uncategorized_overview` (its name, or any description that reads the same without digits), stands for that group's spending as the overview counts it (booked, money out, no category), plus what an AI suggested before, so a second pass keeps a merchant consistent. Money in, such as a refund, is taken only by ID: a group like a person's MB WAY transfers runs both ways. Its audit row counts the transactions written.
  - **The prompt:** `categorize_uncategorized` walks the model through `uncategorized_overview` (household view), `list_categories` and `suggest_categories`, group by group, leaving out what it can't tell.
  - **The app:** `listTransactions` takes `source` (who set the category). The Transactions page marks AI categories "AI" and filters them under "Suggested by AI"; the overview's "To categorize" tile counts them, from any month, with a link to review them. Picking a category, even the suggested one, makes it `manual`. *(Added after M4)* So does approving: a ✓ beside each AI category, and "Approve the N shown" under "Suggested by AI", both through `POST /transactions/approve-suggestions` (`approveSuggestions`), which turns visible `ai` assignments into `manual` ones and leaves the rest alone.

### Controls

- A config switch disables all external AI calls.
- Every external call is recorded in the audit log: what was sent, and when.
- *(Amended in M4)* The switch is `HUBNISIO_AI_ENABLED`, set in `.env` and passed to the containers by Compose: without it the MCP server won't start. The server connects only with the member's connection string in `HUBNISIO_AI_DSN_FILE`, never with the app's own database URL, and refuses to start if that login isn't mapped to a member. Each tool call is recorded in `core.ai_calls` (when, which login, which tool, its arguments and the row count, never the data returned) by `analytics.record_call`. That function is `SECURITY DEFINER`, takes the login from `session_user`, and fails in a read-only transaction, so `query_sql` can't write to the audit. The record outlives a revoked login.
- Models are picked per task: a smaller model for bulk categorization, a larger one for analysis and chat.

## Options Considered

### Option A: Let the AI query the main database directly

| Dimension | Assessment |
|-----------|------------|
| Complexity | Lowest |
| Cost | Low |
| Scalability | n/a |
| Familiarity | Simple |

**Pros:** the AI sees everything, with no curation work.
**Cons:** it can see secrets and raw payloads, can bypass household visibility, and could run destructive or very heavy queries. Not acceptable for this data.

### Option B: Curated read-only layer + MCP tools (chosen)

| Dimension | Assessment |
|-----------|------------|
| Complexity | Medium: views, one role, one MCP server |
| Cost | Claude API usage, kept down by caching and model choice |
| Scalability | Fine |
| Familiarity | SQL views plus a small Python server |

**Pros:** safe by construction (read-only, scoped, no secrets); the same tools serve Claude Desktop/Code and a future in-app chat; the views double as the reporting layer.
**Cons:** views and tools have to be maintained as the model evolves.

### Option C: Local-only models

**Pros:** nothing leaves the machine.
**Cons:** weaker analysis, and real hardware cost. Not needed since the Claude API is acceptable; keeping the tools model-agnostic leaves this open.

## Trade-off Analysis

B costs a modest amount of upfront work and makes the AI layer safe structurally, rather than relying on prompts. The `analytics` views aren't AI-only overhead either: the dashboards would want the same aggregates.

## Consequences

- **Easier:** asking questions about the data from Claude on day one of the analytics layer; adding AI features without touching domain tables.
- **Harder:** every new insight needs a view or tool; scoping must be tested for the AI role too.
- **Revisit:** row-level security on `hub_ai`; whether `query_sql` is still needed once the tools mature.

## Action Items

1. [x] Create the `analytics` schema and the `hub_ai` role once the finance tables exist. *(M4, slice A1.)*
2. [x] First MCP tools: `search_transactions` and `spending_summary`. *(M4, slice A2, with the other read tools.)*
3. [x] Categorization suggestions with a fingerprint cache and audit logging. *(M4, slice A3: suggestions through MCP, audited in `core.ai_calls`; no cache needed.)*
4. [x] A first live run from Claude Code: `cli ai-login` for the user, `HUBNISIO_AI_ENABLED=true`, and every read tool against the live data. *(2026-10-23, after M4.)*
5. [x] A first `categorize_uncategorized` pass, with its coverage in ADR-0007. *(2026-10-23.)*
