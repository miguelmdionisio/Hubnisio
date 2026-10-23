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
    hidden_at: null,
    transaction_count: 0,
    balance: {
      balance_type: 'ITAV',
      amount: '90.0000',
      currency: 'EUR',
      fetched_at: new Date().toISOString(),
    },
    ...overrides,
  };
}

const HIDDEN_AT = new Date().toISOString();

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
  expect(screen.queryByRole('button', { name: 'Hide Conta do Rui' })).toBeNull();
  expect(screen.queryByRole('button', { name: /Hidden accounts/ })).toBeNull();

  fireEvent.click(screen.getByRole('switch', { name: 'Conta à Ordem is private' }));
  await waitFor(() =>
    expect(calls.find((call) => call.method === 'PATCH')?.body).toEqual({ visibility: 'private' }),
  );
});

test('hiding an account moves it to the collapsed hidden section, and unhiding brings it back', async () => {
  let hidden = false;
  const calls = mockApi({
    'GET /api/finance/accounts': () => [
      account('a1', {}),
      account('a3', { name: 'Poupança', hidden_at: hidden ? HIDDEN_AT : null }),
    ],
    'PATCH /api/finance/accounts/a3': async (request) => {
      hidden = (await request.json()).hidden;
      return account('a3', { name: 'Poupança', hidden_at: hidden ? HIDDEN_AT : null });
    },
  });

  renderAt('/finance/accounts');

  fireEvent.click(await screen.findByRole('button', { name: 'Hide Poupança' }));
  expect(await screen.findByText(/Its past transactions still count/)).toBeDefined();
  fireEvent.click(screen.getByRole('button', { name: 'Hide account' }));
  await waitFor(() =>
    expect(calls.find((call) => call.method === 'PATCH')?.body).toEqual({ hidden: true }),
  );
  expect(calls[0]?.search.get('include_hidden')).toBe('true');

  const section = await screen.findByRole('button', { name: 'Hidden accounts (1)' });
  expect(screen.queryByText('Poupança')).toBeNull(); // collapsed
  fireEvent.click(section);
  fireEvent.click(await screen.findByRole('button', { name: 'Unhide Poupança' }));
  await waitFor(() =>
    expect(calls.filter((call) => call.method === 'PATCH').at(-1)?.body).toEqual({
      hidden: false,
    }),
  );
  expect(await screen.findByRole('button', { name: 'Hide Poupança' })).toBeDefined();
  expect(screen.queryByRole('button', { name: /Hidden accounts/ })).toBeNull();
});

test('deleting an account with transactions states what goes and asks for its name', async () => {
  let deleted = false;
  const calls = mockApi({
    'GET /api/finance/accounts': () => [
      account('a1', {}),
      ...(deleted
        ? []
        : [account('a3', { name: 'Poupança', hidden_at: HIDDEN_AT, transaction_count: 3 })]),
    ],
    'DELETE /api/finance/accounts/a3': (request) => {
      if (new URL(request.url).searchParams.get('confirm') !== 'true') {
        return Response.json(
          { detail: 'This account has transactions.', transaction_count: 3, transfer_count: 2 },
          { status: 409 },
        );
      }
      deleted = true;
      return new Response(null, { status: 204 });
    },
  });

  renderAt('/finance/accounts');

  fireEvent.click(await screen.findByRole('button', { name: 'Hidden accounts (1)' }));
  fireEvent.click(await screen.findByRole('button', { name: 'Delete Poupança' }));
  expect(await screen.findByText(/Its 3 transactions go with it/)).toBeDefined();
  expect(await screen.findByText(/2 transfers with your other accounts stay marked/)).toBeDefined();
  expect(screen.getByText(/linking the bank again brings it back/)).toBeDefined();

  const confirm = screen.getByRole('button', { name: 'Delete account' });
  expect(confirm).toHaveProperty('disabled', true);
  fireEvent.change(screen.getByLabelText(/to confirm/), { target: { value: 'Poupanç' } });
  expect(confirm).toHaveProperty('disabled', true);
  fireEvent.change(screen.getByLabelText(/to confirm/), { target: { value: 'Poupança' } });
  expect(confirm).toHaveProperty('disabled', false);
  fireEvent.click(confirm);

  await waitFor(() => expect(deleted).toBe(true));
  expect(await screen.findByText('Deleted Poupança.')).toBeDefined();
  await waitFor(() => expect(screen.queryByRole('button', { name: /Hidden accounts/ })).toBeNull());
  const deletes = calls.filter((call) => call.method === 'DELETE');
  expect(deletes.filter((call) => call.search.get('confirm') === 'true')).toHaveLength(1);
});

test('an account without transactions deletes without typing its name', async () => {
  const calls = mockApi({
    'GET /api/finance/accounts': () => [
      account('a3', { name: 'MAD', hidden_at: HIDDEN_AT, transaction_count: 0 }),
    ],
    'DELETE /api/finance/accounts/a3': () => new Response(null, { status: 204 }),
  });

  renderAt('/finance/accounts');

  fireEvent.click(await screen.findByRole('button', { name: 'Hidden accounts (1)' }));
  fireEvent.click(await screen.findByRole('button', { name: 'Delete MAD' }));
  expect(await screen.findByText('It has no transactions.')).toBeDefined();
  expect(screen.queryByLabelText(/to confirm/)).toBeNull();
  fireEvent.click(screen.getByRole('button', { name: 'Delete account' }));

  await waitFor(() =>
    expect(
      calls.filter((call) => call.method === 'DELETE').map((call) => call.search.get('confirm')),
    ).toEqual(['true']),
  );
});

test('an empty list points to linking a bank', async () => {
  mockApi({ 'GET /api/finance/accounts': () => [] });

  renderAt('/finance/accounts');

  expect(await screen.findByText('No accounts yet')).toBeDefined();
});
