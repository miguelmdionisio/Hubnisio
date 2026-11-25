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
  - *(Added in M4)* An `ai` category comes only from `analytics.suggest_category` ([ADR-0006](0006-ai-access.md)). A rules run keeps it until a rule or a merchant's default applies, and drops it if the transaction becomes a transfer.
- **Rules:**
  - Ordered rules; each has conditions (match all / any) on description, counterparty, amount range, account, MCC and direction, and actions (set category, tag, counterparty, mark as transfer).
  - They run when transactions arrive and can be re-run on demand. "Stop processing" is available per rule.
- **Counterparties:** a cleaned-up name with aliases (e.g. "CONTINENTE MATOSINHOS 4450" → Continente) and an optional default category. A name the bank sends becomes a counterparty automatically; one set by hand is never replaced. A merchant can also be created by name, for a brand rule or a transaction to point at; a name that compares the same (`match_key`) as an existing merchant's is refused. A brand rule leaves the per-branch merchants empty, so the Merchants page hides unused ones by default. *(Added before M4.)*
- **Rule actions** are recomputed on every run, so editing or deleting a rule takes effect everywhere. Tags a rule adds are kept apart from tags added by hand, which a run never touches.

### Transaction kind and transfers *(added in M2)*

- A transaction's kind (expense, income or transfer) is derived, not stored, in this order: transfer if it's in a transfer pair or overridden; then its kind override; then *(amended before M4)* the kind of its category; then its sign. An override (by hand or by a rule) covers moves the sign gets wrong, e.g. a deposit to a broker the hub doesn't sync yet.
- **A category decides the kind** of a transaction that isn't a transfer and has no override: money in with an expense category is an expense (a repayment or refund, see "Repayments and refunds"), and money out with an income category is income. Without a category the sign decides, as before. `kinds.kind_is` (the Transactions list's `kind` filter) and `transactions_api._out` (the row's `kind`) both follow this.
- **Transfer pairs** are linked automatically when exactly one match exists: same currency and amount, opposite directions on two of the household's accounts, at most 3 days apart. Ambiguous matches are left alone. Unlinking a pair records a dismissal, so matching never links it again.
- Transfers are excluded from income, spending and categories.

### Recurring payments: detected, not scheduled

- `recurring_series` is filled by a detection job, not entered by hand. The job groups transactions by counterparty and similar amount, looks for a regular cadence (weekly / monthly / quarterly / yearly, each within a tolerance), and requires at least 3 occurrences.
- Each series stores its cadence, expected amount, last seen date, next expected date and status (active / dormant / cancelled).
- It's used for the subscription list, expected upcoming payments (forecasting) and price-change alerts.
- The user can confirm, edit, or dismiss a detected series.
- **Decided in M3:**
  - **Per account:** a series belongs to one account and has its visibility, so a private account's subscriptions never show to another member.
  - **Grouping:** by merchant, else by the description without digits (BPI sends no merchant names), and by direction. Income such as a salary is detected too.
  - **Chains:** within a group, chains are built in date order.
    - Each gap must fit the cadence: weekly 7±2 days, monthly 30.4±5, quarterly 91±10, yearly 365±20. One missed payment is allowed, plus one more per six made.
    - Each amount must be within 30% of the chain's recent ones, so a price rise stays one series and gives a price-change hint.
    - A chain needs 3 payments and at most half as many other similar payments to the same payee in its span. Otherwise shopping every few days would pass as weekly.
    - Payments left over get a second chance with any amount, on the monthly or slower cadences, marked "varies" (utilities).
  - **Review state is separate from status.** Review is suggested, confirmed or dismissed. Status is active, dormant (a payment is late) or cancelled (three missed, or the user said it stopped).
    - Only confirmed series count in upcoming payments and the dashboard.
    - Each run updates the series that share a transaction with what it finds, keeping the review, the user's name and a cancellation. So a dismissal is never suggested again.
    - A chain that's already over when first found isn't suggested.
  - **Edit means rename in M3.** Changing the cadence or the expected amount by hand is deferred until it's needed.
  - **When it runs:** after each sync and each rules run, and from `cli detect-recurring`.

### Budgets

- A budget is a monthly limit per category (other periods possible later).
- Everything is **configurable per category**:
  - `rollover`: off (reset every period) or on (unspent money carries into the next period).
  - `overspend`: `forgive` (the next period starts fresh) or `carry` (the overspend is subtracted from the next period).
- Defaults: everyday categories reset; when rollover is on, overspending carries.
- Spending counts booked, non-transfer transactions assigned to the category, with child categories rolling up to their parent.
- **Decided in M3:**
  - **Month:** a budget month is the calendar month, from the 1st.
  - **Currency:** budgets are in EUR. Spending is the net spending of "Spending and cash flow" below, so refunds lower it.
  - **Limits are effective-dated** (`budget_limits`: an amount from a month on, until the next). Changing a budget "from this month" keeps past months, and their rollover, as they were.
  - **Group and category budgets:** a budget can be on a group or on a category. A group's spending includes its categories. When both are budgeted, the group is the cap and its categories are sub-limits, and totals count only the top budgeted level. Income categories can't be budgeted.
  - **Computed on read:** from the budget's first month to the month asked for, with no job. This differs from Firefly, which materializes each period's limit with a cron job.
  - **Privacy:** budgets belong to the household, but the spending shown against one counts only the accounts the viewer may see.
- **Global budget** *(added before M4)*:
  - **What it is:** one cap on all spending, next to the category budgets. A budget row with a null `category_id` is the household's overall budget; a partial unique index allows one per household.
  - **What it counts:** all spending, uncategorized included. This is the same figure as cash flow's spending (`total_spending`), so the two agree by construction. Category budgets stay sub-limits within it, and their totals still count only the category budgets.
  - **Settings:** the same as a category budget's: rollover, overspend, and effective-dated limits.
  - **Where:** `compute_budgets` is pure (limits plus monthly sums in, figures out), so M4's analytics views can feed it too.

### Balances and net worth

- `balance_snapshots`: the bank-reported balance (booked and available) for each account on each sync. This is the source of truth for balances.
- Transactions explain the movement between snapshots. Balances between snapshots are interpolated from transactions.
- Net worth = the sum of the latest balances across accounts (investments at market value), in EUR via `fx_rates` (daily rates). Accounts can be excluded from net worth.
- **Net worth over time** *(added in M3)*. It's computed on read, over the accounts the viewer may see.
  - **Anchor:** each account's latest snapshot. The booked balance (CLBD, ITBD, XPCD) is preferred over an available one, which can include an overdraft. The Accounts page still shows the spendable balance first.
  - **Earlier days:** the balance on a day is the anchor moved by the booked transactions between that day and the anchor's date (its reference date, else the day it was fetched). Each day is converted at that day's rate.
  - **Start:** the first day for which every included account has data. Before that, at least one account's movements are unknown (BPI gives about 90 days).
    - A bank gives every account of one consent the same history, so an account's data starts with the earliest transaction of any account on its connection. An account opened later was simply empty before its first transaction. Going by each account's own first transaction would have started on 2026-08-03 instead of 2026-07-24, because one BPI account had nothing in its first ten days.
    - Accounts without transactions count at their anchor throughout.
    - A later `date_from` can shorten the series, not lengthen it.
  - **Missing data:** an account without a snapshot is listed without a balance. An account-day without a rate is left out of that day's total and counted.
  - *(M4)* `net_worth` loads the inputs (`load_inputs`) and `compute_net_worth` computes from them, so the MCP server loads the same inputs from the `analytics` views and gets the same figures ([ADR-0006](0006-ai-access.md)).

### Retiring an account *(added before M4)*

- **Hide** (`accounts.hidden_at`): the lasting way to retire an account the bank still offers, such as an unused savings pot. Only the account's owners can hide or unhide it, and hiding applies to the whole household.
  - **What leaves:** account lists and filters, net worth and upcoming payments. The sync stops fetching it.
  - **What stays:** its past transactions stay listed and keep counting in spending, cash flow, budgets and recurring detection.
  - **Re-linking:** a re-link matches the account by `identification_hash`, so it stays hidden.
  - **Unhiding:** the sync resumes from two weeks before its latest booked transaction. Anything older than the bank's history (about 90 days at BPI) is lost.
- **Delete:** owners only. It removes the account, and the foreign keys cascade to its transactions, their user layer, its balance snapshots, provider links, recurring series and transfer pairs.
  - **Confirmation:** an account with transactions needs `confirm=true`. Without it, the API answers 409 with the transaction count and the number of transfer pairs with other accounts, and the dialog asks for the account's name.
  - **Transfers:** a pair's side on a kept account becomes a transfer on its own: `kind_override = transfer` with source `auto`, unless its kind was set by hand. Spending and income don't change. The rules engine leaves an `auto` kind alone. Pairing that side by hand, or unlinking a new pair it joins, clears it.
  - **A plain delete:** if the bank still offers the account, a re-link creates it again, and the next sync brings back what the bank still has. So the UI says to hide such accounts instead.
- **Scoping:** `finance/scoping.py` has two account sets ([ADR-0005](0005-household-data-model.md)). `visible_account_ids` includes hidden accounts and serves everything about past transactions. `listed_account_ids` leaves them out and serves lists, filters, net worth and upcoming payments.

### Spending and cash flow *(added in M3)*

- **What counts:** booked transactions that aren't transfers, in EUR at the rate on their date. Pending transactions don't count.
- **Net per category:** a category's sum is net, so a refund categorized as Groceries lowers Groceries. Child categories roll up into their group.
- **Split-ready:** sums use the assignment's amount when it has one, so splits will work without a change.
- **Without a category:** a transaction counts by its kind (expense or income) and shows as "Uncategorized".
- **Cash flow** is built from the same sums: income categories plus uncategorized income, against expense categories plus uncategorized spending. So it always agrees with the category chart.
- **Computed on read,** with no job and no cache tables (unlike Firefly's `period_statistics`). Revisit if it gets slow.

### Shared pots and the Mine view *(added before M4)*

- **The model** is in [ADR-0005](0005-household-data-model.md), "Shared pots and two views". Spending, cash flow, budgets and net worth take `view=personal|household`, `personal` (Mine) by default.
- **Mine's sums** (`insights.spending.monthly_sums`): transactions on `mine_account_ids` only. A transfer pair whose other side is on a pot isn't a transfer there: the viewer's side counts by its sign in the pot's `pot_category_id`, ignoring any category or kind set on the transaction, or as uncategorized by its sign without one. So a contribution is spending, and money back from the pot lowers that category's spending. Pairs between the viewer's own accounts stay transfers.
- **Downstream:** spending, cash flow, category budgets and the overall budget all read those sums, so they follow the view. Mine's net worth sums `listed_mine_account_ids`, so the pot's balance is left out.
- **The pot's category:** an expense category of the household, not archived. Deleting it sets the pot to none (`ON DELETE SET NULL`), and its contributions become uncategorized. Only a transfer pair makes a move a contribution: a move marked as a transfer but left unpaired stays out of Mine's sums.
- **Household** is unchanged: the same sums and net worth as before G5.

### Repayments and refunds *(added before M4)*

- **Money in with an expense category counts as negative spending in that category, not as income.** The partner sends 600 towards a 1,200 rent, both in Rent: Rent is 600. A friend repays a 30 lunch: it's 0. The sums already worked this way ("Net per category", above); this makes the rest agree: the transaction's kind is "expense", so the Transactions list's kind filter and the row show it that way. Money out with an income category is income in the same way.
- **Rules can do it automatically.** A rule can set an expense category on money in, with the conditions that exist today: for example direction `in`, amount `between` two figures, and counterparty `contains` a name.
- **Below zero:** a category that nets below zero in a month shows the net. Tables and budgets show a negative spent, with remaining above the limit, and rollover evens it out over the months (a remainder carries forward whether it came from unspent budget or from repayments). Bars in the spending chart dip below zero (`stackOffset="sign"`), and the donut, which can't draw a negative slice, lists it in its note. The overall budget and cash flow's spending subtract it too, and income is untouched.
- **Display:** the Transactions page shows such a row as "+€50" in the normal colour, not income green, with a "Repayment" hint, or "Refund" for a card refund (Revolut `CARD_REFUND`, BPI `dev. compra`). The transaction's sheet says "Lowers Rent by €50".
- **Refunds take their merchant's rule or default category,** like any payment. The automatic `dev. compra` → Income › Refunds rule is turned off. The Refunds category stays, for picking by hand.
- **Option B is left open:** a `repayment_links` table (repayment → payment, amount) would take precedence over the category for the amounts it covers, and would date them to the payment's month, so a repayment in March for a February payment lowers February. This would fit a partial repayment of a single payment more exactly, at the cost of linking each one. Nothing here blocks it: it would add a table and change how `monthly_sums` dates those amounts, and nothing else.

### FX rates *(added in M3)*

- **Base currency:** EUR, a constant rather than a setting. Every insight is in EUR.
- **Table:** `fx_rates` has one row per currency and day: how many units of the currency one euro buys. It is global (public data, no household) and records each rate's source.
- **Sources:**
  - **ECB reference rates** (ECB Data Portal API, no key) for every currency the ECB still publishes. It is the official daily reference, and one request returns a whole range.
  - **fawazahmed0's currency-api** (keyless, CC0, one dated file a day since 2024-03-02, jsDelivr with a pages.dev fallback) only for the rest. Today that is the Moroccan dirham.
  - **"Covered" means current.** The ECB does have a dirham series, but it stopped on 2020-10-30 and is marked indicative. A currency counts as the ECB's only if its newest rate is under 30 days old.
- **Which currencies:** every non-euro currency of an account, a transaction (its own or its original currency) or a balance snapshot.
- **Filling:**
  - The daily task `fetch_fx_rates` (16:00 UTC, after the ECB publishes) fetches what is missing since each currency's last stored day. A currency with nothing stored starts at the earliest transaction.
  - `cli fx-backfill [--since]` checks the whole range from a day (default: the earliest transaction) and writes only missing or changed rates.
  - currency-api needs a request per day, so a backfill samples it weekly and the last two weeks daily. The dirham is pegged to a basket and moves well under 1% a week.
  - One currency failing doesn't stop the others. The job then fails, and the next day's run fills the gap.
- **Conversion (`finance/fx/convert.py`):**
  - An amount is divided by the latest rate on or before its date, if that rate is at most 10 days old. That covers weekends, bank holidays and the weekly sampling.
  - With no such rate the result is NULL, and callers leave the amount out and count it as unconverted. There is no 1:1 fallback: Firefly silently treats a missing rate as 1, which would put a dirham amount in the totals as euros.
  - The SQL expression `eur_amount` is unrounded so that sums stay exact; `to_eur` rounds a single value to 4 decimal places.
- **Gaps:** dirham amounts before 2024-03-02 can't be converted.

### Investments (Trading 212)

- A separate sub-model: instruments (ISIN, ticker, currency), trades, dividends, cash movements, holdings, prices.
- Its performance model will be decided when that provider is built. *(Decided in [ADR-0008](0008-investments.md).)*

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

## What the banks actually send (first live sync)

Observed through Enable Banking, restricted mode, first sync with `strategy=longest` run within 10 minutes of linking.

| | BPI (PT) | Revolut (LT entity, PT IBANs) |
|---|---|---|
| Accounts | Current accounts | Current accounts (EUR with a PT IBAN, other currencies), savings accounts without an IBAN |
| History returned | About 90 days, even inside the first hour | About 2 years |
| `entry_reference` | On every transaction | On every transaction |
| Pending transactions | None returned | None returned |
| Counterparty name | Never; everything is in the description | On most transactions |
| `bank_transaction_code` | Present but empty | `CARD_PAYMENT`, `TRANSFER`, `TOPUP`, `EXCHANGE`, `CARD_REFUND`, `ATM`, `FEE`, `REV_PAYMENT` |
| Type hints in the description | Prefixes: `TRF`/`TRANSF.` (transfer), `DD` (direct debit), `dd/mm` (card purchase) | — |
| MCC, balance after, original-currency amount | Never | Never |
| Account name | None: `product` empty, `details` holds the holder's name | `product` empty; savings accounts carry their name in `details` |

Consequences:

- **Identity:** the `entry_reference` path covers every transaction so far; the fingerprint fallback is unused. Keep it for banks that drop references.
- **Pending:** neither bank returned pending items, and asking Revolut explicitly (`transaction_status=PDNG`) returned none either. The user-layer carry-over from pending to booked (M2) is built and tested for banks that do send them, but has nothing to do with these two.
- **Categorization (M2):** rules can't rely on MCCs. Use Revolut's transaction codes and counterparty names, and BPI's description prefixes and text.
- **History:** BPI's 90 days is the limit through this route; accepted, as there's no CSV backfill ([ADR-0003](0003-financial-data-sources.md)).
- **Account names:** the hub uses `product`, else `details` unless it repeats the holder's name, else the IBAN's last four digits or the currency and type.

### First categorization run (`cli recategorize`)

Run over the whole history with the seeded rule set and no merchant defaults. What it showed:

- **Without rules or merchant defaults the engine has little to go on.** Revolut's names created merchants for most of its transactions; BPI got none, as it sends no names. Only the hand-set categories and the seeded `EXCHANGE` rule applied.
- **BPI → Revolut top-ups don't always pair.** Some Revolut `TOPUP`s have no BPI outflow of the same amount within 3 days, as they're funded some other way. A BPI outflow with two same-amount Revolut candidates was correctly left unlinked.
- **Revolut names are per branch, not per brand.** One brand can arrive under dozens of spellings, and a few merchants cover a large share of named transactions. Setting a default per merchant is too slow; a rule on `bank_counterparty starts_with <brand>` that sets one merchant collapses the spellings, and that merchant's default category then covers them all.
- **BPI descriptions carry the merchant after the card reference** (`dd/mm COMPRA <ref> <MERCHANT …>`), so a `description contains` rule can set the same merchant that Revolut's name created, and one category default then serves both banks.
- **`TRF` is not "transfer".** `TRF SEPA+ INST` and `TRF CR INTRAB` are mostly payments to and from other people. Only transfers between the household's own accounts are transfers; marking every `TRF` would hide real spending.
- **Patterns worth a rule on BPI:** `comissao` (includes the VAT on it), `imposto`, `lev. atm`, `reforco bpi poupanca` (a move to savings), `dev. compra` (refunds in), `paypal`, and card purchases by merchant name.

### First insights run (M3)

- **Net worth** starts at the earliest date every account has history for (BPI's 90 days), and today's total equals the sum of the accounts' balances with no account-day unconverted. Going by each account's own first transaction would start later when an account is quiet in its first days.
- **Spending** works but tells little until rules exist: almost everything was uncategorized.
- **Recurring:** BPI series have only about 3 payments each (its 90 days). No long same-amount Revolut subscriptions turned up, and weekly-rhythm groups weren't linked, which is right: they look like habits, not subscriptions.
- **The first rule for "other payments in the span" was too loose.** Allowing as many as the chain's own let shopping every three days pass as two interleaved weekly series. Half is the limit now.

### Brand rules run (G3)

The table was built from read-only aggregates of uncategorized outgoing Revolut card payments, and the user approved it before anything was written. Then, through the API: new merchants with a default category, rules that set a merchant (any of `bank_counterparty starts_with <brand>`, plus `description contains` where BPI also names the brand; "Uber Eats" stops processing before "Uber"), default categories on existing merchants, and "Run rules now". It roughly doubled the categorized share. What it showed:

- **A brand word in a description isn't safe on its own.** Revolut transfers between people carry free-text references that can name a brand. So brands match on Revolut's name only, and BPI conditions use longer phrases (`uber trip`, `uber com`). With these, no rule matched anything but card payments, apart from a few card refunds and zero-amount entries.
- **A few brands carry much of the gain.** A couple of frequent shops covered nearly half of what the run categorized.
- **What's left is a long tail of single merchants** whose category can't be told from the name, merchants trading under a person's name, and payment processors that front many shops. The Merchants page's "Needs a category" filter lists them, most used first.

### First AI categorization pass (M4)

The user ran ADR-0006's `categorize_uncategorized` prompt from Claude Code against the live data. The suggestions count at once and wait for review on the Transactions page ("Suggested by AI"), where approving one makes it the user's own.

## Action Items

1. [x] Migrations for the bank-facts tables in the `finance` schema (user-layer tables come with M2).
2. [x] Enable Banking provider: linking, `longest` first fetch, overlapping incremental sync, pending replacement.
3. [x] Dedup test suite (synthetic payloads modelled on real ones). Pending→booked matching moves to M2, with the user layer.
4. [x] Rules engine plus the category precedence logic (M2).
5. [x] Recurring detection job.
6. [x] Budget calculation with per-category rollover and overspend settings.
