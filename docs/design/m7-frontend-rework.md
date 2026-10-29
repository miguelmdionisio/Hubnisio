# M7: frontend rework (plan)

Agreed with the user on 2026-10-29 from the prototype at `.impeccable/mocks/prototype.html` (published privately as a claude.ai artifact). The prototype is the reference for layout and behaviour; its figures are made up.

## What changes

- **Look:** "Calm" from the round-two looks (`.impeccable/mocks/looks-b1-v2.html`), dark by default, Figtree. Light, dark and system are offered. Few words on screen: numbers, short labels, no explanatory sentences.
- **Navigation:** B1 ([navigation.md](navigation.md)): one sidebar on desktop, a bottom tab bar on iPhone (Overview, Spending, Transactions, Budgets, More).
- **Spending page (new),** modelled on Revolut's "Spent" screen:
  - pill controls: account filter, "‹ This month ›", group by Category or Merchant; chart switch on the right;
  - three charts: bars per day (with the highest day and the daily average as dashed lines), running total against last month, donut;
  - a big total with one line under it ("€44 avg. per day", or "▼ €213 vs September so far");
  - a ranked list (icon, name, transactions, amount, share), top six then "See all";
  - clicking a bar shows that day; clicking a row or a donut slice opens the category or merchant page (same layout, plus budget bar, merchants and transactions).
- **Transaction sheet:** opens from any payment; category change in one click.
- **Overview, shorter:** four linked figures (spent, left to spend, due in 7 days, net worth), budgets with a pace tick, coming up, spent per day.

Hubnisio's own rules stay: Mine / Household in the page header, scoping, honest gaps (an incomplete month says so with a short marker, not a paragraph), `en-GB`.

## Slices

Each slice is one fresh session, committed and pushed to `main` once its checks pass; the session starts the next.

1. **F1 Foundation.** Tokens (light and dark), Figtree via `@fontsource-variable/figtree` (pinned, ≥14 days old), theme switch, the B1 sidebar and iPhone tab bar, the page header (title, sync freshness, Mine / Household). Existing pages keep working inside the new shell. `DESIGN.md` written from what ships.
2. **F2 Spending API.** `GET /api/finance/insights/spending/month`: for one month, view and optional account, category or merchant: spending per day, per category and per merchant (amount and count), and the month before per day. Same rules as `monthly_sums` (kinds, transfers, refunds, EUR on the day, scoping), as a pure function the MCP server could call later. Tests against `home`; client regenerated.
3. **F3 Spending page.** Controls, the three charts (Recharts), the ranked list, day selection, category and merchant pages. Route `/finance/spending`.
4. **F4 Transactions.** The new transaction sheet; the Transactions page grouped by day with search and a category filter, keeping the Review tab and bulk actions.
5. **F5 Overview.** The shorter overview; the old spending, donut and cash-flow cards go.
6. **F6 The other pages.** Budgets, Recurring, Investments, Categories, Merchants, Rules, Accounts and Bank connections moved to the new tokens and components; a critique pass over all of them.

## Decided (2026-10-29)

- Cash flow and the net worth chart leave the overview. Net worth's chart moves to Accounts (F6); cash flow returns later as an "Income" view of the Spending page, not in M7.
- Charts stay on Recharts (already a dependency), styled to the prototype.
