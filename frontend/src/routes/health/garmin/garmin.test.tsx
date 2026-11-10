import { cleanup, fireEvent, screen, waitFor, within } from '@testing-library/react';
import { afterEach, expect, test, vi } from 'vitest';
import { connection, inDays } from '@/test/health/garmin';
import { mockApi, renderAt } from '@/test/render';

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  localStorage.clear();
  document.documentElement.classList.add('dark');
  delete document.documentElement.dataset.domain;
});

test('shows the link command, and nothing else, when no watch is linked', async () => {
  mockApi({ 'GET /api/health/connection': () => ({ linked: false }) });
  renderAt('/health/garmin');

  expect(await screen.findByText('Not linked')).toBeTruthy();
  expect(screen.getByText('cli garmin-link').tagName).toBe('CODE');
  expect(screen.queryByRole('button', { name: 'Sync now' })).toBeNull();
});

test('shows the last sync, the key and what is stored per kind', async () => {
  mockApi({ 'GET /api/health/connection': () => connection() });
  renderAt('/health/garmin');

  expect(await screen.findByText('2 hours ago')).toBeTruthy();
  expect(screen.getByText('Succeeded')).toBeTruthy();
  expect(screen.getByText('in 200 days')).toBeTruthy();
  const stored = within(
    screen.getByRole('heading', { name: 'Stored' }).parentElement as HTMLElement,
  );
  expect(stored.getAllByRole('listitem').map((li) => li.textContent)).toEqual([
    'Daily summaries1 Feb 2026 – 10 Nov 2026280',
    'Heart rate1 Oct 2026 – 10 Nov 202641,300',
    'Sleep3 Feb 2026 – 10 Nov 2026262',
    'Weigh-ins4 Mar 2026 – 20 Oct 20263',
  ]);
});

test('a failed run and the kinds it skipped are marked', async () => {
  mockApi({
    'GET /api/health/connection': () => {
      const data = connection();
      if (data.last_run) {
        data.last_run = {
          ...data.last_run,
          status: 'failed',
          error_code: 'rate_limited',
          skipped: ['sleeps'],
        };
      }
      return data;
    },
  });
  renderAt('/health/garmin');

  expect(await screen.findByText('Failed (rate_limited)')).toBeTruthy();
  expect(screen.getByText('Skipped')).toBeTruthy();
});

test('Sync now queues a sync and is disabled while one runs', async () => {
  let syncing = false;
  const calls = mockApi({
    'GET /api/health/connection': () => connection({ syncing }),
    'POST /api/health/sync': () => {
      syncing = true;
      return Response.json({ queued: true }, { status: 202 });
    },
  });
  renderAt('/health/garmin');

  fireEvent.click(await screen.findByRole('button', { name: 'Sync now' }));
  const button = await screen.findByRole('button', { name: 'Syncing' });
  expect((button as HTMLButtonElement).disabled).toBe(true);
  expect(calls.filter((call) => call.method === 'POST').map((call) => call.path)).toEqual([
    '/api/health/sync',
  ]);
});

test('a sync already running shows its state from the start', async () => {
  mockApi({ 'GET /api/health/connection': () => connection({ syncing: true }) });
  renderAt('/health/garmin');

  const button = await screen.findByRole('button', { name: 'Syncing' });
  expect((button as HTMLButtonElement).disabled).toBe(true);
});

test('a key lapsing within 14 days is flagged in the warning colour', async () => {
  mockApi({
    'GET /api/health/connection': () =>
      connection({ key_expires_on: inDays(9), key_expires_soon: true }),
  });
  renderAt('/health/garmin');

  const days = await screen.findByText('in 9 days');
  expect(days.parentElement?.className).toContain('text-destructive');
  expect((screen.getByRole('button', { name: 'Sync now' }) as HTMLButtonElement).disabled).toBe(
    false,
  );
});

test('an expired key says so and cannot sync', async () => {
  mockApi({
    'GET /api/health/connection': () =>
      connection({ status: 'expired', key_expires_on: inDays(-3), key_expires_soon: true }),
  });
  renderAt('/health/garmin');

  const word = await screen.findByText(/^Expired/);
  expect(word.className).toContain('text-destructive');
  expect((screen.getByRole('button', { name: 'Sync now' }) as HTMLButtonElement).disabled).toBe(
    true,
  );
});

test('a 409 from Sync now shows its reason and reloads the connection', async () => {
  const calls = mockApi({
    'GET /api/health/connection': () => connection(),
    'POST /api/health/sync': () =>
      Response.json({ detail: 'Link a new Garmin key first.' }, { status: 409 }),
  });
  renderAt('/health/garmin');

  fireEvent.click(await screen.findByRole('button', { name: 'Sync now' }));
  const loaded = () => calls.filter((call) => call.path === '/api/health/connection').length;
  const before = loaded();
  expect((await screen.findByRole('alert')).textContent).toBe('Link a new Garmin key first.');
  await waitFor(() => expect(loaded()).toBeGreaterThan(before));
});
