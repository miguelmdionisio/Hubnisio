# Navigation (B1)

Chosen by the user on 2026-10-28 from the sketches in `.impeccable/mocks/` (`navigation.html`, `navigation-b.html`, option B1). Built in M7 F1 (`frontend/src/components/app-shell.tsx`, config in `components/domains.ts`). Not built yet:
- the icon-only sidebar below 1024px (the 200px sidebar holds down to 768px);
- the domain switcher in the phone's page header, which waits for a second domain.

Spending joined the sidebar (after Overview) and the tab bar (Overview, Spending, Transactions, Budgets, More) with its page in F3.

## Why it looks like this

- Hubnisio is a hub of domains. Finance is the only one today; sport and others will follow, each with its own pages (PRODUCT.md, "Capabilities and Constraints").
- Desktop and iPhone both count. The navigation is designed for both from the start.
- The user rejected a top bar, a command-first layout and a two-column domain rail plus sidebar (too much chrome, too generic). B1 keeps one column.

## Desktop and tablet

One sidebar column, about 184–200px wide, light and quiet (no coloured field).

1. **Domain switcher** at the top: the domain's mark (a small square in the domain's accent colour, "€" for Finance), its name, and a chevron. Clicking it opens a menu of domains; domains not built yet don't appear. Switching domain swaps the list below and goes to that domain's first page.
2. **The domain's pages**, in groups. Finance:
   - (no heading) Overview, Transactions, Budgets, Recurring, Investments
   - **Organise:** Categories, Merchants, Rules
   - **Sources:** Accounts, Bank connections
3. **Footer:** "Search" with the `Ctrl K` hint (the command menu, cross-domain later). The API health line in today's footer goes away; sync freshness moves into the pages (see below).

The current page has a subtle filled background plus the domain's accent on its icon. Icons stay (lucide, as today), 14–16px, muted until active.

Below about 1024px wide the sidebar collapses to icons only (about 56px) with names as tooltips; the domain switcher becomes just its mark. (Not sketched; a reasonable default to confirm.)

Each domain owns one accent colour. It marks the domain switcher, the active nav item, the iPhone tab bar's active tab and the domain's primary emphasis. Semantic colours (good, warning, over budget) are separate from it.

## Page header (every page)

A slim bar at the top of the content: page title, the period or context (e.g. "October 2026"), and on the right the page's own controls. Finance pages that sum money put the **Mine / Household** segmented control here, as today. No breadcrumbs: the sidebar already says where you are.

Overview shows sync freshness per provider (BPI, Revolut, Trading 212) as a status, with a dashed ring for anything stale.

## iPhone (below about 768px)

- **No sidebar.** A large title at the top of each page, with the period on the left above it and the **domain switcher** ("€ Finance ⌄") on the right. Tapping it opens a bottom sheet listing domains.
- **Bottom tab bar** with four tabs for the open domain: three main pages plus **More**. Finance: Overview, Transactions, Budgets, More. The active tab is drawn in the domain's accent.
- **More** is a page (or sheet) listing the rest of the domain's pages in the same groups as the sidebar, plus search.
- The tab bar respects the iPhone safe area (`env(safe-area-inset-bottom)`). Mine / Household stays in each page's header, wrapping under the title when narrow.

## Routing

URLs keep their domain prefix: `/finance/transactions`, later `/sport/...`. `/` is currently the finance Overview (`routes/home.tsx`); with more domains it can become `/finance` and `/` can redirect to the last domain used. That move is a separate decision.

Navigation config should be data per domain (name, mark, accent, groups of `{ label, to, icon }`, which three pages go in the tab bar), so a new domain adds a config entry rather than new shell code.

## Still open

- **Visual look:** not chosen. The latest options are in `.impeccable/mocks/looks-b1-v2.html` (Precision, Calm, Instrument), drawn on B1 in light and dark. The user's references are Linear and Things; they want it sharp and technical. Earlier looks (Conserveira, Euro Series, Graphite Console, Envelopes) were rejected.
- After the look: tokens in `frontend/src/index.css`, the shadcn components rethemed, the shell rebuilt to this spec, and DESIGN.md written (impeccable skill, `/impeccable`).
