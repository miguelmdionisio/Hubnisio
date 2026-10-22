import { cleanup, fireEvent, screen, waitFor, within } from '@testing-library/react';
import { afterEach, expect, test, vi } from 'vitest';
import type { ConnectionOut } from '@/api/types.gen';
import { mockApi, renderAt } from '@/test/render';

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

function connection(overrides: Partial<ConnectionOut>): ConnectionOut {
  return {
    id: 'c1',
    institution_name: 'Banco BPI',
    institution_country: 'PT',
    status: 'active',
    valid_until: '2027-04-20T12:00:00Z',
    days_left: 170,
    last_synced_at: new Date(Date.now() - 5 * 60_000).toISOString(),
    syncing: false,
    last_error: null,
    account_ids: ['a1', 'a2'],
    ...overrides,
  };
}

test('shows each connection and what needs attention', async () => {
  mockApi({
    'GET /api/finance/connections': () => [
      connection({ id: 'c1', days_left: 9, last_error: 'ASPSP_RATE_LIMIT_EXCEEDED' }),
      connection({ id: 'c2', institution_name: 'Revolut', status: 'expired', account_ids: ['a3'] }),
    ],
  });

  renderAt('/finance/connections');

  const bpi = (await screen.findByText('Banco BPI')).closest('[data-slot="card"]') as HTMLElement;
  expect(within(bpi).getByText('2 accounts · consent valid for 9 more days')).toBeDefined();
  expect(within(bpi).getByText('Last synced 5 minutes ago.')).toBeDefined();
  expect(within(bpi).getByText(/daily limit on automatic syncs was reached/)).toBeDefined();
  expect(within(bpi).getByText(/The consent ends in 9 days/)).toBeDefined();
  expect(within(bpi).getByRole('button', { name: 'Link again' })).toBeDefined();

  const revolut = screen.getByText('Revolut').closest('[data-slot="card"]') as HTMLElement;
  expect(within(revolut).getByText('Needs linking again')).toBeDefined();
  expect(within(revolut).queryByRole('button', { name: /sync now/i })).toBeNull();
});

test('sync now queues a sync', async () => {
  const calls = mockApi({
    'GET /api/finance/connections': () => [connection({})],
    'POST /api/finance/connections/c1/sync': () => Response.json({ queued: true }, { status: 202 }),
  });

  renderAt('/finance/connections');
  fireEvent.click(await screen.findByRole('button', { name: /sync now/i }));

  await waitFor(() =>
    expect(calls.some((call) => call.method === 'POST' && call.path.endsWith('/c1/sync'))).toBe(
      true,
    ),
  );
});

test('disconnecting asks first', async () => {
  const calls = mockApi({
    'GET /api/finance/connections': () => [connection({})],
    'DELETE /api/finance/connections/c1': () => new Response(null, { status: 204 }),
  });

  renderAt('/finance/connections');
  fireEvent.click(await screen.findByRole('button', { name: 'Disconnect' }));
  const dialog = await screen.findByRole('dialog');
  expect(calls.some((call) => call.method === 'DELETE')).toBe(false);
  fireEvent.click(within(dialog).getByRole('button', { name: 'Disconnect' }));

  await waitFor(() => expect(calls.some((call) => call.method === 'DELETE')).toBe(true));
});

test('an empty list invites linking a bank', async () => {
  mockApi({ 'GET /api/finance/connections': () => [] });

  renderAt('/finance/connections');

  expect(await screen.findByText('No banks linked yet')).toBeDefined();
});
