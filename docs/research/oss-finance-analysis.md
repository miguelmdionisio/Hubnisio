# Open-source finance software: research findings

Factual notes on how existing projects solve the problems Hubnisio's finance module will face. **Findings only: no recommendations or design.** Design is discussed separately and recorded in `docs/adr/`.

Source: a research pass on 2026-10-22 (shallow clones, read-only), written up from the raw code and docs it read. Code references are to these commits:

| Project | Commit | Date |
|---|---|---|
| firefly-iii/firefly-iii | `b9c31006e8d3008df3d12e23de86b66088c9480e` | 2026-10-17 |
| firefly-iii/data-importer | `9228bb7b435e6c9d90a9120b5cbdc07d540d2925` | 2026-10-21 |
| actualbudget/actual | `d1a536f35c5a114eda0582d5a1d744a9103cc90e` | 2026-10-21 |
| maybe-finance/maybe (archived) | `77b5469832758d1cbee1a940f3012a1ae1c74cd3` | 2025-07-24 |
| we-promise/sure (maintained fork of Maybe) | `bf8d6cc39a102e3d80f8146d88dd31c539329172` | 2026-10-22 |
| ghostfolio/ghostfolio | `0d58df7ce77acaddb657216a03782c9fed2d935d` | 2026-10-22 |
| beancount/smart_importer | `db71e8cd5538d079324472d276708979adc95506` | 2026-07-26 |
| beancount/fava | `b1c45fca96b5f9a26a21093c3056e3bde01bec88` | 2026-10-21 |

## Licenses

| Project | License | Note |
|---|---|---|
| Firefly III | AGPL-3.0-or-later | |
| Firefly III data importer | AGPL-3.0-or-later | |
| Actual Budget | MIT | |
| Maybe | AGPL-3.0 | archived July 2025 |
| Sure | AGPL-3.0 | |
| Ghostfolio | AGPL-3.0 | |
| smart_importer | MIT | |
| Fava | MIT | |
| beancount-import | GPL-2.0-only | |
| Export-To-Ghostfolio | Apache-2.0 | |

Reusing ideas and algorithms is not restricted by these licenses. Close line-by-line translation of AGPL/GPL code would make the result a derivative work under the same license.

---

## 1. Enable Banking API (from Enable Banking's docs)

