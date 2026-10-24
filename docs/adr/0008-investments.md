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

### Trades, instruments and holdings

- **Instruments:** global, like `fx_rates` (public data): Trading 212's ticker, ISIN, name, currency and type.
- **Fills:** bank facts, written only by the sync, one row per order fill: instrument, side, fill type, quantity, price, FX rate, net value, realised result, and taxes and fees. Identity is Trading 212's fill id.
- **Holding snapshots:** what `positions` returns on each sync. The latest is the anchor for quantities, as a bank balance is for cash.
- **Raw first:** every response goes to `provider_payloads` before it's applied, and normalization can be re-run from it ([ADR-0003](0003-financial-data-sources.md)).

### The key and the sync

- **The key is a file,** `secrets/trading212/<name>`, holding the key and secret. Compose bind-mounts the folder, so the stack starts without it. A connection records the file's name, never the key. `cli t212-link` reads the file, checks it against the account summary, and creates the connection and account for a member. One file per Trading 212 account.
- **The key's permissions:** account data, history and portfolio only. No orders, no pies.
- **Syncing:** no PSD2 limit applies. The existing schedule and "Sync now" serve it.
  - The first sync pages through the whole history, which Trading 212 keeps from the account's opening.
  - Later syncs stop paging at two weeks before the latest item already stored.
  - The client honours the rate-limit headers and backs off on 429.

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

1. [ ] The user creates a read-only API key (account data, history, portfolio) in the Trading 212 app. If their public IP is stable, they restrict the key to it. They save the key at `secrets/trading212/<name>` in the format T1 documents.
2. [ ] Approve the live-data writes in the session that does them: the first link and sync, and the Dividends category and bank-code rules in the existing household (seeding covers only new ones).
3. [ ] After T3: switch on "Include in net worth" for the Trading 212 account.
