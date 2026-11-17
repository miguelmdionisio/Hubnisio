# M9: The hub on the iPhone (plan)

Drafted with the user on 2026-11-17. Approved by the user on 2026-11-17.

Make Hubnisio usable from the user's iPhone as an installed web app that feels native: opened from a home-screen icon, full screen, touch-first, with no App Store and no paid Apple account. If after a few weeks native features (widgets, haptics, badges) are still missed, a Capacitor wrapper under a shared developer account is the next step, not part of this milestone.

## Constraints

- **No always-on machine** (M5 stays deferred). The phone reaches the hub through Tailscale only while the PC and Compose stack run. Nothing in this milestone needs the server; it all carries over when M5 lands.
- **Login is still the dev user** (`core/auth.py`). Anyone who can open the site is the user, so the tailnet must hold only the user's own devices. No public exposure (no Tailscale Funnel), and no partner on the tailnet until passkey login (M5).
- **Real data on the phone:** pages show real bank and health data on a device that leaves the house. Whatever the phone stores is decided below, not by accident.
- **iOS limits for web apps:** no haptics API, no icon badges on older iOS, no native widgets. Web push works only for an app added to the home screen (iOS 16.4+). Standalone web apps have no browser pull-to-refresh and no address bar, so back and refresh need to be in the app.

## What's there already

- `index.html` has `viewport-fit=cover`; the phone tab bar and main column pad for `env(safe-area-inset-bottom)` (`components/app-shell.tsx`).
- The phone layout (tab bar, More page, bottom sheets, rows instead of tables) came with M7 and M8; checks so far were at 375px in Chromium.
- Tailwind v4 already applies `hover:` only on devices that can hover, so touch doesn't get stuck hover states.
- The sheet is shadcn's `Sheet` (Radix Dialog): it opens from the bottom on the phone but can't be dragged closed.
- The dev server is Vite on `https://localhost:5173` with a self-signed certificate, bound to `127.0.0.1`, proxying `/api` to the API.

## Slices

Each slice is one fresh session, committed and pushed to `main` once its checks pass. Live checks on the user's phone are listed for the user to do.

### P1: Reach the hub from the phone

- `tailscale serve` on the PC, in front of the frontend, so the phone opens `https://<pc>.<tailnet>.ts.net` with a real certificate (needed for install and the service worker; iOS refuses the self-signed one).
- A production build for the phone: a Compose service serving `pnpm build` through `vite preview` (which reuses the `/api` proxy) on its own port, so the phone gets a fast, stable app while the dev server keeps hot reload. A one-line rebuild command after frontend changes.
- Vite's `allowedHosts` (dev and preview) gains the `.ts.net` name, from an environment variable, not hard-coded.
- README section: install Tailscale on PC and iPhone, switch on MagicDNS and HTTPS certificates in the tailnet admin, run the serve command once. Enable Banking linking stays on the desktop (its redirect is `localhost`).
- **Done when:** Safari on the phone, on 4G, opens Overview with real data over the tailnet, and nothing answers outside it.

### P2: Installable

- Web app manifest: name and short name, `display: standalone`, start URL `/`, dark background and theme colours from the Calm tokens, icons (192, 512, maskable) and `apple-touch-icon` 180px.
- The user's app icon, exported at each size.
- Apple meta: `apple-mobile-web-app-capable`, status bar `black-translucent` with the header padded by `env(safe-area-inset-top)`; `theme-color` follows light/dark and the domain accent where it shows.
- A service worker for the app shell only (HTML, JS, CSS, fonts, icons), so the app opens instantly; `/api` always goes to the network. A quiet "New version, reload" toast when a new build is out. Library or hand-written decided in the slice (`vite-plugin-pwa` if it is maintained and pinnable).
- `lib/standalone.ts`: one place that knows whether the app runs installed, for the slices below.
- **Done when:** "Add to Home Screen" gives the icon, the app opens full screen with no Safari bars, content clears the notch and home bar in both themes, and a rebuild offers the reload.

### P3: Touch basics

- Global CSS: no tap highlight, `touch-action: manipulation` (no double-tap zoom, no tap delay), no text selection on buttons, tabs and rows, `overscroll-behavior` so only lists bounce, not the shell.
- Inputs at 16px or more on the phone, so focusing one doesn't zoom the page.
- Pressed states on rows, pills, tabs and buttons (a quick dim or scale on `:active`), so a tap answers before the page does.
- Tap targets at least 44px on the phone; an audit lists and fixes the small ones.
- Back on detail pages (category, merchant, activity, account): a back button in the header when installed, since there's no browser back.
- Search, Ctrl K on the desktop, gets a button in the phone header.
- **Done when:** a measured check at iPhone size in WebKit finds no input under 16px, no target under 44px, and every detail page has a way back.

### P4: Gestures

- Sheets drag down to close, following the finger, with a handle; the desktop side panel unchanged. Library or own pointer code decided in the slice (shadcn's `Drawer` wraps `vaul`, whose maintenance needs checking first).
- Pull to refresh on the main pages: refetches the page's queries (not a bank sync, which has its own button and limits).
- Swipe from the left edge to go back, if iOS doesn't give it to installed web apps; checked on the phone first.
- **Done when:** each gesture works on the phone and nothing scrolls the page behind an open sheet.

### P5: Motion and continuity

- Page transitions with the View Transitions API through TanStack Router (`defaultViewTransition`): detail pages slide in from the right and back out; tab switches stay instant. Off with `prefers-reduced-motion`.
- Scroll restoration: going back to a list returns to where it was.
- Skeletons sized like the content, so pages don't jump as data arrives.
- **Done when:** going Spending → category → transaction and back keeps the scroll position, and no page shifts after loading.

### P6: Notifications (if decided below)

- Web push: VAPID keys in `secrets/`, a table of a member's push subscriptions (one migration), a pinned `pywebpush`, the worker sending through Apple's push service.
- First alerts: a bill due tomorrow (recurring), a budget overspent, a sync failing for a day, the Garmin key lapsing. A settings page to turn each on or off, and to send a test.
- Alerts only go out while the PC and worker run; `catch_up_syncs`-style catch-up sends the ones missed, at most once each.
- **Done when:** the phone gets a test notification and one real alert, and turning an alert off stops it.

### P7: Device pass

- The impeccable critique on the installed app (the user's phone for feel, WebKit at iPhone sizes for measurements), both themes, both domains. P1 issues fixed in the slice; the rest listed.

## Decided (2026-11-17)

- **Notifications:** in this milestone (P6), arriving while the PC runs.
- **App icon:** the user's own design, supplied for P2.
- **Nothing real on the phone:** the service worker caches the app shell only. `/api` replies are never cached, and query data is never persisted to browser storage. With the PC off, the app opens and says the hub can't be reached.