Sources: [API reference](https://enablebanking.com/docs/api/reference/), [FAQ](https://enablebanking.com/docs/faq), [Portugal market notes](https://enablebanking.com/docs/markets/pt/).

### Authentication

- Every call carries `Authorization: Bearer <JWT>`.
- JWT header: `typ: JWT`, `alg: RS256` (the only algorithm supported), `kid: <application ID>`.
- JWT body: `iss: "enablebanking.com"`, `aud: "api.enablebanking.com"`, `iat`, `exp`. Maximum lifetime 86400 s; longer tokens are rejected.
- Signed with the application's private RSA key.

### Linking flow

1. `POST /auth` with `access.valid_until` (RFC 3339), `aspsp: {name, country}`, `state`, `redirect_url`, `psu_type` (personal/business). Optional: `auth_method`, `credentials`, `language`, `psu_id`. `valid_until` cannot exceed now + `maximum_consent_validity` for that bank (from `GET /aspsps`; 180 days for most banks).
2. The response has `url` (send the user there), `authorization_id`, `psu_id_hash`.
3. The bank redirects back to `redirect_url` with `code` and `state`.
4. `POST /sessions {code}` returns `session_id`, `accounts`, `aspsp`, `psu_type`, `access`.
5. `GET /sessions/{id}` returns status, `accounts` (UIDs), `accounts_data` (`uid` + `identification_hash`), `authorized`, `created`.
6. `DELETE /sessions/{id}` closes the session, and the bank consent too where possible.

Session statuses: `AUTHORIZED`, `CANCELLED`, `CLOSED`, `EXPIRED`, `INVALID`, `PENDING_AUTHORIZATION`, `RETURNED_FROM_BANK`, `REVOKED`.

### Accounts

- `uid`: used to fetch balances and transactions. Valid only while its session is `AUTHORIZED`.
- `identification_hash`: stable across sessions; the documented way to match accounts after re-authorization. `identification_hashes` lists alternatives, which may not be unique and are meant for fuzzy matching.
- `account_id`: primary identifier (IBAN, or `other` with `scheme_name`/`identification`).
- Also: `cash_account_type` (CACC, CARD, CASH, LOAN, OTHR, SVGS), `currency`, `name` (holder names), `product`.
- Re-authorization creates a **new session ID and new account UIDs**. Enable Banking doesn't identify individual users, so cross-session matching relies on `identification_hash` (or raw IBAN / masked PAN / BBAN).

### Balances

`GET /accounts/{uid}/balances` returns `balances[]` with `name`, `balance_amount`, `balance_type`, `last_change_date_time`, `reference_date`, `last_committed_transaction`. Types: CLAV, CLBD (closing booked), FWAV, INFO, ITAV (interim available), ITBD (interim booked), OPAV, OPBD, OTHR, PRCD, VALU, XPCD.

### Transactions

`GET /accounts/{uid}/transactions` takes `date_from`, `date_to` (inclusive, UTC), `continuation_key`, `transaction_status`, `strategy`.

Fields:

| Field | Meaning |
|---|---|
| `entry_reference` | Bank-provided ID. Immutable and unique *within the same identification hash*, so usable across sessions. Not globally unique. |
| `transaction_id` | Only for fetching details. **May change between fetches**; not an identity. Null if details aren't supported. |
| `transaction_amount` | `{amount, currency}`; the amount is unsigned |
| `credit_debit_indicator` | `CRDT` (money in) / `DBIT` (money out) |
| `status` | `BOOK`, `PDNG`, `HOLD`, `SCHD`, `CNCL`, `RJCT`, `OTHR` |
| `booking_date` | Date booked on the account |
| `value_date` | Date funds become / stop being available |
| `transaction_date` | Card transaction date, acquiring date (transfers), or receiving date (direct debits) |
| `creditor`, `creditor_account`, `debtor`, `debtor_account` | Parties and their account identifiers |
| `remittance_information` | **List of strings**: free text and/or reference |
| `reference_number`, `reference_number_schema` | Structured creditor reference, when present |
| `merchant_category_code` | ISO 18245 MCC |
| `bank_transaction_code` | `{description, code, sub_code}` |
| `balance_after_transaction` | Balance after the transaction |
| `note` | User's internal note at the bank |
| `exchange_rate` | `{unit_currency, exchange_rate (string), rate_type: AGRD/SALE/SPOT, contract_identification, instructed_amount}`. `instructed_amount` is the original-currency amount for cross-currency card payments. |

### Pagination, history and fetch strategy

- If a response has a `continuation_key`, repeat the request with it and **all other parameters unchanged**, until none comes back. Empty pages can still carry a key. Page size varies by bank.
- `strategy=default` uses the requested dates and returns `WRONG_TRANSACTIONS_PERIOD` if the range isn't available.
- `strategy=longest` finds the earliest available transaction, ignores `date_to`, and returns empty rather than an error. Meant for first or long-range fetches.
- **Full history is often available only for about an hour after authorization.** After that, many banks limit access to about 90 days.
- Most banks provide at least a year of history; some two to three years or more. Asking for dates before the account opened can error.
- The Control Panel's "Data Insights" shows typical history availability per bank.

### Entry references and pending transactions (FAQ)

- Most banks provide unique `entry_reference` values; some don't, and **some send duplicates**. For some banks Enable Banking generates "synthetic" entry references during processing.
- Entry references are mainly provided for booked (`BOOK`) transactions. A pending (`PDNG`) transaction has one only if the bank's ID stays the same after booking. Otherwise the FAQ says to **exclude pending transactions when matching**.
- No documentation was found on how to link a pending item to its later booked version.

### Rate limits and user-present headers

- Many banks allow **4 data fetches per day** when the user isn't present. On `ASPSP_RATE_LIMIT_EXCEEDED` (429) during background fetching, the guidance is to retry after 6 hours.
- PSU headers (e.g. `Psu-Ip-Address`, `Psu-User-Agent`) signal that the user is actively present, and then background limits don't apply. Send all required PSU headers or none: partial sets return 422 `PSU_HEADER_NOT_PROVIDED`. Scheduled fetches send none; user-triggered fetches send that user's headers.

### Consent expiry

- Renewal is needed only when `valid_until` is reached; there's no separate refresh, and token refresh is internal.
- Sessions can expire early with `EXPIRED_SESSION`. Handle the error code, not the HTTP status, since 401 has other causes. Causes include a newer session replacing an older one, yearly KYC surveys at the bank, and certificate migration.

### Restricted (free) mode

- Free for accessing your own accounts. Only accounts linked in the Control Panel are returned; the application shows as "Restricted" but "Active".
- The terms exclude business or professional use (per the [Terms of Service](https://enablebanking.com/terms)).

### Bank coverage seen

- BPI and Novo Banco: in Enable Banking's Portugal market docs. BPI authorizes through its BPI Net app (biometrics or PIN).
- Revolut: listed by third-party directories ([banq.ai](https://banq.ai/enablebanking/revolut)); not confirmed against Enable Banking's own list.
- Trading 212: no evidence of Enable Banking support found.

---

## 2. How Firefly III's data importer uses Enable Banking

Code: `data-importer/app/Services/EnableBanking/` (about 3,600 lines). Configured with `ENABLE_BANKING_APP_ID`, `ENABLE_BANKING_PRIVATE_KEY` and `ENABLE_BANKING_URL` (default `https://api.enablebanking.com`), in `config/eb.php`.

### Auth and requests

- `JWTManager::generateToken()` creates a fresh RS256 JWT for **every request**, with a 1-hour expiry and `kid` set to the app ID.
- `Request/Request.php`: Guzzle with a 30 s timeout. Optionally adds a `PSU-IP-Address` header from config (a fixed IP, or `autodetect` via icanhazip.com; private and reserved ranges are rejected).

### Linking

`Http/Controllers/Import/EnableBanking/LinkController.php`:

- `build()` posts `/auth` with the chosen bank and country, `state` = import job ID, and `redirect_url` = its callback route. It stores the `authorization_id`, then redirects the user to the bank.
- `PostAuthRequest` defaults `valid_until` to **now + 89 days** (`7_689_600` s) when none is given, and `psu_type` to `personal`.
- `callback()` reads `code` and `state`, then posts `/sessions`. It handles an `ALREADY_AUTHORIZED` error, e.g. when the user refreshes the callback page, by reusing the existing session. It stores the session ID and parses the accounts.

### Account model

`Model/Account.php`:

- Reads `uid`, `identification_hash`, IBAN from `account_id.iban`, and `other` identification.
- Scans `all_account_ids[]` for BBAN/IBAN.
- Also reads currency, owner name, display name, product, `cash_account_type`, usage and details.
- If `identification_hash` is empty, it generates SHA-256 of the account's JSON. It then **hashes the hash again** on fresh API data (comment: "a very annoying value to handle").

### Fetching transactions

`Request/GetTransactionsRequest.php`:

- Optional `date_from`/`date_to`.
- Loops on `continuation_key`, capped at **50 pages**. Ends when the key is empty.
- Doesn't pass `strategy` or `transaction_status`.

`Response/TransactionsResponse.php` accepts two response shapes:

- nested: `{"transactions": {"booked": [...], "pending": [...]}}`
- flat: `{"transactions": [...]}` with a `status` on each item. `BOOK` becomes `booked`, **anything else becomes `pending`**.

### Field mapping

`Model/Transaction.php::fromArray`:

| Firefly field | Taken from |
|---|---|
| identity (`external_id`) | `entry_reference`. The comment dated 2026-03-07 says `transaction_id` was empty in practice. If missing: `eb-` + UUIDv5 of SHA-256 of the whole transaction JSON. |
| amount | `transaction_amount.amount`, negated when `credit_debit_indicator = DBIT` |
| currency | `transaction_amount.currency` |
| date | `booking_date`, falling back to `transaction_date`. `getDate()` then falls back to `value_date`, then "now". |
| payment date | `value_date` |
| counterparty | `creditor.name` / `debtor.name`, plus IBAN, plus BBAN when `other.scheme_name = BBAN`, plus postal `address_line[]` (optionally appended to the name, truncated to 255 chars) |
| description | `remittance_information[]` joined with spaces, falling back to `additional_information` / `note`, then `"(no description)"` |
| notes | `additional_information` when it differs from the description |
| tags | the status (`booked`/`pending`) and `bank_transaction_code.sub_code` |
| `internal_reference` | the account UID |

Not mapped: `exchange_rate`, `merchant_category_code`, `balance_after_transaction`, `reference_number`.

The fallback ID hashes the full JSON. If any field changes between fetches (as it can from pending to booked), the generated ID changes too.

### Filtering

`Conversion/Routine/TransactionProcessor.php::filterTransactions`:

- Drops pending transactions unless the "pending transactions" option is on.
- Drops transactions outside the not-before / not-after dates.
- **Drops zero-amount transactions** with a warning.

The date range options (`all`, `partial` with N days/weeks/months/years, or a fixed range) live in `Services/Shared/Configuration/Configuration.php`.

### Transaction type and transfer detection

`Conversion/Routine/GenerateTransactions.php`:

- Positive amounts become a deposit into the linked account; negative amounts become a withdrawal (amount made positive).
- The counterparty IBAN, or BBAN as `nr_<bban>`, is looked up among the user's existing Firefly accounts. A match on an **asset** account turns the transaction into a **transfer** between the two. IBAN overrides BBAN. Matches on non-asset accounts are ignored.
- A missing counterparty becomes `(unknown source)` / `(unknown destination)`.
- `ApiSubmitter::updateTransactionType` also turns any asset→asset pair into a transfer.

### Duplicate detection

There are two independent layers.

1. **Importer side** (`Services/Shared/Import/Routine/ApiSubmitter.php::uniqueTransaction`, the "cell" method, default for non-file imports):
   - Takes the configured unique field (default `external_id`) and searches Firefly for an exact match (`external_id_is:"…"`).
   - If none, it runs a count query that **also covers deleted transactions**.
   - Any hit skips the transaction.
2. **Core side:** each submission carries `error_if_duplicate_hash`, which triggers Firefly's content hash (see §3). A rejection comes back as the validation error "Duplicate of transaction #…", which the importer can be told to ignore.
   - If a Firefly rule deletes the transaction right after creation (error code `200032`), it's reported as "created, but deleted by a rule".

### Comparison: GoCardless provider

`Services/Nordigen/Model/Transaction.php`:

- Identity: since 2025-09-07 it uses `internalTransactionId`, with the note "never transactionId", falling back to a UUIDv5 of the JSON. `getTransactionId()` **prefixes the account identifier** to make IDs unique across accounts (issue #10914).
- The Enable Banking provider has the same prefixing **commented out**.
- Dates: `bookingDateTime` takes precedence over `bookingDate`.
- Tags: `pending`/`booked` and the merchant category code.
- `currencyExchange` (rate, source/target currency) is written into the notes.
- `FilterTransactions::filter` has a `FIXME`: no real filtering happens.

---

## 3. Firefly III core: ledger, balances, currencies, duplicates

### Ledger model (double-entry)

Tables (from `database/migrations/2016_06_16_000002_create_main_tables.php` plus later migrations):

- **`transaction_groups`** (`title`): one user-visible transaction, possibly split. Linked to journals through `group_journals`.
- **`transaction_journals`**: `transaction_type_id`, `transaction_currency_id`, `bill_id`, `description`, `date` (+ `date_tz`), `interest_date`, `book_date`, `process_date`, `order`, `completed`, soft-delete.
- **`transactions`**: the legs. `account_id`, `transaction_journal_id`, `amount` DECIMAL(32,12), `transaction_currency_id`, `foreign_currency_id`, `foreign_amount`, `native_amount`, `native_foreign_amount`, `reconciled`, `identifier`, and (since 2024) `balance_before`, `balance_after`, `balance_dirty`.
- **`journal_meta`** (`name`, `data`, `hash`): key-value store for extra fields. The list is in `config/firefly.php` `journal_meta_fields`:
  - SEPA fields: `sepa_cc`, `sepa_ct_op`, `sepa_ct_id`, `sepa_db`, `sepa_country`, `sepa_ep`, `sepa_ci`, `sepa_batch_id`
  - extra dates: `interest_date`, `book_date`, `process_date`, `due_date`, `payment_date`, `invoice_date`
  - other: `recurrence_id`, `internal_reference`, `external_id`, `import_hash_v2`, `original_source`, `recurrence_total`, …
- Many-to-many: categories, budgets and tags per journal (`category_transaction_journal`, `budget_transaction_journal`, `tag_transaction_journal`). Older per-transaction pivot tables also exist.
- `journal_links` + `link_types`: user-defined relations between journals (e.g. "refunds").
- `notes`, `attachments`, `locations`: polymorphic.

**How a journal is created** (`app/Factory/TransactionJournalFactory.php::createJournal`):

- Two `transactions` rows: `createNegative()` on the source account, `createPositive()` on the destination.
- Every journal is double-entry. Counterparties (shops, employers) are accounts too, of type Expense or Revenue, created on the fly by name, IBAN or number (`Services/Internal/Support/JournalServiceTrait.php::getAccount`).
- The lookup order is ID → IBAN → account number → name. If a name matches an account with a different IBAN, it retries with the name `"<name> (<IBAN>)"`. If nothing can be found or created, it falls back to a "cash" account.

**Account types** (`app/Enums/AccountTypeEnum.php`): Asset, Beneficiary, Cash, Credit card, Debt, Default, Expense, Import, Initial balance, Liability credit, Loan, Mortgage, Reconciliation, Revenue.

**Transaction types** (`TransactionTypeEnum`): Withdrawal, Deposit, Transfer, Opening balance, Reconciliation, Liability credit, Invalid.

- The type is determined by the account-type pair, via `config/firefly.php` `account_to_transaction` (e.g. Asset→Asset = Transfer, Asset→Expense = Withdrawal, Revenue→Asset = Deposit, Initial balance→Asset = Opening balance).
- Allowed source→destination combinations per type are in `source_dests`.
- Opening balances are journals from an "Initial balance" account; reconciliation differences are journals against a "Reconciliation" account.

### Multi-currency

- Each leg has a currency and an optional foreign currency + amount. Foreign currency is nulled if it equals the main one (`compareCurrencies`).
- **Transfers between accounts in different currencies:** the two legs swap primary and foreign, so each account sees the amount in its own currency in the `amount` column.
- `native_amount` / `native_foreign_amount` (and `native_*` on budgets, bills, piggy banks, available budgets) hold the amount converted to the user's **primary currency**.
  - They're recomputed by observers on every save (`Handlers/Observer/TransactionObserver.php::updatePrimaryCurrencyAmount`), using the rate on the journal's date.
- `currency_exchange_rates` (`from_currency_id`, `to_currency_id`, `date`, `rate`, `user_rate`). The converter is `Support/Http/Api/ExchangeRateConverter.php::getRate`:
  1. Use the most recent rate on or before the date (`date <= ?`, newest first).
  2. Otherwise use the inverse pair, `1/rate`.
  3. Otherwise triangulate through EUR. Config `cer.rates` holds static fallback rates per currency.
  4. If still nothing, return `1`.
  - Results are cached forever per (from, to, date).

### Balances

- **Point-in-time balance** (`Support/Steam.php::accountsBalancesOptimized`):
  - `SUM(transactions.amount)` grouped by account and currency, for journals dated `<=` (or `<`) the date, excluding soft-deleted ones.
  - Plus the account's `virtual_balance`, a user-set offset (e.g. credit limit).
  - Optional conversion to the primary currency.
- **Daily series** (`finalAccountBalanceInRange`): the start balance, then `SUM(amount)` grouped by journal date and currency over the range, accumulated day by day. Converted per day if requested. Cached through `CacheProperties`.
- **Running balance per transaction** (`Support/Models/AccountBalanceCalculator.php`): `balance_before` / `balance_after` are stored on each `transactions` row, with a `balance_dirty` flag.
  - Recalculation walks transactions in a fixed order: date, then `order`, then journal ID, then description, then amount. It starts from the latest clean `balance_after` before the change date.
  - Saves use `saveQuietly()` so observers don't loop.
  - It's behind the `use_running_balance` feature flag.
  - The class docblock says `account_balances` (a 2024 table) is "at the moment unused".

### Duplicate detection (core)

- `TransactionJournalFactory::hashArray()` hashes the whole submitted row (minus `import_hash_v2`, `original_source`, `batch_submission`) with SHA-256 and stores it as `journal_meta.import_hash_v2`.
- `errorIfDuplicate()` runs only when the caller sets `error_if_duplicate_hash`. It looks the hash up across the user's journals, **including soft-deleted ones**, and throws "Duplicate of transaction #<group>".
- Any change to any field (description text, date, amount) gives a different hash.

---

## 4. Firefly III: recurring transactions, bills, budgets, rules, reports

### Recurring transactions

Tables:
- `recurrences`: `first_date`, `repeat_until`, `latest_date`, `repetitions` (0 = unlimited), `apply_rules`, `active`.
- `recurrences_transactions`: the template legs.
- `recurrences_repetitions`: `repetition_type`, `repetition_moment`, `repetition_skip`, `weekend`.
- `recurrences_meta` and `rt_meta`: budget, category, tags, piggy bank, bill.

Repetition types and how dates are computed (`Support/Repositories/Recurring/CalculateRangeOccurrences.php`):

| Type | `repetition_moment` | Notes |
|---|---|---|
| daily | – | |
| weekly | ISO day of week, 1–7 | |
| monthly | day of month | Clamped to the month's length: the 31st becomes the 30th or 28th. |
| ndom | `"n,weekday"`, e.g. `"2,1"` = second Monday | Built by parsing a string like `"second Monday of March 2026"`. |
| yearly | a date | |

- Skip is `repetition_skip + 1`: an occurrence is kept when the attempt counter `% skipMod == 0`.
- Weekend handling (`FiltersWeekends.php`): do nothing, skip creation, move to Friday (`+5 - isoDow`), or move to Monday (`+8 - isoDow`). The resulting dates are de-duplicated.

Creation (`Jobs/CreateRecurringTransactions.php`):
- Runs from a cron (`Support/Cronjobs/RecurringCronjob.php`), at most once per 12 h per user (`last_rt_job_<user>`).
- It skips a recurrence that is inactive, has reached its repetition count, is past `repeat_until`, hasn't started yet, or already fired today.
- It computes occurrences from `first_date` to today + 2 days ("so we always include the weekend") and **creates only the one equal to today**.
  - Re-creation is prevented by counting the day's journals and by `createdPreviously()`, which matches journal meta `recurrence_id` + `recurrence_date`.
- Created journals carry meta `recurrence_id`, `recurrence_total`, `recurrence_count`, `recurrence_date`. Then `latest_date` is updated.
- A day the cron didn't run isn't backfilled, apart from the +2-day window.

### Bills (shown as "subscriptions" in the search operators)

- `bills` table: `name`, `amount_min`, `amount_max`, `date` (the anchor), `repeat_freq` (daily, weekly, monthly, quarterly, half-year, yearly), `skip`, `end_date`, `extension_date`, currency.
  - `match`/`automatch` are legacy columns. `Console/Commands/Upgrade/UpgradesBillsToRules.php` turned them into rules: `description_contains` the match words, plus `amount_exactly`, or `amount_less` + `amount_more`, plus a `link_to_bill` action.
- **Matching to transactions is done by rules** (the `link_to_bill` action sets `transaction_journals.bill_id`). If a bill is renamed, `Listeners/Model/Bill/UpdatesRulesForChangedBill.php` rewrites the rule triggers and actions that referenced the old name.
- **Expected dates:** `Support/Models/BillDateCalculator.php::getPayDates` steps from the anchor date by period × (skip+1). It keeps dates `>= earliest` and after `lastPaid`. Two special cases:
  - It tracks the period difference to force progress when a short month blocks the jump (issue #8401).
  - It subtracts a day when the anchor sits within 4 days of month end (issue #8401).
  - There's a loop cap of 31.
- **Paid / unpaid** (`Repositories/Bill/BillRepository.php`):
  - `nextExpectedMatch` moves to the following period if a journal is already linked in the current one.
  - `sumUnpaidInRange` = (expected dates − linked journals) × average of `amount_min` and `amount_max`.
  - `sumPaidInRange` sums the linked journals.

### Budgets

Tables:
- `budgets`
- `budget_limits`: `budget_id`, `start_date`, `end_date`, `amount`, currency, `generated`.
- `available_budgets`: per-period total income to distribute.
- `auto_budgets`: `budget_id`, currency, `auto_budget_type`, `amount`, `period`.

Spent (`Repositories/Budget/OperationsRepository.php::sumExpenses`) = withdrawals in the range linked to the budget, per currency. A comment says excluding transfers to liabilities was disabled on 2024-12-24.

Auto-budgets (`Jobs/CreateAutoBudgetLimits.php`):
- Run on the period's "magic day": daily; Mondays; the 1st of the month; 01-01/04-01/07-01/10-01; 01-01/07-01; 01-01. They're also cron-gated at most once per 12 h.
- A new limit is created only when the period has none.

| Type | New limit for the period |
|---|---|
| **reset** (1) | the fixed amount |
| **rollover** (2) | `amount` + whatever was left last period (`previous_limit + spent`, where spent is negative); nothing is carried when overspent |
| **adjusted** (3) | `previous_limit + amount + spent`. Overspending is subtracted; if the result is ≤ 0, the limit is set to `1`. |

### Rule engine

Tables:
- `rule_groups` (ordered)
- `rules`: `order`, `active`, `strict`, `stop_processing`
- `rule_triggers` and `rule_actions`: type, value, order, active, `stop_processing`
- A `user_action` trigger with value `store-journal`, `update-journal` or `manual-activation` sets when the rule runs.

How it runs (`TransactionRules/Engine/SearchRuleEngine.php`):
- **Rules are compiled into searches.** Each trigger becomes a search operator.
  - Strict rules: all triggers in one search (AND).
  - Non-strict rules: one search per trigger, results merged (OR). A trigger's `stop_processing` ends that loop once it matches.
- On create or update (`Listeners/Model/TransactionGroup/ProcessesNewTransactionGroup.php` → `processRules`), the engine runs each rule group with an extra `journal_id:<id>` operator, so the search is limited to the new journal.
- Inside a group: when a rule fires and has `stop_processing`, the group stops. Actions run in order, and an action with `stop_processing` stops the remaining actions once it acted.
- 235 search operators are defined in `config/search.php`, covering:
  - description, notes, account name/number/IBAN, category, budget, bill/subscription, tags, `external_id`, `internal_reference`
  - six date kinds (on/before/after each), amount and foreign amount ranges
  - attachments, currency
  - source/destination balance comparisons, e.g. `source_balance_gte`
  - Operators prefixed with `-` are negated.
  - The query parser (`Support/Search/QueryParser/QueryParser.php`) supports nested groups up to depth 32.
- 30 action classes (`TransactionRules/Actions/`): set/clear category and budget; add/remove tags; set, append or prepend description and notes; set source/destination account or cash; convert to deposit/withdrawal/transfer; switch accounts; set amount; link to bill; update piggy bank; delete transaction.
  - Action values can be expressions over transaction fields (`TransactionRules/Expressions/ActionExpression.php`).

### Reports, net worth, caching

- **Net worth** (`Helpers/Report/NetWorth.php::byAccounts`): point-in-time balances per account, **minus `virtual_balance`**, summed per currency or converted to the primary currency.
  - Accounts can opt out through the account meta `include_net_worth`.
  - The report chart (`Http/Controllers/Chart/ReportController.php::netWorth`) samples **every 7 days**. A `TODO` notes liabilities aren't included.
- **Period statistics:** `period_statistics` (2025) caches count + amount per (model, currency, start, end, type). Models are accounts, budgets, categories, tags, plus prefixed totals like `all_*`, `no_budget`, `no_category`, `no_tag`.
  - Entries are deleted for the affected dates whenever transactions change (`SupportsGroupProcessingTrait::removePeriodStatistics`).
- **Cache keys** (`Support/CacheProperties.php`) include the user's `lastActivity` value, which is bumped on every change. So any write invalidates all cached reports for that user.
- **Exchange rates** are downloaded weekly per currency from `https://ff3exchangerates.z6.web.core.windows.net/<year>/<isoWeek>/<code>.json` (`Jobs/DownloadExchangeRates.php`).
- **Roles:** `UserRoleEnum` defines read-only and manage permissions per area (transactions, budgets, subscriptions, rules, recurring, …), plus `full` and `owner`, for shared "user groups".

---

## 5. Trading 212 API (from docs.trading212.com)

- **Status and scope:** beta. Invest and Stocks ISA accounts only. Live base URL `https://live.trading212.com/api/v0`; demo `https://demo.trading212.com/api/v0`.
- **Auth:** HTTP Basic with `API_KEY:API_SECRET`. Keys can be IP-restricted and carry per-area scopes.
- **Endpoints:**
  - `GET /equity/positions` (1 req/s)
  - `/equity/account/summary`
  - `GET /equity/history/orders`, `/history/dividends`, `/history/transactions`, each 20 req/min
  - `POST` / `GET /equity/history/exports`: asynchronous CSV reports; request one, then poll its status
  - Pies endpoints are deprecated.
- **Pagination:** cursor-based. `limit` ≤ 50; follow `nextPagePath` until it's null. Rate limits are per account and reported in `x-ratelimit-*` headers.
- **CSV export columns** (seen in third-party converters): Action, Time, ISIN, Ticker, No. of shares, Price / share, Currency, Exchange rate, Total, ID. Export-To-Ghostfolio (Apache-2.0) converts this export.

---

## Not yet written up

These were read during the research pass but aren't summarized yet:

- **Actual Budget:** bank-sync reconciliation and fuzzy dedup (`packages/loot-core/src/server/accounts/sync.ts`); its Enable Banking integration (`packages/sync-server/src/app-enablebanking/`); transfers (`transactions/transfer.ts`); **automatic recurring-schedule detection** (`schedules/find-schedules.ts`); rules (`rules/`, `transactions/transaction-rules.ts`); envelope budgeting (`budget/envelope.ts`); forecasting (`server/forecast/`).
- **Sure (Maybe fork):** its own **Enable Banking** importer (`app/models/enable_banking_item/importer.rb`, `enable_banking_entry/processor.rb`) and **Trading 212** provider (`app/models/provider/trading212.rb`, `trading212_account/activities_processor.rb`); recurring detection (`recurring_transaction/identifier.rb`, `matcher.rb`, `price_change_detector.rb`); auto transfer matching (`family/auto_transfer_matchable.rb`); LLM and Bayes categorization (`family/auto_categorizer.rb`, `bayes_categorizer.rb`, `provider/openai/auto_categorizer.rb`, `auto_merchant_detector.rb`); AI assistant functions (`assistant/function/*.rb`); balance materialization (`balance/materializer.rb`); account sharing (`account_share.rb`).
- **Ghostfolio:** portfolio calculators (`apps/api/src/app/portfolio/calculator/roai/`, `twr/`) and the Prisma schema.
- **smart_importer:** ML categorization (`predictor.py`).
- **Fava:** budgets (`core/budgets.py`), ingest (`core/ingest.py`).
