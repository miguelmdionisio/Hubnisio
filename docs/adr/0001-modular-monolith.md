# ADR-0001: Modular monolith with one Postgres schema per domain

**Status:** Accepted
**Date:** 2026-10-22
**Deciders:** Miguel Dionísio

## Context

Hubnisio is a personal hub covering several domains: finance first, fitness next, more later. Each domain is meant to be as complete as a standalone app, and some features will cross domains (for example, gym spending next to workout history). One person builds and runs it, for one household (one or two users), on a single self-hosted machine.

The architecture has to keep domains independent enough to grow separately for years, without paying distributed-systems costs that a household-sized load never needs.

## Decision

Build one deployable backend, split into modules with enforced boundaries:

- **One codebase, two entrypoints** from the same image: the HTTP API and the background worker.
- **Modules:** `core` (users, households, auth, settings, audit log, notifications, job plumbing) and one module per domain (`finance`, later `fitness`, ...).
- **One Postgres schema per module** (`core`, `finance`, `fitness`, ...). Foreign keys may point into `core` (users, households), never into another domain's schema.
- **Public interfaces only:** a module is used by others only through its `api.py`. No importing another module's models, repositories or routes.
- **Domain events** for cross-module reactions (e.g. `finance.TransactionCategorized`). Dispatch is synchronous in-process to start; a persisted outbox is added only when a consumer needs retries.
- **Boundaries checked in CI** with import-linter contracts, so they can't erode silently.

Layout:

```
backend/src/hubnisio/
  core/
  finance/
    api.py          public interface for other modules
    models.py       SQLAlchemy models, schema "finance"
    routes.py       HTTP endpoints
    services/       domain logic
    providers/      enable_banking/, trading212/
    jobs.py         background tasks
    events.py       events this module publishes
  fitness/          later
  main.py           API entrypoint
  worker.py         worker entrypoint
```

## Options Considered

### Option A: Microservices (one service per domain)

| Dimension | Assessment |
|-----------|------------|
| Complexity | High: network calls between services, distributed data, service discovery |
| Cost | Higher: more containers and more operations work for one maintainer |
| Scalability | Not needed: the load is one household |
| Familiarity | Solo project; every extra moving part is maintained by one person |

**Pros:** hard boundaries; independent deploys; could mix languages per domain.
**Cons:** cross-domain queries become API calls; consistency across services; much more ops for no load benefit.

### Option B: Modular monolith (chosen)

| Dimension | Assessment |
|-----------|------------|
| Complexity | Low to medium: one deploy, boundaries enforced by convention and tooling |
| Cost | Low: API + worker + Postgres |
| Scalability | Far beyond a household; a module can still be extracted later |
| Familiarity | Standard Python project structure |

**Pros:** one deploy and one database; transactions inside a module are simple; boundaries are still real.
**Cons:** boundaries need discipline and tooling; one module's crash takes the process down.

### Option C: Plain monolith (no module boundaries)

**Pros:** fastest to start.
**Cons:** domains tangle within months; cross-domain joins everywhere; hard to reason about or split later.

## Trade-off Analysis

The real risk for this project is entanglement as domains are added over the years, not scale. Microservices solve entanglement at a high operational price; a plain monolith ignores it. Schema-per-module plus import contracts gives most of A's isolation at C's operational cost.

## Consequences

- **Easier:** one thing to deploy, back up and debug; a domain can be developed without touching the others.
- **Harder:** cross-domain features need an explicit interface or event instead of a quick join.
- **Revisit:** add an outbox if events need durability; extract a module only if one ever needs a different runtime.

## Action Items

1. [ ] Scaffold `backend/` with `core` and `finance` in this layout.
2. [ ] Add import-linter contracts: domain modules may import `core` and other modules' `api` only.
3. [ ] Create the `core` and `finance` schemas in the first migration.
