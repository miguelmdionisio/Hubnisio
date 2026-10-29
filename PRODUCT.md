# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

One person running their own money, in a household of two. The partner is a member of the household but doesn't use the hub yet; they may log in later.

The user opens the hub in two ways:

- **Quick daily glance:** balances, bills coming up, whether a budget is slipping. Seconds, not minutes.
- **Weekly review:** sitting down to categorize, approve AI category suggestions, fix merchants and rules, and check budgets and where the money went.

Many questions also go to Claude through the hub's MCP server ([ADR-0006](docs/adr/0006-ai-access.md)); the app is where data gets confirmed and corrected.

## Product Purpose

Hubnisio is a private, self-hosted personal hub with one app per domain. Finance is the first and only domain so far; fitness and others come later, each meant to be as complete as a standalone app.

Finance gives a full picture of the household's money: every bank account and the broker in one place, categorized, budgeted, with recurring payments, cash flow, net worth and investments. Success is the user trusting the numbers enough to stop opening the banks' own apps to check.

## Positioning

What BPI's, Revolut's and Trading 212's own apps can't do:

- **One true picture.** All accounts, the joint pot and investments together, converted to EUR, reconciled to the cent against what the providers report.
- **Under the user's control.** Self-hosted and private; their categories, rules and decisions, no vendor deciding what they see.
- **Explains, not just shows.** Detected recurring payments, patterns, and AI answers about why the numbers moved.

## Operating Context

- Data arrives from Enable Banking (BPI, Revolut) and the Trading 212 API on a schedule; the user never types in transactions. Bank facts are read-only; everything the user decides (categories, merchants, notes, tags, transfers) is a layer on top. See [ADR-0007](docs/adr/0007-finance-domain-model.md).
- Banks send little: BPI about 90 days with no counterparties, neither bank sends pending transactions or merchant category codes. Gaps in the data are normal and the UI must not pretend otherwise.
- AI suggestions are proposals the user approves; they never override a manual choice or a rule.
- Runs locally for now (Docker Compose); a self-hosted always-on server comes later.

## Capabilities and Constraints

- Pages today: overview (spending, donut, cash flow, net worth, budgets, upcoming), Transactions, Categories, Merchants, Rules, Budgets, Recurring, Accounts, Bank connections, Investments.
- **Mine / Household view:** "Mine" (default) counts what the user moves into shared pots; "Household" counts everything. Another member's private accounts never show, not even by name.
- Money is multi-currency (EUR, MAD, instruments in other currencies), shown in EUR.
- Desktop and mobile web both count: the user is on iPhone, and quick glances and alerts will happen there. Every page and the navigation are designed for both. No native app planned.
- More domains will join finance (sport and others), each with its own pages; navigation and the design system must hold several domains.
- English UI, one locale: `en-GB` formatting (`frontend/src/lib/format.ts`).
- Real bank data: demos, screenshots and fixtures use made-up figures, never the user's own.

## Evidence on Hand

- Live data: about 1,650 transactions across BPI and Revolut, plus a Trading 212 portfolio of 19 instruments. Private; not for showing.
- Test fixtures in `frontend/src/test/fixtures.ts` and `backend/tests/households.py` are the safe source of sample content.
- No logo or brand assets exist. The name is Hubnisio.

## Product Principles

1. **The numbers are right or they say why not.** Reconciled totals, honest gaps, no silent estimates.
2. **Glance first, then dig.** The daily answer fits on one screen; the weekly work is a click away.
3. **The user decides.** Rules and AI propose; manual choices win and are easy to make in bulk.
4. **Private by construction.** Nothing leaves the user's machine that they didn't choose to send; another member's private accounts are invisible.
5. **One hub, many domains.** Finance patterns should stretch to the domains that come after it.
