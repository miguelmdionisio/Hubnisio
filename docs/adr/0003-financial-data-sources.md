# ADR-0003: Financial data sources

**Status:** Accepted
**Date:** 2026-10-22
**Deciders:** Miguel Dionísio

## Context

Accounts to integrate:

- **BPI** and **Novo Banco** (Portuguese banks)
- **Revolut:** a Lithuanian personal account and a Portuguese joint account
- **Trading 212** (broker)

Constraints and findings:

- The EU's open-banking rules (PSD2) cover payment accounts, not brokerage positions. The unattended-access limits below come from these rules.
- GoCardless Bank Account Data (formerly Nordigen), the former free default, stopped accepting new signups in July 2025.
- Enable Banking offers a free restricted mode for accessing your own accounts. Its Portugal documentation lists BPI and Novo Banco.
- Firefly III (with its data importer, which supports Enable Banking) was considered as the finance backend.

## Decision

1. **Bank accounts come from the Enable Banking API directly, in restricted mode.**
   - **Auth:** an application ID plus a private key. Every API call carries an RS256 JWT signed with that key.
   - **Linking:** start authorization for a bank → the user approves in the bank's app → the bank redirects back with a code → create a session → list accounts. The redirect only needs to reach the user's browser, so a private-network URL works.
   - **Consent expiry:** consent lasts up to the bank's maximum (often 180 days). Store the expiry, notify about 14 days before it, and keep account identity stable across re-linking.
   - **Sync limits:** at most 4 unattended fetches per account per day, as PSD2 allows. Extra fetches only when the user triggers a sync. Honor rate-limit responses.
2. **Trading 212 comes from its official API** (beta; Invest and Stocks ISA accounts).
   - Use an API key with read-only scopes only, IP-restricted to the server where possible.
   - Investments get their own model (holdings, orders/trades, dividends, cash movements), not just transactions.
3. **One provider interface for every source.**
   - Operations: `connect`, `list_accounts`, `fetch(since=cursor)`.
   - Every raw provider response is stored append-only (`finance.provider_payloads`), then normalized into domain tables.
   - Normalization can be re-run from the raw data, so parser fixes never need a re-fetch.
4. **Firefly III and other open-source apps are reference material, not dependencies.**
   - We study how they handle recurring transactions, budgets, rules and deduplication, then reimplement in Python.
   - No line-by-line translation of AGPL/GPL code (Firefly III is AGPL-3.0).
   - Findings: [docs/research/oss-finance-analysis.md](../research/oss-finance-analysis.md).
5. **No historical backfill from CSV exports.** History starts with whatever each provider returns on the first sync. A CSV provider can be added later without changing this design.

## Options Considered

### Option A: Firefly III + data importer as the finance backend

| Dimension | Assessment |
|-----------|------------|
| Complexity | Low to start; high integration cost later (two apps, two data models, sync between them) |
| Cost | Free, but a PHP/Laravel app plus the importer to run and update |
| Scalability | Fine |
| Familiarity | New codebase in a different language |

**Pros:** budgets, rules, recurring transactions and reports on day one.
**Cons:** the hub becomes a client of someone else's data model; cross-domain features go through its API; two sources of truth.

### Option B: Enable Banking directly + our own finance core (chosen)

| Dimension | Assessment |
|-----------|------------|
| Complexity | Medium: small API surface; the work is in our own domain logic |
| Cost | Free (restricted mode, personal use) |
| Scalability | Fine |
| Familiarity | Our own Python code |

**Pros:** full control of the data model; one source of truth; cross-domain and AI features work on our own schema.
**Cons:** we build deduplication, transfer detection, categorization, budgets and reports ourselves.

### Option C: Another aggregator

**Cons:** GoCardless is closed to new signups; Tink and TrueLayer are aimed at businesses, with contracts to match. Nothing here beats Enable Banking's free personal tier.

## Trade-off Analysis

A buys features immediately and charges for it forever in integration and constrained modeling. B costs more up front, but the hard parts (dedup, recurring detection, budgets) are well documented by the open-source projects we're studying, and owning the model is what makes cross-domain and AI features possible.

## Consequences

- **Easier:** the data model fits our goals; a provider change stays inside its provider package.
- **Harder:** dedup and pending→booked matching are ours to get right. They're the riskiest part of the finance module.
- **Revisit:** the finance domain model ADR once the research report is in.

## Action Items

1. [ ] Register an Enable Banking application and generate the key pair; store the private key outside the repo ([ADR-0004](0004-hosting-and-security.md)).
2. [ ] Confirm Revolut (LT personal and PT joint) appear in Enable Banking's bank list, and that the joint account is returned after linking.
3. [ ] Check whether Enable Banking's restricted-mode terms allow a household member to link her own accounts under the same application.
4. [ ] Check whether Trading 212's API covers cash-account and card transactions or only investment-account movements.
5. [ ] Write the finance domain model ADR from the research report.
