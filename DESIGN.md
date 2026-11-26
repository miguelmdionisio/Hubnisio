---
name: Hubnisio
description: A private personal hub, finance first. Calm, dark by default, numbers before words.
colors:
  ink-dark: "#eef0f4"
  ground-dark: "#0d0e13"
  soft-dark: "#181a21"
  soft-2-dark: "#23262f"
  seam-dark: "#22242c"
  mute-dark: "#9aa0ab"
  faint-dark: "#8a909a"
  nav-dark: "#0a0b0f"
  nav-on-dark: "#1d2029"
  pop-dark: "#1b1d25"
  finance-blue-dark: "#6b8cff"
  finance-blue-soft-dark: "#1c2440"
  health-orange-dark: "#ff9f5a"
  health-orange-soft-dark: "#3a2414"
  good-dark: "#4cc283"
  bad-dark: "#f2675d"
  ink-light: "#1d2129"
  ground-light: "#ffffff"
  soft-light: "#f3f4f7"
  soft-2-light: "#e7e9ef"
  seam-light: "#e8eaee"
  mute-light: "#646b77"
  faint-light: "#737a85"
  nav-light: "#f6f7f9"
  nav-on-light: "#e4e8f0"
  finance-blue-light: "#2766cf"
  finance-blue-soft-light: "#e6eefb"
  health-orange-light: "#b04e08"
  health-orange-soft-light: "#fdeee3"
  sport-swim: "#4fb3ff"
  sport-bike: "#b38cff"
  sport-run: "#ffd166"
  sport-strength: "#8a909a"
  sleep-deep: "#4e5bd6"
  sleep-light: "#8fa3ff"
  sleep-rem: "#c58cff"
  sleep-awake: "#8ee6cf"
  zone-1: "oklch(0.82 0.07 230)"
  zone-2: "oklch(0.74 0.11 250)"
  zone-3: "oklch(0.66 0.15 275)"
  zone-4: "oklch(0.6 0.19 305)"
  zone-5: "oklch(0.56 0.21 340)"
  good-light: "#187a50"
  bad-light: "#cf3f36"
typography:
  page-title-phone:
    fontFamily: "Figtree Variable, system-ui, sans-serif"
    fontSize: "24px"
    fontWeight: 700
    letterSpacing: "-0.02em"
  page-title:
    fontFamily: "Figtree Variable, system-ui, sans-serif"
    fontSize: "18px"
    fontWeight: 700
  body:
    fontFamily: "Figtree Variable, system-ui, sans-serif"
    fontSize: "14px"
    fontWeight: 400
    lineHeight: 1.45
  nav:
    fontFamily: "Figtree Variable, system-ui, sans-serif"
    fontSize: "13.5px"
    fontWeight: 400
  group-label:
    fontFamily: "Figtree Variable, system-ui, sans-serif"
    fontSize: "11.5px"
    fontWeight: 600
  tab-label:
    fontFamily: "Figtree Variable, system-ui, sans-serif"
    fontSize: "10.5px"
    fontWeight: 500
rounded:
  control: "12px"
  nav-item: "8px"
  row: "14px"
  panel: "18px"
  pill: "9999px"
spacing:
  page-x-phone: "16px"
  page-x: "28px"
  header-height: "58px"
  sidebar-width: "200px"
components:
  nav-item:
    textColor: "{colors.mute-dark}"
    rounded: "{rounded.nav-item}"
    padding: "7px 9px"
  nav-item-active:
    backgroundColor: "{colors.nav-on-dark}"
    textColor: "{colors.ink-dark}"
    rounded: "{rounded.nav-item}"
  segmented:
    backgroundColor: "{colors.soft-dark}"
    rounded: "{rounded.pill}"
    padding: "3px"
  segmented-on:
    backgroundColor: "{colors.soft-2-dark}"
    textColor: "{colors.ink-dark}"
    rounded: "{rounded.pill}"
    height: "28px"
  list-panel:
    backgroundColor: "{colors.soft-dark}"
    rounded: "{rounded.panel}"
    padding: "6px"
  list-row:
    rounded: "{rounded.row}"
    padding: "10px 12px"
  tab-bar-tab:
    textColor: "{colors.faint-dark}"
  tab-bar-tab-active:
    textColor: "{colors.finance-blue-dark}"
