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

### Shared pots and two views *(added before M4)*

- **The case:** the joint Revolut account is shared with a partner who isn't in the hub. Its money is partly hers, so counting its spending and balance as the user's overstates both.
- **Shared pot** (`accounts.is_pot`, with `pot_category_id`, an expense category): an owner marks the account, for the whole household. The pot's real balance always shows on the Accounts page.
- **Two views** for spending, cash flow, budgets (the overall budget included) and net worth, chosen per request (`view`) and by a "Mine / Household" toggle remembered in the browser:
  - **Mine** (`personal`, the default): the viewer's own accounts that aren't pots. Money they move into a pot counts as spending when it's moved, in the pot's category (uncategorized without one); money back lowers it. The pot's own spending and balance aren't theirs.
  - **Household:** every visible account in full, as before. Moves to the pot are transfers and its spending counts.
  - Example: 1,000 on a personal account, 300 moved in, the pot spends 120. Mine: spending 300, net worth 700. Household: spending 120, net worth 880.
- **Her deposits** land in the pot, so they're outside Mine. Household counts them as money in until she links her account and they pair up as transfers.
- **Not now:** owner share fractions and per-transaction "whose is it" overrides. Under this model nothing needs them; they can come when the partner logs in.
- **Unchanged:** the transactions list (bank facts: the moves stay transfers there), recurring and upcoming payments, and the categorization engine, which still skips categories on transfers. The pot's category comes from the account setting.

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
- **The Mine sets** *(added before M4)*: `mine_account_ids` is the visible accounts the viewer owns that aren't shared pots, hidden ones included; `listed_mine_account_ids` also leaves out hidden ones, for net worth. `counted_account_ids` and `listed_counted_account_ids` pick the pair for a view. A pot counts in Mine only through the viewer's side of a transfer pair with it, and only a pot the viewer may see.
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
