/// <reference lib="webworker" />
/**
 * The phone's service worker (M9, docs/design/m9-iphone.md): the app shell only.
 *
 * The build's own files (HTML, JS, CSS, fonts, icons) are kept so the app opens at once, even
 * with the PC off. Nothing else is: `/api` always goes to the network and its replies are never
 * stored, so no bank or health data stays on the phone.
 *
 * A new build waits until the page asks it to take over ("New version, reload").
 */

export {}; // a module, so `self` below is this file's own

type ShellEntry = { url: string; revision: string | null };

declare const self: ServiceWorkerGlobalScope & { __WB_MANIFEST: ShellEntry[] };

// vite-plugin-pwa replaces this with the build's files (injectManifest).
const SHELL: ShellEntry[] = self.__WB_MANIFEST;

const PREFIX = 'hubnisio-shell-';

/** One cache per build, named from its files' revisions, so a new build never mixes with an old one. */
function cacheName(): string {
  let hash = 0;
  for (const entry of SHELL) {
    for (const char of `${entry.url}@${entry.revision ?? ''}`) {
      hash = (hash * 31 + char.charCodeAt(0)) | 0;
    }
  }
  return `${PREFIX}${(hash >>> 0).toString(36)}`;
}

const CACHE = cacheName();
const SHELL_URLS = new Set(SHELL.map((entry) => new URL(entry.url, self.location.href).href));
const INDEX = new URL('index.html', self.location.href).href;

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches
      .open(CACHE)
      .then((cache) =>
        cache.addAll([...SHELL_URLS].map((href) => new Request(href, { cache: 'reload' }))),
      ),
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    (async () => {
      const names = await caches.keys();
      await Promise.all(
        names
          .filter((name) => name.startsWith(PREFIX) && name !== CACHE)
          .map((name) => caches.delete(name)),
      );
      await self.clients.claim();
    })(),
  );
});

self.addEventListener('message', (event) => {
  if (event.data?.type === 'SKIP_WAITING') void self.skipWaiting();
});

self.addEventListener('fetch', (event) => {
  const request = event.request;
  if (request.method !== 'GET') return;
  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;
  // The hub's data: always the network, never stored.
  if (url.pathname.startsWith('/api/') || url.pathname === '/api') return;

  if (request.mode === 'navigate') {
    // Every page is the same single-page app: answer with the kept index.html.
    event.respondWith(fromShell(INDEX, request));
    return;
  }
  const href = url.origin + url.pathname;
  if (SHELL_URLS.has(href)) event.respondWith(fromShell(href, request));
});

async function fromShell(href: string, request: Request): Promise<Response> {
  const cache = await caches.open(CACHE);
  const kept = await cache.match(href);
  return kept ?? fetch(request);
}

// Push alerts (M9 P6, backend core/push.py): show what the hub sent, and open its page on tap.
type PushPayload = { title?: string; body?: string; url?: string; tag?: string | null };

self.addEventListener('push', (event) => {
  let payload: PushPayload = {};
  try {
    payload = event.data?.json() ?? {};
  } catch {
    payload = { body: event.data?.text() };
  }
  event.waitUntil(
    self.registration.showNotification(payload.title ?? 'Hubnisio', {
      body: payload.body ?? '',
      tag: payload.tag ?? undefined,
      icon: '/pwa-192x192.png',
      badge: '/pwa-64x64.png',
      data: { url: payload.url ?? '/' },
    }),
  );
});

self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  const path = (event.notification.data as { url?: string } | null)?.url ?? '/';
  const target = new URL(path, self.location.origin);
  // Only the hub's own pages.
  const url = target.origin === self.location.origin ? target.href : self.location.origin;
  event.waitUntil(
    (async () => {
      const windows = await self.clients.matchAll({ type: 'window', includeUncontrolled: true });
      const open = windows[0];
      if (open) {
        await open.focus();
        await open.navigate(url);
        return;
      }
      await self.clients.openWindow(url);
    })(),
  );
});
