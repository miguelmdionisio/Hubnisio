import { cleanup, fireEvent, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, test, vi } from 'vitest';
import type { AccountOut } from '@/api/types.gen';
import { mockApi, renderAt } from '@/test/render';

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

function account(id: string, overrides: Partial<AccountOut>): AccountOut {
  return {
    id,
    name: 'Conta à Ordem',
    institution_name: 'Banco BPI',
    iban_masked: 'PT50 •••• 0154',
    currency: 'EUR',
    cash_account_type: 'CACC',
    visibility: 'shared',
    include_in_net_worth: true,
    is_owner: true,
    balance: {
      balance_type: 'ITAV',
      amount: '90.0000',
      currency: 'EUR',
      fetched_at: new Date().toISOString(),
    },
    ...overrides,
  };
}

test('shows balances, a total, and lets only owners change an account', async () => {
  const calls = mockApi({
    'GET /api/finance/accounts': () => [
      account('a1', {}),
      account('a2', {
        name: 'Conta do Rui',
        is_owner: false,
        balance: { balance_type: 'CLBD', amount: '10.0000', currency: 'EUR', fetched_at: '' },
      }),
      account('a3', { name: 'Poupança', include_in_net_worth: false }),
    ],
    'PATCH /api/finance/accounts/a1': () => account('a1', { visibility: 'private' }),
  });

  renderAt('/finance/accounts');

  expect(await screen.findAllByText('Conta à Ordem')).toHaveLength(1);
  expect(screen.getByText(/^€100\.00$/)).toBeDefined(); // a1 + a2; a3 is left out of net worth
  expect(screen.getByRole('switch', { name: 'Conta do Rui is private' })).toHaveProperty(
    'disabled',
    true,
  );
  expect(screen.queryByRole('button', { name: 'Rename Conta do Rui' })).toBeNull();

  fireEvent.click(screen.getByRole('switch', { name: 'Conta à Ordem is private' }));
  await waitFor(() =>
    expect(calls.find((call) => call.method === 'PATCH')?.body).toEqual({ visibility: 'private' }),
  );
});

test('an empty list points to linking a bank', async () => {
  mockApi({ 'GET /api/finance/accounts': () => [] });

  renderAt('/finance/accounts');

  expect(await screen.findByText('No accounts yet')).toBeDefined();
});
