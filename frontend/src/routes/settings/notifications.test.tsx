import { cleanup, fireEvent, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, test, vi } from 'vitest';
import type { PushSettings } from '@/api/types.gen';
import { mockApi, renderAt } from '@/test/render';

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const settings = (budgetOver = true): PushSettings => ({
  public_key: 'BKey',
  devices: 1,
  alerts: [
    { kind: 'bill_due', label: 'A bill due tomorrow', enabled: true },
    { kind: 'budget_over', label: 'A budget overspent', enabled: budgetOver },
    { kind: 'sync_failing', label: 'A sync failing for a day', enabled: true },
    { kind: 'key_lapsing', label: 'The Garmin key lapsing', enabled: true },
  ],
});

test('lists the alerts with a switch each, and turns one off', async () => {
  const calls = mockApi({
    'GET /api/push': () => settings(),
    'PUT /api/push/alerts/budget_over': () => settings(false),
  });

  renderAt('/settings/notifications');

  const budget = await screen.findByRole('switch', { name: 'A budget overspent' });
  expect(budget.getAttribute('aria-checked')).toBe('true');
  fireEvent.click(budget);

  await waitFor(() =>
    expect(
      screen.getByRole('switch', { name: 'A budget overspent' }).getAttribute('aria-checked'),
    ).toBe('false'),
  );
  expect(calls.find((call) => call.method === 'PUT')?.body).toEqual({ enabled: false });
  expect(screen.getByText('1 device gets alerts.')).toBeDefined();
});

test('a browser without push says to use the installed app', async () => {
  mockApi({ 'GET /api/push': () => settings() });

  renderAt('/settings/notifications');

  expect(await screen.findByText(/add Hubnisio to the Home Screen/)).toBeDefined();
  expect(screen.queryByRole('button', { name: 'Turn on' })).toBeNull();
});

test('without a push key, the page says how to make one', async () => {
  mockApi({ 'GET /api/push': () => ({ ...settings(), public_key: null }) });

  renderAt('/settings/notifications');

  expect(await screen.findByText(/no push key yet/)).toBeDefined();
});
