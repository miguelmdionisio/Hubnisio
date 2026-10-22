# ADR-0007: Finance domain model

**Status:** Accepted
**Date:** 2026-10-22
**Deciders:** Miguel Dionísio

## Context

- Bank data comes from Enable Banking, and investment data from Trading 212 ([ADR-0003](0003-financial-data-sources.md)).
- The model must support a household with joint accounts ([ADR-0005](0005-household-data-model.md)) and AI analysis ([ADR-0006](0006-ai-access.md)).

Findings that shape it ([research](../research/oss-finance-analysis.md)):

- **`transaction_id` isn't an identity.** It can change between fetches. `entry_reference` is stable per account but missing at some banks.
- **Pending transactions often have no stable ID**, and they change when booked.
- **Firefly's importer** stores bank data and user edits in the same record and dedups on a hash of all fields. Any change at the bank makes a transaction look new.
- **Re-linking creates new account UIDs.** Accounts must be matched by `identification_hash`.
- **History is limited:** full history is usually available only for about an hour after linking, then about 90 days.

## Decision

### Ledger: single-entry with linked transfers

- Each transaction belongs to one account and has a signed amount.
- A move between two of the household's own accounts is a pair of transactions joined by a transfer link. Transfers are excluded from income and spending.
- Counterparties (merchants, employers, people) are their own entity, not accounts. Firefly-style double-entry was rejected.

### Three layers

1. **Raw:** `provider_payloads`. Every provider response, append-only, never modified. Normalization can be re-run from it.
2. **Bank facts:** `transactions`. One row per real transaction as the provider reports it: account, amounts (+ original currency amount when given), booking date, value date, transaction date, counterparty name/IBAN, description, status, MCC, bank code, provider identity. **Only the sync writes this layer.**
3. **User layer:** everything a person, rule or the AI decides: category, notes, tags, transfer link, recurring link. Stored apart from the bank facts, so **syncing never overwrites it**.

### Identity and deduplication

- **Accounts:** matched within the household by Enable Banking `identification_hash`, falling back to IBAN. A joint account reached through two users' connections is stored once.
- **Transactions:**
  - When there's an `entry_reference`, the identity is `(account, entry_reference)`.
  - Otherwise, a fingerprint: booking date + amount + currency + normalized counterparty + normalized description, plus an occurrence index so two genuinely identical transactions on the same day stay distinct.
  - Never the full-payload hash, never `transaction_id`.
- **Pending transactions:**
  - Stored with `status = pending` and no stable identity. Each sync replaces the pending set for the fetched window.
  - A newly booked transaction is matched to a pending one that disappeared (same account, same amount, within 5 days, configurable). The user layer moves over to it.
  - Pending transactions show in lists and balances but are excluded from budgets and reports until booked.
- **First link:** fetch with `strategy=longest` immediately after authorization, inside the full-history window. Later syncs fetch a short overlapping window (e.g. the last 14 days).

### Categorization

- `categories`: a household-level tree (parent/child), with an optional per-user extension later ([ADR-0005](0005-household-data-model.md)).
- `category_assignments`: one row per transaction for now (category + amount + source). The table allows several rows per transaction, so splits (manual or from receipts) can be added later without changing the schema. **No split UI for now.**
- **Precedence:** `manual` > `rule` > `ai`. A lower-precedence source never overwrites a higher one.
- **Rules:**
  - Ordered rules; each has conditions (match all / any) on description, counterparty, amount range, account, MCC and direction, and actions (set category, tag, counterparty, mark as transfer).
  - They run when transactions arrive and can be re-run on demand. "Stop processing" is available per rule.
- **Counterparties:** a cleaned-up name with aliases (e.g. "CONTINENTE MATOSINHOS 4450" → Continente) and an optional default category.

### Recurring payments: detected, not scheduled

- `recurring_series` is filled by a detection job, not entered by hand. The job groups transactions by counterparty and similar amount, looks for a regular cadence (weekly / monthly / quarterly / yearly, each within a tolerance), and requires at least 3 occurrences.
- Each series stores its cadence, expected amount, last seen date, next expected date and status (active / dormant / cancelled).
- It's used for the subscription list, expected upcoming payments (forecasting) and price-change alerts.
- The user can confirm, edit, or dismiss a detected series.

### Budgets

- A budget is a monthly limit per category (other periods possible later).
- Everything is **configurable per category**:
  - `rollover`: off (reset every period) or on (unspent money carries into the next period).
  - `overspend`: `forgive` (the next period starts fresh) or `carry` (the overspend is subtracted from the next period).
- Defaults: everyday categories reset; when rollover is on, overspending carries.
- Spending counts booked, non-transfer transactions assigned to the category, with child categories rolling up to their parent.

### Balances and net worth

- `balance_snapshots`: the bank-reported balance (booked and available) for each account on each sync. This is the source of truth for balances.
- Transactions explain the movement between snapshots. Balances between snapshots are interpolated from transactions.
- Net worth = the sum of the latest balances across accounts (investments at market value), in EUR via `fx_rates` (daily rates). Accounts can be excluded from net worth.

### Investments (Trading 212)

- A separate sub-model: instruments (ISIN, ticker, currency), trades, dividends, cash movements, holdings, prices.
- Its performance model will be decided when that provider is built.

## Options Considered

### Ledger

| Option | Pros | Cons |
|---|---|---|
| Single-entry + transfer links (chosen) | Matches how bank data arrives; simple queries; what Actual and Sure do | Balances are checked against bank snapshots rather than by the ledger's own structure |
| Double-entry (Firefly) | Every movement balances by construction | Every merchant becomes an account; heavier queries and UI |

### Budget rollover

| Option | Pros | Cons |
|---|---|---|
| Configurable per category (chosen) | Fits both everyday and irregular spending | More settings to explain in the UI |
| Fixed reset | Simplest | Irregular costs (car service, gifts) always look like overspending |
| Envelope / zero-based | Every euro planned | Needs constant upkeep; a different product style |

## Consequences

- **Easier:** syncs are safe to re-run; bank corrections never destroy user work; history fixes come from re-normalizing raw data; joint accounts dedupe naturally.
- **Harder:** pending→booked matching and fingerprinting need careful tests with real data from each bank; the user layer must follow a transaction through re-identification.
- **Revisit:**
  - pending-match tolerance and fingerprint fields once real BPI / Novo Banco / Revolut data is seen
  - the investment model, when the Trading 212 provider is built
  - a split UI, if receipts become a data source

## Action Items

1. [ ] Migrations for the tables above in the `finance` schema.
2. [ ] Enable Banking provider: linking, `longest` first fetch, overlapping incremental sync, pending replacement.
3. [ ] Dedup and pending-matching test suite built from recorded raw payloads.
4. [ ] Rules engine plus the category precedence logic.
5. [ ] Recurring detection job.
6. [ ] Budget calculation with per-category rollover and overspend settings.
