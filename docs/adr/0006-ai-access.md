# ADR-0006: AI access to hub data

**Status:** Accepted
**Date:** 2026-10-22
**Deciders:** Miguel Dionísio

## Context

- The owner wants AI to explore the data, find patterns, and help categorize.
- Sending finance data to the Claude API is acceptable.
- The data is sensitive: the AI must see only what the asking user may see, must never be able to change anything, and must never touch secrets such as provider tokens or keys.
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

### An MCP server

- Built with the official Python MCP SDK, so Claude Desktop and Claude Code can use the data directly. Later, an in-app chat uses the same tools through the Claude API.
- Tools: `search_transactions`, `spending_summary`, `cashflow`, `net_worth_history`, `recurring_payments`, `budget_status`.
- A `query_sql` escape hatch: SELECT-only, on `analytics` only, with a statement timeout and a row limit.
- Reachable only on the private network, with a per-client token.

### LLM-assisted categorization

- Uncategorized transactions get a suggested category from the Claude API.
- Suggestions are marked as such and never overwrite a manual categorization.
- Only the fields needed are sent: description, counterparty name, amount, date. No IBANs or account numbers.
- Results are cached by a merchant/description fingerprint, so repeats don't call the API again.

### Controls

- A config switch disables all external AI calls.
- Every external call is recorded in the audit log: what was sent, and when.
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

1. [ ] Create the `analytics` schema and the `hub_ai` role once the finance tables exist.
2. [ ] First MCP tools: `search_transactions` and `spending_summary`.
3. [ ] Categorization suggestions with a fingerprint cache and audit logging.
