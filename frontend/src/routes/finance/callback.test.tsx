import { cleanup, screen } from '@testing-library/react';
import { afterEach, expect, test, vi } from 'vitest';
import type { ConnectionOut } from '@/api/types.gen';
import { mockApi, renderAt } from '@/test/render';

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const linked: ConnectionOut = {
  id: 'c1',
  provider: 'enable_banking',
  institution_name: 'Banco BPI',
  institution_country: 'PT',
  status: 'active',
  valid_until: '2027-04-20T12:00:00Z',
  days_left: 179,
  key_file: null,
  last_synced_at: null,
  syncing: true,
  last_error: null,
  account_ids: ['a1', 'a2'],
};

test('completes the link once, then reports the first sync', async () => {
  const calls = mockApi({
    'POST /api/finance/connections/complete': () => linked,
    'GET /api/finance/connections': () => [
      { ...linked, syncing: false, last_synced_at: new Date().toISOString() },
    ],
  });

  renderAt('/finance/connections/callback?code=abc&state=xyz');

  expect(await screen.findByText('Banco BPI is linked')).toBeDefined();
  expect(screen.getByText('The hub can now read 2 accounts.')).toBeDefined();
  expect(await screen.findByText('Your history is in.')).toBeDefined();
  const completions = calls.filter((call) => call.path.endsWith('/complete'));
  expect(completions).toHaveLength(1); // even though strict mode mounts the page twice
  expect(completions[0]?.body).toEqual({ code: 'abc', state: 'xyz' });
});

test("shows the bank's reason when authorization didn't complete", async () => {
  const calls = mockApi({ 'GET /api/finance/connections': () => [] });

  renderAt('/finance/connections/callback?error=access_denied&error_description=User%20cancelled');

  expect(await screen.findByText('User cancelled')).toBeDefined();
  expect(calls.some((call) => call.path.endsWith('/complete'))).toBe(false);
});

test('explains a failed completion', async () => {
  mockApi({
    'POST /api/finance/connections/complete': () =>
      Response.json(
        { detail: 'This authorization was already used. Start again.' },
        { status: 409 },
      ),
    'GET /api/finance/connections': () => [],
  });

  renderAt('/finance/connections/callback?code=abc&state=xyz');

  expect(
    await screen.findByText('This authorization was already used. Start again.'),
  ).toBeDefined();
});
