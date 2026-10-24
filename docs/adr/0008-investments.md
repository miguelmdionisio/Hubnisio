# ADR-0008: Investments (Trading 212)

**Status:** Accepted
**Date:** 2026-10-24
**Deciders:** Miguel Dionísio

## Context

- Trading 212 comes from its own API, with a read-only key ([ADR-0003](0003-financial-data-sources.md)). Investments get their own sub-model, and the performance model was left for when the provider is built ([ADR-0007](0007-finance-domain-model.md), "Investments").
- What the user has: one Invest account, with pies or AutoInvest and interest on uninvested cash. No Trading 212 card, no second account.
- Money already moving there: the banks show 4 deposits to Trading 212 (about €5,180) and 1 withdrawal (€3,000). With no Trading 212 side to pair them with, they count today as spending and as income.
- M5 (the server) is deferred, so nothing here may need an always-on machine.

What the API offers (Public API v0, beta, read 2026-10-24 at docs.trading212.com):

- **Accounts:** Invest and Stocks ISA only. Amounts are in the account's primary currency; multi-currency accounts aren't supported.
- **Auth:** an API key and secret, sent as HTTP Basic. The key's permissions are chosen when it's created (account data, history, portfolio, orders), so it can be read-only. It can be restricted to IP addresses. Live and demo have separate keys.
- **Rate limits:** per account, whatever the key. Every response carries `x-ratelimit-*` headers.
- **Read endpoints:**

| Endpoint | What it gives | Limit |
|---|---|---|
| `GET /equity/account/summary` | Account number and currency; cash (available, in pies, reserved for orders); investments (current value, cost, realised and unrealised result); total value | 1 per 5 s |
| `GET /equity/positions` | Per holding: instrument (ticker, ISIN, name, currency), quantity (and in pies), average price and current price in the instrument's currency, value, cost, result and FX impact in the account's currency | 1 per s |
| `GET /equity/history/orders` | Orders with their fill: price, quantity, FX rate, net value, realised result, taxes and fees; fill types include splits and other corporate actions | 20 per min |
| `GET /equity/history/dividends` | Amount (account currency, and in euros), gross per share, quantity, type, paid on, reference | 20 per min |
| `GET /equity/history/transactions` | Cash movements: deposit, withdraw, fee, transfer, interest on free cash, lending interest | 20 per min |
| `GET /equity/metadata/instruments` | Every tradable instrument: ticker, ISIN, currency, type | 1 per 50 s |
| `POST`/`GET /equity/history/exports` | CSV reports, generated asynchronously | 1 per 30 s / 1 per min |

- **Paging:** the history endpoints page newest first, at most 50 items a page, with a cursor; `nextPagePath` is the next request, null at the end.
- **Not in the API:** price history, card payments, and pies as a structure (the pies endpoints are deprecated; orders a pie places appear in the order history).

## Decision

### The account and its cash

- **One hub account per Trading 212 account,** flagged as an investment account. Its value is its cash plus its holdings at market value. It has owners and visibility like any account ([ADR-0005](0005-household-data-model.md)).
- **Cash movements are transactions** on that account, written only by the sync, like the banks' ([ADR-0007](0007-finance-domain-model.md), "Three layers"): deposits, withdrawals, fees, transfers, interest on cash, lending interest, and dividends. Each carries its Trading 212 type as its bank code, and its reference, prefixed by its endpoint, as its entry reference.
- **So the existing machinery applies:**
  - a deposit pairs with the bank's outflow as a transfer (same amount, opposite directions, at most 3 days apart), which takes the 5 existing moves out of spending and income;
  - seeded rules on the bank code set the categories: dividends → Income › Dividends (a new seeded category), interest → Income › Interest, fees → Bills & fees › Bank fees;
  - a `TRANSFER` (between Trading 212 accounts) is marked as a transfer by a seeded rule.
