import { cleanup, fireEvent, screen, waitFor, within } from '@testing-library/react';
import { afterEach, expect, test, vi } from 'vitest';
import type { TransactionCategory } from '@/api/types.gen';
import { account, categories, transaction } from '@/test/fixtures';
import { mockApi, renderAt } from '@/test/render';

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

function api() {
  return mockApi({
    'GET /api/finance/accounts': () => [account],
    'GET /api/finance/transactions': (request) =>
      new URL(request.url).searchParams.get('cursor')
        ? {
            items: [transaction('t3', { counterparty_name: 'Café Exemplo', amount: '-3.5000' })],
            next_cursor: null,
          }
        : {
            items: [
              transaction('t1', {
                status: 'pending',
                counterparty_name: 'Supermercado Exemplo',
                description: 'COMPRA 4450',
              }),
              transaction('t2', { description: 'SALARIO OUTUBRO', amount: '2100.0000' }),
            ],
            next_cursor: 'c1',
          },
  });
}

test('lists transactions and loads more pages', async () => {
  const calls = api();

  renderAt('/finance/transactions');

  expect(await screen.findByText('Supermercado Exemplo')).toBeDefined();
  expect(screen.getByText('COMPRA 4450')).toBeDefined();
  expect(screen.getByText('Pending')).toBeDefined();
  expect(screen.getByText(/2,100\.00/)).toBeDefined();
  fireEvent.click(screen.getByRole('button', { name: 'Load more' }));

  expect(await screen.findByText('Café Exemplo')).toBeDefined();
  expect(screen.queryByRole('button', { name: 'Load more' })).toBeNull();
  const pages = calls.filter((call) => call.path === '/api/finance/transactions');
  // Strict mode mounts twice, and the abort on the first unmount re-requests a page; pages matter.
  const cursors = new Set(pages.map((call) => call.search.get('cursor')));
  expect([...cursors]).toEqual([null, 'c1']);
});

test('money in with an expense category is a repayment or refund, not income', async () => {
  const rent: TransactionCategory = {
    id: 'c-rent',
    name: 'Rent & mortgage',
    group_name: 'Housing',
    source: 'manual',
  };
  mockApi({
    'GET /api/finance/accounts': () => [account],
    'GET /api/finance/categories': () => categories,
    'GET /api/finance/transactions': () => ({
      items: [
        transaction('t1', { counterparty_name: 'Ana Silva', amount: '600.0000', category: rent }),
        transaction('t2', {
          counterparty_name: 'Zara',
          amount: '25.0000',
          bank_code: 'CARD_REFUND',
          category: { ...rent, id: 'c-clothes', name: 'Clothes' },
        }),
        transaction('t3', {
          description: 'DEV. COMPRA 4450',
          amount: '10.0000',
          category: { ...rent, id: 'c-home', name: 'Home & garden' },
        }),
        transaction('t4', { description: 'SALARIO', amount: '2100.0000', kind: 'income' }),
        transaction('t5', { counterparty_name: 'Continente', category: rent }),
      ],
      next_cursor: null,
    }),
  });

  renderAt('/finance/transactions');

  const rowOf = async (title: string) =>
    (await screen.findByText(title)).closest('tr') as HTMLElement;
  const ana = within(await rowOf('Ana Silva'));
  expect(ana.getByText('+€600.00').className).not.toContain('text-emerald');
  expect(ana.getByText('Repayment')).toBeDefined();
  expect(within(await rowOf('Zara')).getByText('Refund')).toBeDefined();
  expect(within(await rowOf('DEV. COMPRA 4450')).getByText('Refund')).toBeDefined();
  // Real income stays green, and spending has no hint or plus sign.
  const salary = within(await rowOf('SALARIO'));
  expect(salary.getByText('€2,100.00').className).toContain('text-emerald');
  expect(salary.queryByText(/Repayment|Refund/)).toBeNull();
  const continente = within(await rowOf('Continente'));
  expect(continente.getByText('-€42.17')).toBeDefined();
  expect(continente.queryByText(/Repayment|Refund/)).toBeNull();

  fireEvent.click(screen.getByRole('button', { name: 'Ana Silva' }));
  const panel = await screen.findByRole('dialog');
  expect(within(panel).getByText('Lowers Rent & mortgage by €600.00')).toBeDefined();
});

test('search goes into the URL and the query', async () => {
  const calls = api();
  const { router } = renderAt('/finance/transactions?q=cafe');

  const input = (await screen.findByLabelText('Search transactions')) as HTMLInputElement;
  expect(input.value).toBe('cafe');
  fireEvent.change(input, { target: { value: 'padaria' } });

  await waitFor(() => expect(router.state.location.search).toEqual({ q: 'padaria' }));
  await waitFor(() => expect(calls.some((call) => call.search.get('q') === 'padaria')).toBe(true));
  expect(calls.find((call) => call.path === '/api/finance/transactions')?.search.get('q')).toBe(
    'cafe',
  );
});

