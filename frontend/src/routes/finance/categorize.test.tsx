import { cleanup, fireEvent, screen, waitFor, within } from '@testing-library/react';
import { afterEach, expect, test, vi } from 'vitest';
import { account, categories, transaction } from '@/test/fixtures';
import { type ApiCall, mockApi, renderAt, touch } from '@/test/render';

/** The table's own request for a page, not the review queue's (which asks for 200 at a time). */
const tablePage = (call: ApiCall) =>
  call.path === '/api/finance/transactions' && call.search.get('limit') === '50';

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const continente = transaction('t1', {
  counterparty_name: 'CONTINENTE',
  counterparty: { id: 'm1', name: 'Continente', source: 'bank' },
  description: 'COMPRA 4450 CONTINENTE',
});
const transfer = transaction('t2', {
  amount: '-200.0000',
  kind: 'transfer',
  kind_source: 'auto',
  description: 'TRF REVOLUT',
  transfer: {
    id: 'x1',
    other_transaction_id: 't9',
    other_account_id: 'a2',
    other_account_name: 'Revolut ••9659',
    source: 'auto',
  },
});
const salary = transaction('t3', {
  amount: '2100.0000',
  kind: 'income',
  description: 'SALARIO',
  category: { id: 'c-salary', name: 'Salary', group_name: 'Income', source: 'rule' },
});

function api(overrides: Record<string, (request: Request) => unknown> = {}) {
  return mockApi({
    'GET /api/finance/accounts': () => [account],
    'GET /api/finance/categories': () => categories,
    'GET /api/finance/transactions': () => ({
      items: [continente, transfer, salary],
      next_cursor: null,
    }),
    ...overrides,
  });
}

test('shows each transaction’s category, merchant and transfers', async () => {
  api();

  renderAt('/finance/transactions');

  expect(await screen.findByText('Continente')).toBeDefined(); // the merchant, not the raw name
  expect(screen.getByText('Uncategorized')).toBeDefined();
  expect(screen.getByText('To Revolut ••9659')).toBeDefined();
  expect(screen.getByText('Salary').getAttribute('title')).toBe('set by a rule');
});

test('one click in the sheet sets a category, then offers it for the whole merchant', async () => {
  const calls = api({
    'PATCH /api/finance/transactions/t1': () => ({
      transaction: {
        ...continente,
        category: { id: 'c-groceries', name: 'Groceries', group_name: 'Food', source: 'manual' },
      },
      offer: {
        counterparty_id: 'm1',
        counterparty_name: 'Continente',
        category_id: 'c-groceries',
        other_transactions: 4,
      },
    }),
    'PATCH /api/finance/counterparties/m1': () => ({
      id: 'm1',
      name: 'Continente',
      default_category_id: 'c-groceries',
      transactions: 5,
      aliases: ['continente'],
    }),
  });

  renderAt('/finance/transactions');
  fireEvent.click(await screen.findByRole('button', { name: /Continente/ }));
  const panel = within(await screen.findByRole('dialog'));
  expect(panel.queryByText('Old stuff')).toBeNull(); // archived
  fireEvent.click(panel.getByRole('button', { name: 'Groceries' }));

  await waitFor(() =>
    expect(calls.find((call) => call.method === 'PATCH')?.body).toEqual({
      category_id: 'c-groceries',
    }),
  );
  expect(await screen.findByText(/everything from Continente/)).toBeDefined();
  fireEvent.click(screen.getByRole('button', { name: 'Apply to all' }));
  await waitFor(() =>
    expect(calls.find((call) => call.path.endsWith('/counterparties/m1'))?.body).toEqual({
      default_category_id: 'c-groceries',
    }),
  );
});

test('the details panel saves a note', async () => {
  const calls = api({
    'PATCH /api/finance/transactions/t1': () => ({
      transaction: { ...continente, note: 'Jantar' },
      offer: null,
    }),
  });

  renderAt('/finance/transactions');
  fireEvent.click(await screen.findByRole('button', { name: /Continente/ }));
  const panel = await screen.findByRole('dialog');
  expect(within(panel).getByText('COMPRA 4450 CONTINENTE')).toBeDefined(); // bank data
  fireEvent.change(within(panel).getByLabelText('Note'), { target: { value: ' Jantar ' } });
  fireEvent.click(within(panel).getByRole('button', { name: 'Save note' }));

  await waitFor(() =>
    expect(calls.find((call) => call.method === 'PATCH')?.body).toEqual({ note: 'Jantar' }),
  );
});

test('kind and category filters come from the URL', async () => {
  const calls = api();

  renderAt('/finance/transactions?kind=expense&category=uncategorized');

  await screen.findByText('Continente');
  const query = calls.find(tablePage)?.search;
  expect(query?.get('kind')).toBe('expense');
  expect(query?.get('uncategorized')).toBe('true');
  expect(query?.get('category_id')).toBeNull();
});

test('the sheet shows who set the category, approves a suggestion, and links the merchant', async () => {
  const suggested = transaction('t4', {
    counterparty_name: 'PINGO',
    counterparty: { id: 'm2', name: 'Pingo Doce', source: 'bank' },
    category: { id: 'c-groceries', name: 'Groceries', group_name: 'Food', source: 'ai' },
  });
  const calls = api({
    'GET /api/finance/transactions': () => ({ items: [suggested], next_cursor: null }),
    'POST /api/finance/transactions/approve-suggestions': () => ({ approved: 1 }),
  });

  renderAt('/finance/transactions');
  fireEvent.click(await screen.findByRole('button', { name: /Pingo Doce/ }));
  const panel = within(await screen.findByRole('dialog'));
  expect(panel.getByText('AI suggestion')).toBeDefined();
  expect(panel.getByRole('button', { name: 'Groceries' }).getAttribute('aria-pressed')).toBe(
    'true',
  );
  expect(panel.getByRole('link', { name: 'All from Pingo Doce' }).getAttribute('href')).toBe(
    '/finance/spending/merchant/m2',
  );

  fireEvent.click(panel.getByRole('button', { name: 'Approve' }));
  await waitFor(() =>
    expect(calls.find((call) => call.path.endsWith('/approve-suggestions'))?.body).toEqual({
      transaction_ids: ['t4'],
    }),
  );
});

test('on the phone the sheet drags down to close, and springs back from a short pull', async () => {
  api();

  renderAt('/finance/transactions');
  fireEvent.click(await screen.findByRole('button', { name: /Continente/ }));
  const panel = await screen.findByRole('dialog');
  const handle = panel.querySelector('[data-sheet-handle]');
  if (!handle) throw new Error('No handle');

  const drag = (to: number) => {
    touch(handle, 'touchstart', [{ x: 100, y: 100 }]);
    touch(handle, 'touchmove', [{ x: 100, y: 100 + to }]);
    touch(handle, 'touchend', [{ x: 100, y: 100 + to }]);
  };
  drag(20);
  expect(screen.getByRole('dialog')).toBeDefined();
  drag(200);
  await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
});