---

# Design System: Hubnisio

## Overview

**Creative North Star: "Calm"**

A quiet instrument for one household's money, opened for a few seconds on a phone or for a sit-down weekly review on a laptop. Dark by default, near-black ground, one accent per domain (Finance blue, Health orange), and type that does the work: big numbers, short labels, no explanatory sentences. Surfaces are told apart by tone (ground, soft, soft-2), not by lines or shadows.

The look was chosen on 2026-10-29 from the round-two looks (`.impeccable/mocks/looks-b1-v2.html`) and the M7 prototype (`.impeccable/mocks/prototype.html`); its references are Revolut's analytics screens, Linear and Things. Rejected earlier: a top bar, a command-first layout, a two-column domain rail, and the Conserveira, Euro Series, Graphite Console and Envelopes looks.

Since M7 (done 2026-10-29) the whole finance app is in this system: the shell, the Spending page and its drill-downs, the transaction sheet, the Overview, and every other page.

**Key Characteristics:**
- Dark first; light and system offered, remembered per browser.
- Tonal layering instead of borders and shadows.
- Pills and segmented controls, fully rounded.
- One accent per domain (Finance: blue, Health: orange), plus good and bad; nothing else is coloured except charts.
- Copy is numbers and short labels.

## Colors

Cool, near-neutral greys with a faint blue cast, one domain accent, and two semantic colours. Light and dark are the same roles; the frontmatter holds both.

### Primary
- **Finance Blue** (dark `finance-blue-dark`, light `finance-blue-light`): the Finance domain's accent. The domain mark, the active sidebar icon, the active tab, focus rings, selection, primary buttons. As `primary` in Tailwind. The light blue is 5.4:1 on white and 4.6:1 on its soft fill, so the tab bar's 10.5px labels and a selected pill's text pass.
- **Finance Blue, soft** (`finance-blue-soft-*`): a selected pill's fill, with Finance Blue text (`primary-soft`).
- **Health Orange** (dark `health-orange-dark`, light `health-orange-light`) and its soft fill (`health-orange-soft-*`): the Health domain's accent, in the same roles. The light orange is a deep burnt orange: 5.1:1 on white, 4.5:1 on its soft fill, 4.7:1 on soft, and white text on it passes too. Dark orange has 9.5:1 on the ground and the ground's colour as its text.
- **Following the domain:** `primary`, `primary-soft`, `ring` and the sidebar's primary are not fixed. The shell sets `data-domain` on `<html>` from the route (`finance`, `health`), and `index.css` redefines those tokens per domain and theme (`:root[data-domain="health"]`, `.dark[data-domain="health"]`). Every component that uses the tokens takes the current domain's accent; Finance is the default. It lives on `<html>` so menus, the command menu and toasts, which render outside the shell, follow too.

### Sport and sleep-stage colours
Chart-only hues for Health, the same in both themes like the `--cat-*` hues (`--sport-*`, `--sleep-*`). Sports: swim `sport-swim`, bike `sport-bike`, run `sport-run`, strength `sport-strength`. Sleep stages: deep `sleep-deep` (darkest), light `sleep-light`, REM `sleep-rem`, and awake `sleep-awake`, a pale mint. Awake is deliberately not orange (the accent marks the domain, never data) and is told apart from the blues and purples by hue and by being the lightest of the four. Chart marks carry a label or screen-reader list too, never colour alone.

### Heart-rate zones
One sequential ramp, `--zone-1` to `--zone-5` (`zone-*` above), the same in both themes: pale sky through blue and indigo to magenta, darker as the effort rises. Every place that draws zones uses it: an activity's zone bars, and Training's intensity bars (Z1–2 `zone-2`, Z3 `zone-3`, Z4–5 `zone-5`). It avoids good and bad, because hard work is not a verdict, and the accent.

