import { cleanup, screen, within } from '@testing-library/react';
import { afterEach, expect, test, vi } from 'vitest';
import type { HealthConnection } from '@/api/types.gen';
import { connection, inDays } from '@/test/health/garmin';
import { mockApi, renderAt } from '@/test/render';

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  localStorage.clear();
  document.documentElement.classList.add('dark');
  delete document.documentElement.dataset.domain;
});

const hoursAgo = (hours: number) => new Date(Date.now() - hours * 3_600_000).toISOString();

/** The Health page header, on a page with no data of its own. */
async function header(data: HealthConnection) {
  mockApi({ 'GET /api/health/connection': () => data });
  renderAt('/health/more');
  const title = await screen.findByRole('heading', { name: 'More', level: 1 });
  return within(title.parentElement as HTMLElement);
}

test('a fresh sync says when, with the good dot', async () => {
  const head = await header(connection({ last_synced_at: hoursAgo(3) }));
  const item = await head.findByText(/^Garmin synced 3 hours ago/);
  expect(item.textContent).not.toContain('stale');
  expect(item.querySelector('i')?.className).toContain('bg-good');
});

test('over 26 hours since the last sync is stale: the dashed ring', async () => {
  const head = await header(connection({ last_synced_at: hoursAgo(27) }));
  const item = await head.findByText(/^Garmin synced/);
  expect(item.textContent).toContain('stale');
  expect(item.querySelector('i')?.className).toContain('border-dashed');
});

test('a failed sync needs a look, linking to the Garmin page', async () => {
  const data = connection();
  if (data.last_run) data.last_run.status = 'failed';
  const head = await header(data);
  const link = await head.findByRole('link', { name: 'Garmin needs a look' });
  expect(link.getAttribute('href')).toBe('/health/garmin');
});

test('a key lapsing within 14 days, or lapsed, needs a look', async () => {
  let head = await header(connection({ key_expires_on: inDays(10), key_expires_soon: false }));
  expect(await head.findByRole('link', { name: 'Garmin needs a look' })).toBeTruthy();

  cleanup();
  head = await header(
    connection({ status: 'expired', key_expires_on: inDays(-2), key_expires_soon: true }),
  );
  expect(await head.findByRole('link', { name: 'Garmin needs a look' })).toBeTruthy();
});

test('nothing linked needs a look too', async () => {
  const head = await header({ linked: false });
  expect(await head.findByRole('link', { name: 'Garmin needs a look' })).toBeTruthy();
});

test('Finance pages keep their own freshness, not Garmin', async () => {
  mockApi({ 'GET /api/finance/connections': () => [] });
  renderAt('/finance/categories');
  await screen.findByRole('heading', { name: 'Categories', level: 1 });
  expect(screen.queryByText(/Garmin/)).toBeNull();
});
