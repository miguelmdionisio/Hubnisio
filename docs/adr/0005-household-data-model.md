# ADR-0005: Household data model

**Status:** Accepted
**Date:** 2026-10-22
**Deciders:** Miguel Dionísio

## Context

- There's a joint Revolut account with a partner. She doesn't use the hub yet but may log in later.
- Some accounts will be personal and others shared.
- Adding multi-user support to a schema after the fact is one of the most painful migrations there is, so the model has to support a household from the start, even with a single active user today.

## Decision

### Identity

- `core.users`
- `core.households`
- `core.household_members` (household_id, user_id, role: `owner` | `member`)

### Tenancy

- Every domain record carries `household_id`.
- Domains that are inherently personal (fitness, health) also carry `user_id` and are private to that user by default.

### Finance ownership

- `finance.accounts` belongs to a household.
- `finance.account_owners` (account_id, user_id) is many-to-many, so a joint account has two owners.
- `visibility` on the account: `shared` (all household members) or `private` (owners only). Transactions inherit their account's visibility.

### Categories, rules and budgets

- These belong to the household.
- A nullable `user_id` leaves room for personal ones later, without a migration of existing data.

### Provider connections

- A connection (for example, an Enable Banking session) belongs to the user who authorized it, because PSD2 consent is personal.
- The same joint account can therefore arrive through two users' connections. Accounts are matched within the household on a stable identifier (IBAN, otherwise the provider's account ID), so a joint account is stored once and its transactions aren't double-counted.

### Authorization

- Enforced in one place: a query-scoping helper in `core` that every finance query goes through (household + visibility), covered by tests.
- **Two account sets** *(added before M4)*: the helper, in `finance/scoping.py`, has two account sets.
  - `visible_account_ids` (household and visibility) includes hidden accounts. It serves everything about past transactions: the transactions list, spending, cash flow, budgets and recurring payments.
  - `listed_account_ids` also leaves out hidden accounts ([ADR-0007](0007-finance-domain-model.md), "Retiring an account"). It serves account lists and filters, net worth and upcoming payments.
  - Hiding never widens what a member sees: a listed account is always a visible one.
- Postgres row-level security is a later defense-in-depth option, most useful for the AI read-only role ([ADR-0006](0006-ai-access.md)).

## Options Considered

### Option A: Single-user now, migrate later

| Dimension | Assessment |
|-----------|------------|
| Complexity | Lowest at first, highest at migration time |
| Cost | A painful, data-touching migration once a second user arrives |
| Scalability | n/a |
| Familiarity | Simple |

**Pros:** less to build up front.
**Cons:** the joint account already exists, so the "later" is foreseeable; retrofitting ownership touches every table and query.

### Option B: Household model from day one (chosen)

| Dimension | Assessment |
|-----------|------------|
| Complexity | Low to medium: a few extra tables and one scoping helper |
| Cost | Small, paid once |
| Scalability | Covers a partner, and family members if ever needed |
| Familiarity | Standard multi-tenant pattern |

**Pros:** the partner gets a login without any migration; joint accounts are modeled correctly from the start.
**Cons:** every query has to be scoped, so the helper must be used everywhere.

## Trade-off Analysis

The cost of B is a handful of tables and the discipline of one helper. The cost of A is a migration through every finance table at a moment when there's real data to protect. With a joint account already in place, B is clearly cheaper.

## Consequences

- **Easier:** adding the partner is a user record and a membership row; joint accounts dedupe correctly.
- **Harder:** every new query and AI tool must respect scoping; tests have to cover visibility.
- **Revisit:** row-level security once the analytics role exists.

## Action Items

1. [ ] `core` tables for users, households and memberships in the first migration.
2. [ ] Query-scoping helper plus tests (shared vs private, owner vs member).
3. [ ] Account matching on IBAN / provider account ID within a household, in the Enable Banking provider.