- **Trades aren't transactions.** A buy moves cash into a holding inside the same account, so it's neither spending nor income. Fees and taxes on a trade are costs in its result (see "Returns"), not spending.
- **Pies:** not modelled. Their cash counts as cash, and their holdings and orders come through positions and the order history.
- *(As built in T1)* The details:
  - **Bank codes** are the type with a `T212_` prefix (`T212_DEPOSIT`, `T212_WITHDRAW`, …, and `T212_DIVIDEND`, with the dividend's own type as `sub_code`). Revolut already sends `TRANSFER` and `FEE`, so a rule on the bare type would mark Revolut payments to other people as transfers.
  - **Entry references:** `transactions:<reference>` and `dividends:<reference>`.
  - **Signs:** withdrawals and fees are made money out whatever sign they come with; every other type keeps Trading 212's sign, so a deposit or interest is money in and a transfer goes either way. *Confirmed at the first live sync (2026-10-24):* deposits and interest come positive, withdrawals and fees negative, and a transfer either way.
  - **Dates:** a movement's day is its timestamp's UTC day. **Text:** no counterparty; the description names the type ("Deposit", "Interest on cash", "Dividend: <name> (<ticker>)").
  - **Seeded rules**, after the Revolut exchange rule: `T212_DIVIDEND` → Income › Dividends; `T212_INTEREST_ON_FREE_CASH` or `T212_LENDING_INTEREST` → Income › Interest; `T212_FEE` → Bills & fees › Bank fees; `T212_TRANSFER` → kind transfer. Dividends sits between Interest and Other income.
  - *(Added after the first live sync, 2026-10-24)* `T212_DEPOSIT` or `T212_WITHDRAW` → kind transfer. Money only moves to and from the member's own accounts. Pairing runs before rules, and only a kind set by hand stops it, so a deposit still pairs with the bank's side when the hub has it. The rule covers those it doesn't: 8 deposits and 3 withdrawals predated BPI's history in the hub, and counted as income and spending. If a bank's side fails to pair (amounts differing by a fee, say), it counts on its own until linked by hand.
  - **Pairing:** a newly linked account's first sync pairs transfers across all history, not the usual last 60 days, so deposits older than that pair too.

### Trades, instruments and holdings

- **Instruments:** global, like `fx_rates` (public data): Trading 212's ticker, ISIN, name, currency and type.
- **Fills:** bank facts, written only by the sync, one row per order fill: instrument, side, fill type, quantity, price, FX rate, net value, realised result, and taxes and fees. Identity is Trading 212's fill id.
- **Holding snapshots:** what `positions` returns on each sync. The latest is the anchor for quantities, as a bank balance is for cash.
- **Raw first:** every response goes to `provider_payloads` before it's applied, and normalization can be re-run from it ([ADR-0003](0003-financial-data-sources.md)).
- *(As built in T2)* The details:
  - **Fetch order:** the summary and positions first, so the two agree; then cash movements, dividends and orders; then the instrument list. Payload kinds `positions`, `orders` and `instruments`. Positions and the instrument list are bare JSON arrays, stored as `{"items": […]}`.
  - **The instrument list** (every instrument Trading 212 offers, 1 per 50 s) is the one response stored trimmed: only the instruments that fetch's positions and orders name. It needs the key's **Metadata** permission; without it the sync goes on and types stay empty.
  - **Paging orders:** an order is dated by its fill, else (never filled) by its creation. A later sync stops after the first page reaching back past two weeks before the account's latest fill; with no fill stored yet (an account synced before T2), it reads every order. A limit order created long before it fills can sit deeper than that; T3's check against the summary would show it.
  - **Instruments** (`finance.instruments`): Trading 212's ticker (unique), ISIN, name, currency (its prices'; GBX is pence) and type. Every sync upserts the ones it meets; a value a response lacks never clears a stored one.
  - **Fills** (`finance.fills`): identity is the account and Trading 212's fill id. Side, fill type, order type, where the order came from (`AUTOINVEST`, `WEB`, …), when it filled, quantity and price (in the instrument's currency), and from its wallet impact the account's currency, FX rate, net value, realised result, and taxes as JSON `[{name, amount, currency, charged_at}]`, amounts as decimal strings. An order without a fill (cancelled, rejected, still working) is ignored; one without a side takes it from the quantity's sign. T3's rebuild needs the signs, *confirmed at the first live sync (2026-10-24):*
    - a buy's quantity comes positive and a sell's negative;
    - the net value is positive both ways: the cash the fill moved, fees included;
    - a sell carries the realised result;
    - taxes come negative (only currency conversion fees so far);
    - the FX rate is units of the instrument's currency per unit of the account's (USD per EUR, about 1.15), so the account's amount is quantity × price ÷ FX rate.
  - **The first live sync** (2026-10-24) reconciled exactly:
    - the summary's cash equals the cash movements, plus the sells' net values, less the buys', to the cent;
    - the fills' realised results add up to the summary's;
    - the instrument list worked, with an ISIN and a type for every instrument traded;
    - everything had been sold, so the snapshot is an empty anchor, and every instrument's fills net to zero (by side, on absolute quantities).
  - **Snapshots:** a sync's positions become one `finance.portfolio_snapshots` row, with the same sync's summary figures (cash available, in pies and reserved; the investments' value, cost, realised and unrealised result; the total value), and one `finance.holding_snapshots` row per position (quantity, in pies, average and current price, value, cost, unrealised result, FX impact, opened at). A sync from before T2, without positions, has none. The latest snapshot is the anchor, an empty one too (everything sold).
  - **Renormalize** deletes an account's fills and snapshots and rebuilds them from the stored payloads, as it does balances: nothing in the user layer points at them. Instruments are upserted again.
  - **API:** `GET /api/finance/investments?months=12` gives each listed investment account the principal may see: value, cash (available, in pies and reserved), cost and result from the latest snapshot (the summary's unrealised result, else the investments' value less cost), the realised result, the holdings (biggest first; weight is the share of the holdings' value, cash left out), and dividends and interest per month from the bank codes, in the account's currency. `insights/investments.py` loads the inputs and a pure `compute_investments` shapes them, for T4's MCP tool. The Investments page shows it, under Finance.
  - **Analytics:** no view changed. Fills aren't transactions, and the holdings views are T4's.

### The key and the sync

- **The key is a file,** `secrets/trading212/<name>`, holding the key and secret. Compose bind-mounts the folder, so the stack starts without it. A connection records the file's name, never the key. `cli t212-link` reads the file, checks it against the account summary, and creates the connection and account for a member. One file per Trading 212 account.
- **The key's permissions:** account data, history and portfolio only. No orders, no pies. *(T2)* Plus metadata, optional, for the instruments' types.
- **Syncing:** no PSD2 limit applies. The existing schedule and "Sync now" serve it.
  - The first sync pages through the whole history, which Trading 212 keeps from the account's opening.
  - Later syncs stop paging at two weeks before the latest item already stored.
  - The client honours the rate-limit headers and backs off on 429.
- *(As built in T1)* The details:
  - **The key file** holds two lines, `key=<API key>` and `secret=<API secret>`; blank lines and `#` comments are ignored. The folder is `HUBNISIO_TRADING212_KEYS_DIR` (default `../secrets/trading212`), mounted read-only at `/run/secrets/trading212` in the api and worker containers. The README says how to make the key.
  - **The connection:** provider `trading212`, `key_file` (the name only), no country (`institution_country` is now nullable) and no expiry.
  - **The account:** `is_investment` on and `include_in_net_worth` off, matched on `identification_hash = trading212:<account id>`. `cli t212-link --email … --key-file …` touches only that member's household. Linking again reuses the account and the member's connection to it, which takes the new file name and is active again.
  - **The balance:** the summary's `totalValue` is a snapshot of type `TVAL`. The cash stays in the stored summary payload, for T3.
  - **Payloads:** kinds `summary`, `transactions` and `dividends`, each stored before it's applied. A key that reads another account than the connection's fails the sync before anything is stored.
  - **Paging:** `limit=50`, following `nextPagePath`. A later sync stops after the first page holding an item dated before its cutoff: two weeks before the account's latest stored transaction, either kind.
  - **Errors** (the sync's `error_code`): 401 is `KEY_REJECTED` and expires the connection until it's linked again; 403 is `MISSING_PERMISSION`; an unreadable key file is `KEY_FILE`; a key for another account is `WRONG_ACCOUNT`.
  - **Rate limits:** when a response says an endpoint's allowance is used up, the next call to it waits for `x-ratelimit-reset`. A 429 waits for the reset too (at least 1, 2, then 4 seconds) and gives up after 4 tries as `RATE_LIMITED`; the sync is then retried in 15 minutes. A wait is never longer than 2 minutes.

### Value over time: rebuilt from trades

- **Quantities:** each holding's quantity on a day is the latest snapshot's, moved back by the fills since then, splits and other corporate actions included. So today's quantities are exact by construction.
- **Cash:** the summary's cash, moved back by the cash movements and the fills' net values.
- **Prices:** a global `instrument_prices` table, one row per instrument and day, with its source.
  - Each sync stores the positions' current prices (source `trading212`), and each fill's price is a price on its day (source `fill`).
  - The days between come from a daily price source, fetched by a daily task and a `cli prices-backfill`, like FX rates.
  - The source is chosen in slice T3 by checking which one covers every instrument held: keyless and official first, then a free tier with a key, then an unofficial endpoint. It's recorded here. An instrument can be given the source's symbol by hand when its ISIN doesn't map.
  - **Gaps:** a day uses the latest price on or before it, if at most 10 days old. Without one, the holding is left out of that day and counted, as FX does. There's never a fallback to cost.
  - **Currencies:** prices are in the instrument's currency and converted through `fx_rates`, which now also covers instrument currencies. Pence (`GBX`) is a hundredth of a pound.
- **Net worth:** the investment account's value on a day is its cash plus its holdings at that day's prices, in place of the bank anchor-and-move. `load_inputs` and the `analytics` views change together ([ADR-0006](0006-ai-access.md)). Until then, the account is created with `include_in_net_worth` off, so net worth isn't wrong in between.
- **The check:** the rebuilt value today must match the summary's total value. The difference is reported, never hidden.
- *(As built in T3)* The details:
  - **The price source is Yahoo Finance's chart endpoint** (keyless, unofficial), chosen on 2026-10-24 against the 19 instruments traded: 13 US stocks, and 6 UCITS ETFs in EUR (4 on Milan, 2 on Xetra).
    - Keyless and official: none publishes share prices. The ECB has only exchange rates, and Trading 212 no price history.
    - A free tier with a key: EODHD's gives a year of history, and the trades go back 13 months; Twelve Data's covers US markets only; Alpha Vantage's has no Milan. Stooq now sits behind a JavaScript check.
    - Yahoo had all 19, in their own currency, from before the first trade. It answers an HTTP library's default User-Agent with 429, so the client names itself.
  - **Symbols** are found once and kept on the instrument (`price_symbol`).
    - A European ticker's last letter names its exchange (`m` Milan, `d` Xetra, `l` London, `p` Paris, `a` Amsterdam), so `VOLTm_EQ` is `VOLT.MI`. Yahoo's ISIN search lists only the London and Stuttgart listings of those ETFs.
    - A US ticker goes through the ISIN first: Trading 212 keeps a ticker after a rename (4 of the 13, such as FB for META), and Yahoo's FB is now another instrument.
    - A candidate counts only if it's quoted in the instrument's currency, has its type, and its closes are within 0.8 to 1.25 times the broker's prices on the same days (the median).
    - `cli prices-symbol --ticker … --symbol …` sets one by hand; `--auto` forgets it. A symbol Yahoo drops is looked for again, unless set by hand.
  - **Closes are as traded:** Yahoo divides the days before a split by its ratio, and the hub multiplies them back, so a close fits its day's quantities, as a fill's price does.
  - **One price per instrument and day:** the day's close, else the latest sync's price for the position, else the latest fill's (trades only: a corporate action's price isn't one). The broker's prices are rebuilt from the stored fills and snapshots after each sync, by renormalize and by every refresh. After a sync they're stored in their own transaction, so a failure (a database without migration 0017, say) never fails the sync.
  - **The daily task** `fetch_prices` (16:45 UTC, after Xetra and Milan close) fetches each instrument's closes after its newest one, for the days it was held: from its first fill to its last, or to yesterday while held, since today's close isn't final. A failed instrument fails the job, which keeps what it fetched; one without a symbol is only logged. `cli prices-backfill` checks every day held.
  - **FX:** `fx_rates` covers the currencies of every instrument traded or held. Pence convert at the pound's rate times 100, in `RateTable`.
  - **The rebuild** (`insights/portfolio.py`) uses the side with the absolute values: `+|quantity|` for a buy and `−|quantity|` for a sell, corporate actions included; cash `−|net value|` for a buy and `+|net value|` for a sell, plus the booked transactions. The cash is the snapshot's available, in pies and reserved. A fill counts before or after the snapshot by its time; a cash movement by its day.
  - *Checked on live data (2026-10-24):* from the 58 fills and 411 days of cash movements, the rebuild ends at the snapshot exactly, with no cash and no quantity of any of the 19 instruments unexplained. So the signs above are right.
  - *Applied live (2026-10-24):* migration 0017, then `prices-backfill` (19 symbols found, 1,556 closes, none missing) and `fx-backfill` (512 USD rates). The check's difference is 0.00 (everything is sold, so the value is cash), and no holding-day in the 411 days since the first movement lacks a price or rate.
  - **Net worth:** an investment account with a snapshot counts at its rebuilt value; one without has no balance yet, and its `TVAL` balance is never used. Its whole history is known, so it never makes the series start later; with no bank account, the series starts at its first movement. `unpriced` counts the holding-days left out, in the API, the MCP tools and the overview's note.
  - **The check:** `check` in `GET /api/finance/investments`, shown as "Check against Trading 212" on the Investments page.
    - The rebuilt value on the latest sync's day against the summary's total value, with the holdings it left out.
    - What the history doesn't explain: the cash and shares the rebuild holds before the first movement, which should be none.
  - **Analytics** (migration 0017):
    - `accounts` gains `is_investment` at the end.
    - New views: `portfolios` and `holdings` (the latest snapshot's, of listed accounts), `fills` (hidden accounts too), and `instruments` and `instrument_prices`.
    - Those two show only what the member's visible accounts traded or held, so another member's private holdings never show by name.
    - `ai/views.py` loads them into the same `Portfolio` and `PriceTable`, and the `balances` and `net_worth_history` tools agree with the app (tests/test_ai.py). T4's views build on these.

### Returns

- **Breakdown:** over any period, the account's result splits into price movements (unrealised and realised), dividends, interest, and fees and taxes.
- **Money-weighted return** (XIRR) on the deposits and withdrawals: what your money earned, given when you put it in.
- **Time-weighted return** from the daily values, chain-linked across the deposits and withdrawals: how the investments did, regardless of timing.
- **Chart:** value against net deposits over time.
- Pure functions over loaded inputs, so the API and the MCP server compute the same figures.

### Not in M6

- Tax reports for IRS (Anexo J). Fills and dividends keep what they'd need (dates, prices, FX rates, taxes).
- Pies as groups, a Stocks ISA, the CSV exports, and placing orders.

## Plan: four slices

Each slice is one fresh session. It ends committed and pushed once its checks pass, then starts the next.

1. **T1. Provider and cash.**
   - Migration: the `trading212` provider, the investment-account flag, and the connection's key-file name.
   - Then:
     - the client (Basic auth, paging, rate limits);
     - `cli t212-link`;
     - the sync of the summary (as a balance snapshot) and of cash movements and dividends into transactions, raw payloads first;
     - the seeded Dividends category and the rules on bank codes.
   - Tests use synthetic fixtures. The account shows its value on the Accounts page, and deposits pair as transfers.
2. **T2. Trades and holdings.**
   - Instruments, fills and holding snapshots, synced and normalized.
   - An Investments page: the account's value, cash, cost and result; holdings with value, cost, result and weight; dividends and interest by month.
3. **T3. Prices and net worth over time.**
   - Pick and record the price source; `instrument_prices`, its daily task and backfill.
   - The rebuild of quantities and cash, and the investment account's value in net worth, with the `analytics` views changed to match.
   - The check against the summary.
4. **T4. Returns and AI.**
   - The breakdown, money- and time-weighted returns, and the value against net deposits chart on the Investments page.
   - `analytics` views for holdings, fills and investment values; an `investments` MCP tool, checked against the API.
   - This ADR and CLAUDE.md as built.

## Options Considered

### Value before the first sync

| Option | Pros | Cons |
|---|---|---|
| Rebuild from trades and daily prices (chosen) | Right on every day; no always-on machine needed; history as long as the account's | A price source to pick, map and keep; a slice of its own |
| Cost until the first sync, market value after | Simple | A jump on the first day; the past understates or overstates |
| Daily snapshots only | Exact on snapshot days | History starts at linking; days the PC is off are gaps that can't be filled later |

### Where the key lives

| Option | Pros | Cons |
|---|---|---|
| A file in `secrets/` (chosen) | Like the Enable Banking key; the key never enters the database | One file per account to manage by hand; a member links theirs with the CLI |
| Pasted in the app, stored encrypted | Each member links their own in the UI | Key handling in the UI, and in the database even if encrypted |

### Trades in the ledger

| Option | Pros | Cons |
|---|---|---|
| Fills apart; only cash movements are transactions (chosen) | Spending and income stay about money in and out; buys don't need excluding everywhere | Value over time needs its own rebuild |
| Every trade as a transaction | One ledger | Every report must skip buys and sells; the account's "balance" would mean cash only |

## Consequences

- **Easier:** money moved to the broker stops counting as spending; net worth includes investments at market value; returns use the same daily values as net worth.
- **Harder:** a third-party price source to keep working; corporate actions the order history doesn't show would break the rebuild. The check against the summary catches that.
- **Revisit:**
  - the price source, if it stops working or misses an instrument;
  - Anexo J, once the user wants it (IRS ideas in CLAUDE.md).

## Action Items

1. [x] The user creates a read-only API key (account data, history, portfolio, metadata) in the Trading 212 app. If their public IP is stable, they restrict the key to it. They save the key at `secrets/trading212/<name>` in the format T1 documents (README, "Linking Trading 212").
2. [x] Approve the live-data writes in the session that does them (approved standing on 2026-10-24, and done that day): the first link and sync, and the Dividends category and bank-code rules in the existing household (seeding covers only new ones).
3. [ ] After T3: switch on "Include in net worth" for the Trading 212 account.