test('limits the list to the dates in the URL, and clears them', async () => {
  const calls = api();
  const { router } = renderAt('/finance/transactions?from=2026-10-01&to=2026-10-31&q=cafe');

  const clear = await screen.findByRole('button', { name: /Clear dates/ });
  expect(clear.textContent).toBe('Clear dates (1 Oct 2026 to 31 Oct 2026)');
  const first = calls.find((call) => call.path === '/api/finance/transactions');
  expect(first?.search.get('date_from')).toBe('2026-10-01');
  expect(first?.search.get('date_to')).toBe('2026-10-31');

  fireEvent.click(clear);
  await waitFor(() => expect(router.state.location.search).toEqual({ q: 'cafe' }));
  await waitFor(() =>
    expect(calls.at(-1)?.search.has('date_from') || calls.at(-1)?.search.has('date_to')).toBe(
      false,
    ),
  );
});

test('ignores dates that are not real', async () => {
  const calls = api();
  const { router } = renderAt('/finance/transactions?from=2026-02-30&to=yesterday');

  await screen.findByText('Supermercado Exemplo');
  expect(router.state.location.search).toEqual({});
  const first = calls.find((call) => call.path === '/api/finance/transactions');
  expect(first?.search.has('date_from')).toBe(false);
  expect(first?.search.has('date_to')).toBe(false);
});

test('lists the categories an AI suggested, marked as such', async () => {
  const suggested: TransactionCategory = {
    id: 'c-groceries',
    name: 'Groceries',
    group_name: 'Food',
    source: 'ai',
  };
  const calls = mockApi({
    'GET /api/finance/accounts': () => [account],
    'GET /api/finance/categories': () => categories,
    'GET /api/finance/transactions': () => ({
      items: [transaction('t1', { counterparty_name: 'Mercado', category: suggested })],
      next_cursor: null,
    }),
  });

  renderAt('/finance/transactions?category=suggested');

  const row = (await screen.findByText('Mercado')).closest('tr') as HTMLElement;
  expect(within(row).getByTitle('suggested by AI').textContent).toBe('GroceriesAI');
  expect(screen.getByRole('combobox', { name: 'Category' }).textContent).toBe('Suggested by AI');
  const request = calls.find((call) => call.path === '/api/finance/transactions');
  expect(request?.search.get('source')).toBe('ai');
  expect(request?.search.has('category_id')).toBe(false);
  expect(request?.search.has('uncategorized')).toBe(false);
});

test('approves AI suggestions one at a time, or all those shown', async () => {
  const suggested: TransactionCategory = {
    id: 'c-groceries',
    name: 'Groceries',
    group_name: 'Food',
    source: 'ai',
  };
  const calls = mockApi({
    'GET /api/finance/accounts': () => [account],
    'GET /api/finance/categories': () => categories,
    'GET /api/finance/transactions': () => ({
      items: [
        transaction('t1', { counterparty_name: 'Mercado', category: suggested }),
        transaction('t2', { counterparty_name: 'Padaria', category: suggested }),
        transaction('t3', {
          counterparty_name: 'Café',
          category: { ...suggested, source: 'manual' },
        }),
      ],
      next_cursor: null,
    }),
    'POST /api/finance/transactions/approve-suggestions': () => ({ approved: 1 }),
  });
  const approvals = () =>
    calls.filter((call) => call.path === '/api/finance/transactions/approve-suggestions');

  renderAt('/finance/transactions?category=suggested');

  const row = (await screen.findByText('Mercado')).closest('tr') as HTMLElement;
  const mine = screen.getByText('Café').closest('tr') as HTMLElement;
  expect(within(mine).queryByRole('button', { name: 'Approve Groceries' })).toBeNull();
  fireEvent.click(within(row).getByRole('button', { name: 'Approve Groceries' }));
  await waitFor(() => expect(approvals()).toHaveLength(1));
  expect(approvals()[0]?.body).toEqual({ transaction_ids: ['t1'] });

  const all = screen.getByRole('button', { name: 'Approve the 2 shown' }) as HTMLButtonElement;
  await waitFor(() => expect(all.disabled).toBe(false));
  fireEvent.click(all);
  await waitFor(() => expect(approvals()).toHaveLength(2));
  expect(approvals()[1]?.body).toEqual({ transaction_ids: ['t1', 't2'] });
});