### Series that are not verdicts
Heart rate, HRV and cadence lines (an activity's lanes, the overnight chart) are drawn in ink, mute or faint, or in the sport's colour, never in good or bad: an ordinary heart rate is not an alarm. SpO2 is swim blue, apart from the sleep stages' violets. Form is a line in ink over its bands on both Today and Training (`FormChart`); the bands carry the meaning. Body Battery is charged in ink, drained in faint.

### Neutral
- **Ground** (`ground-*`): the page (`background`, `card`).
- **Soft** (`soft-*`): the first raised tone: list panels, segmented tracks, muted fills (`surface`, `muted`).
- **Soft 2** (`soft-2-*`): the second tone: the selected segment, hover on soft, row chips (`surface-2`).
- **Nav** and **Nav on** (`nav-*`, `nav-on-*`): the sidebar and its current page (`sidebar`, `sidebar-accent`).
- **Ink** (`ink-*`): text and figures (`foreground`).
- **Mute** (`mute-*`): secondary text, sidebar items at rest (`muted-foreground`).
- **Faint** (`faint-*`): group labels, chevrons, idle tabs (`faint`). Still ≥4.5:1 on its ground.
- **Seam** (`seam-*`): the one hairline: under the desktop header, beside the sidebar, above the tab bar (`border`).
- **Pop** (`pop-dark`): menus and popovers in dark (`popover`).

### Semantic
- **Good** (`good-*`): fresh sync dot, money in, under budget (`good`). The light green is 5.3:1 on white and 4.85:1 on soft, so it holds as text on both.
- **Bad** (`bad-*`): a connection needing a look, over budget, errors (`destructive`).

**The Verdict Colour Rule.** Good and bad mark verdicts only: a sync fresh or needing a look, a signal OK or not, a value in its range or below it, an improvement or a drop. They never colour a data series, a zone or a level of effort. HRV above its normal range is no problem and reads neutral; below it is the warning.

### Named Rules
**The One Accent Rule.** A domain owns one accent. It marks where you are and what you can act on; it never decorates. Semantic good/bad stay separate from it.

**The Tone Not Line Rule.** Separate surfaces by stepping ground → soft → soft-2. A seam line is used only at the shell's edges.

## Typography

**Body Font:** Figtree Variable (with system-ui, sans-serif), self-hosted from `@fontsource-variable/figtree`.

**Character:** A friendly geometric grotesk that stays crisp at 10.5px tab labels and carries bold 24–42px figures without shouting.

### Hierarchy
- **Page title, phone** (700, 24px, −0.02em): the large title at the top of each page below 768px.
- **Page title** (700, 18px): in the desktop header bar.
- **Body** (400, 14px, 1.45): page text. Longer lines stop at 70ch.
- **Nav** (400, 13.5px; 600 when current): sidebar items.
- **Group label** (600, 11.5px, faint): Organise, Sources. Sentence case, never uppercase.
- **Tab label** (500, 10.5px): under the tab bar's icons.
- Figures use tabular numerals (`tabular-nums`).

### Named Rules
**The No Sentences Rule.** Numbers and short labels. If a screen needs a paragraph to explain itself, the screen is wrong. Honest gaps get a short marker, not prose.

## Layout

- **Desktop (≥768px):** a 200px sidebar, sticky full height, then the content. Each page starts with a sticky 58px header bar across the content (title left; Finance's sync freshness, Mine / Household and the page's actions right) with a seam below and the ground at 88% behind a blur. Content gutters are 28px.
- **Phone (<768px):** no sidebar. The page title is large (24px) at the top; Mine / Household sits right of it and actions wrap below. Gutters are 16px. A fixed tab bar at the bottom holds the domain's main pages plus More, respecting `env(safe-area-inset-bottom)`; content keeps 96px of room below it.
- **More** lists the domains first (the phone's domain switcher: the current one ticked), then the pages the tab bar leaves out, in the sidebar's groups, plus Search and Theme, as soft panels of rows (max 576px wide).
- Navigation is data per domain (`frontend/src/components/domains.ts`): name, mark, groups, tabs.

## Elevation & Depth

Flat. Depth is tonal (ground → soft → soft-2). The only shadow is on floating things: menus, popovers and dialogs.

### Shadow Vocabulary
- **Pop** (`--pop-shadow`; dark `0 16px 40px rgb(0 0 0 / 60%), 0 0 0 1px #2a2d37`, light `0 12px 32px rgb(20 30 50 / 16%), 0 0 0 1px rgb(20 30 50 / 6%)`): menus, popovers, the skip link.

### Named Rules
**The Flat At Rest Rule.** Nothing on the page casts a shadow; only what floats above it does.

## Shapes

Soft and round. Controls are fully rounded pills (9999px); list panels 18px; rows 14px; sidebar items 8px; shadcn's base radius is 12px. Icons are lucide at 16px (sidebar, rows) and 22px (tab bar), stroke as drawn, muted until active. Row chips are 34–40px circles.

## Components

### Navigation
- **Sidebar:** the domain switcher on top (a 22px round mark in the domain accent, the domain's name, a chevron; opens a menu of built domains: Finance and Health), then the pages in groups. Items are mute at rest, ink on hover; the current one has the nav-on fill, semibold ink text and an accent icon. Footer: the theme switch and Search with its `Ctrl K` hint.
- **Tab bar:** icons over labels, faint at rest, the accent when current. More is current on any page not in the tabs.

### Segmented control
- **Style:** a soft pill track (3px inset) of 28px buttons; the chosen one is soft-2 with semibold ink. Text segments for Mine / Household, 32px icon segments (moon, sun, monitor) for the theme. Each button reports `aria-pressed`.

### Page header
- **Content:** title; on desktop, on Finance pages, the sync freshness ("Synced 21 minutes ago" with a good dot; a dashed ring when stale; "BPI needs a look" in bad, linking to Bank connections); Mine / Household on pages that sum money; the page's actions.
- **Health's freshness:** on every Health page, at every width, from `GET /api/health/connection` (`components/health-freshness.tsx`): "Garmin synced 3 hours ago" with a good dot; a dashed ring when the last successful sync is over 26 hours old (the daily task plus two hours' slack); "Garmin syncing" while one runs; "Garmin needs a look" in bad, linking to the Garmin page, when nothing is linked, the last sync failed, or the key lapses within 14 days or has lapsed.

### List panels and rows
- **Style:** soft panel, 18px radius, 6px inset; rows of chip, label and a trailing chevron or control, 14px radius, soft-2 on hover.

### Pills (`components/pills.tsx`)
- **Style:** 34px (36px on desktop) soft pills, semibold 13.5–14px, a 16px icon first. A pill that narrows what's shown (`on`) takes primary-soft with primary text. `MenuPill` opens a short ticked menu; `MonthStepper` is "‹ This month ›" and never steps past the current month. shadcn buttons are pills too.

### Chips (`components/category-chip.tsx`)
- **Style:** round, 34/40/56px, a white lucide icon on the category's hue (`--cat-*`, the same in both themes), or a letter: a merchant's initial on its category's hue, else on soft-2. Seeded categories map to icons by name; others take their group's, then a hue from the name. Uncategorized is grey with a dashed circle.

### Figures and charts
- **Total:** 36px (42px desktop) at 750 weight, one line under it: an average, or "▲/▼ €213 vs September so far" in bad/good. A partial month gets a "Partial" marker, never a sentence.
- **Charts (Recharts):** no gridlines; dashed faint reference lines at the highest day and the average, labelled on the right; bars in ink (a category's hue on its page); the running total in the accent over last month's dashed faint line; the donut's four biggest plus Others, the total and change in its middle. Every chart has a screen-reader list of its values.

### Transaction sheet
- **Style:** a 400px side panel on desktop, a bottom sheet (22px top radius, 88dvh) on the phone: chip, merchant and amount centred; a soft facts panel (date, account, who set the category); a two-column grid of categories by group that sets one in a click; then the rest.

### Search
- **Style:** the command menu (Ctrl K / ⌘K, or Search in the sidebar or More): every page of every domain, and the three themes.

## Do's and Don'ts

### Do:
- **Do** use the shadcn tokens (`background`, `muted`, `surface`, `surface-2`, `primary`, `primary-soft`, `faint`, `good`, `destructive`) rather than raw colours.
- **Do** keep copy to figures and short labels; put notes in a `title` tooltip if they must exist.
- **Do** design every page for 375px and desktop together.
- **Do** add a domain by adding an entry to `domains.ts` and an accent block in `index.css` keyed on its `data-domain`.

### Don't:
- **Don't** add explanatory sentences under titles.
- **Don't** separate surfaces with borders or shadows; step the tone instead.
- **Don't** use the accent for decoration, or a second accent within a domain.
- **Don't** uppercase labels.
