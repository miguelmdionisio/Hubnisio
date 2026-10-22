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

- `categories`: a household-level tree of two levels (groups and categories), each `expense` or `income`, with an optional per-user extension later ([ADR-0005](0005-household-data-model.md)). New households start with an editable default tree.
- `category_assignments`: one row per transaction for now (category + amount + source). The table allows several rows per transaction, so splits (manual or from receipts) can be added later without changing the schema. **No split UI for now.**
- **Precedence:** `manual` > `rule` > `counterparty` (the merchant's default category) > `ai`. A lower-precedence source never overwrites a higher one, and a specific rule beats a merchant's general default. *(Amended in M2.)*
- **Rules:**
  - Ordered rules; each has conditions (match all / any) on description, counterparty, amount range, account, MCC and direction, and actions (set category, tag, counterparty, mark as transfer).
  - They run when transactions arrive and can be re-run on demand. "Stop processing" is available per rule.
- **Counterparties:** a cleaned-up name with aliases (e.g. "CONTINENTE MATOSINHOS 4450" → Continente) and an optional default category. A name the bank sends becomes a counterparty automatically; one set by hand is never replaced.
- **Rule actions** are recomputed on every run, so editing or deleting a rule takes effect everywhere. Tags a rule adds are kept apart from tags added by hand, which a run never touches.

### Transaction kind and transfers *(added in M2)*

- A transaction's kind (expense, income or transfer) is derived, not stored: transfer if it's in a transfer pair or overridden, otherwise from its sign. An override (by hand or by a rule) covers moves the sign gets wrong, e.g. a deposit to a broker the hub doesn't sync yet.
- **Transfer pairs** are linked automatically when exactly one match exists: same currency and amount, opposite directions on two of the household's accounts, at most 3 days apart. Ambiguous matches are left alone. Unlinking a pair records a dismissal, so matching never links it again.
- Transfers are excluded from income, spending and categories.

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

- **Easier:** syncs are safe to re-run; bank corrections never destroy user work; history fixes come from re-normalizing raw data, which keeps every transaction that keeps its identity (and so its user layer); joint accounts dedupe naturally.
- **Harder:** pending→booked matching and fingerprinting need careful tests with real data from each bank; the user layer must follow a transaction through re-identification.
- **Revisit:**
  - pending-match tolerance and fingerprint fields once a bank returns pending items or drops references (see below)
  - the investment model, when the Trading 212 provider is built
  - a split UI, if receipts become a data source

## What the banks actually send (first live sync, 2026-10-22)

Observed through Enable Banking, restricted mode, first sync with `strategy=longest` run within 10 minutes of linking.

| | BPI (PT) | Revolut (LT entity, PT IBANs) |
|---|---|---|
| Accounts | 2 current accounts | 2 current (EUR, PT IBAN), 1 MAD current, 2 EUR savings without IBAN |
| History returned | About 90 days, even inside the first hour | About 2 years |
| `entry_reference` | On every transaction | On every transaction |
| Pending transactions | None returned | None returned |
| Counterparty name | Never; everything is in the description | On about 91% of transactions |
| `bank_transaction_code` | Present but empty | `CARD_PAYMENT`, `TRANSFER`, `TOPUP`, `EXCHANGE`, `CARD_REFUND`, `ATM`, `FEE`, `REV_PAYMENT` |
| Type hints in the description | Prefixes: `TRF`/`TRANSF.` (transfer), `DD` (direct debit), `dd/mm` (card purchase) | — |
| MCC, balance after, original-currency amount | Never | Never |
| Account name | None: `product` empty, `details` holds the holder's name | `product` empty; savings accounts carry their name in `details` |

Consequences:

- **Identity:** the `entry_reference` path covers every transaction so far; the fingerprint fallback is unused. Keep it for banks that drop references.
- **Pending:** neither bank returned pending items, and asking Revolut explicitly (`transaction_status=PDNG`, last 10 days, main account) returned none either. The user-layer carry-over from pending to booked (M2) is built and tested for banks that do send them, but has nothing to do with these two.
- **Categorization (M2):** rules can't rely on MCCs. Use Revolut's transaction codes and counterparty names, and BPI's description prefixes and text.
- **History:** BPI's 90 days is the limit through this route; accepted, as there's no CSV backfill ([ADR-0003](0003-financial-data-sources.md)).
- **Account names:** the hub uses `product`, else `details` unless it repeats the holder's name, else the IBAN's last four digits or the currency and type.

## Action Items

1. [x] Migrations for the bank-facts tables in the `finance` schema (user-layer tables come with M2).
2. [x] Enable Banking provider: linking, `longest` first fetch, overlapping incremental sync, pending replacement.
3. [x] Dedup test suite (synthetic payloads modelled on real ones). Pending→booked matching moves to M2, with the user layer.
4. [ ] Rules engine plus the category precedence logic.
5. [ ] Recurring detection job.
6. [ ] Budget calculation with per-category rollover and overspend settings.
