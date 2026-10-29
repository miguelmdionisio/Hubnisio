import { cleanup, fireEvent, screen, waitFor, within } from '@testing-library/react';
import { afterEach, expect, test, vi } from 'vitest';
import type { TransactionCategory, TransactionOut } from '@/api/types.gen';
import { formatMoney } from '@/lib/format';
import { currentMonth, monthStart, shiftMonth } from '@/lib/months';
import { account, categories, transaction } from '@/test/fixtures';
import { mockApi, renderAt } from '@/test/render';
import { reviewGroups, withSkippedLast } from './review-queue';

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const thisMonth = monthStart(currentMonth());
const lastMonth = monthStart(shiftMonth(currentMonth(), -1));
const groceries: TransactionCategory = {
  id: 'c-groceries',
  name: 'Groceries',
  group_name: 'Food',
  source: 'ai',
};
const merchant = (id: string, name: string) => ({ id, name, source: null });

// This month: three from one shop (all suggested Groceries) and a lone one with no merchant;
// last month: one more from the shop.
const shop = merchant('m-shop', 'Mercado Exemplo');
const open = [
  transaction('t1', { occurred_on: thisMonth, counterparty: shop, category: groceries }),
  transaction('t2', { occurred_on: thisMonth, counterparty: shop, category: groceries }),
  transaction('t3', { occurred_on: thisMonth, counterparty: shop, category: groceries }),
  transaction('t4', { occurred_on: thisMonth, description: 'TRF P2P 123', amount: '-50.0000' }),
  transaction('t5', { occurred_on: lastMonth, counterparty: shop, category: groceries }),
];

function api(items: TransactionOut[] = open) {
  const decided = new Set<string>();
  const update = (id: string) => () => {
    decided.add(id);
    return { transaction: transaction(id), offer: null };
  };
  return mockApi({
    'GET /api/finance/accounts': () => [account],
    'GET /api/finance/categories': () => categories,
    'GET /api/finance/transactions': (request) => {
      const search = new URL(request.url).searchParams;
      const left = items.filter((item) => !decided.has(item.id));
      const page =
        search.get('source') === 'ai'
          ? left.filter((item) => item.category?.source === 'ai')
          : left.filter((item) => !item.category);
      return { items: page, next_cursor: null };
    },
    ...Object.fromEntries(
      items.map((item) => [`PATCH /api/finance/transactions/${item.id}`, update(item.id)]),
    ),
  });
}

test('groups open transactions by merchant, this month first, biggest groups first', () => {
  const groups = reviewGroups(open, thisMonth);

  expect(groups.map((group) => [group.section, group.title, group.transactions.length])).toEqual([
    ['this-month', 'Mercado Exemplo', 3],
    ['this-month', 'TRF P2P 123', 1],
    ['earlier', 'Mercado Exemplo', 1],
  ]);
  expect(groups[0]?.suggestion).toMatchObject({ id: 'c-groceries' });
  expect(groups[0]?.total).toEqual({ amount: -126.51, currency: 'EUR' });
  expect(groups[1]?.suggestion).toBeNull();
});

test('says the suggestions are mixed when they differ, and splits one out on request', () => {
  const mixed = [
    ...open.slice(0, 2),
    transaction('t6', {
      occurred_on: thisMonth,
      counterparty: shop,
      category: { ...groceries, id: 'c-old', name: 'Old stuff' },
    }),
  ];
  expect(reviewGroups(mixed, thisMonth)[0]?.suggestion).toBe('mixed');

  const groups = reviewGroups(open, thisMonth, new Set(['t1']));
  expect(groups[0]?.transactions.map((item) => item.id)).toEqual(['t2', 't3']);
  expect(groups.some((group) => group.key === 'this-month:tx:t1')).toBe(true);
});

test('puts skipped groups last, in the order skipped', () => {
  const groups = reviewGroups(open, thisMonth);
  const keys = withSkippedLast(groups, ['this-month:m-shop']).map((group) => group.key);
  expect(keys.at(-1)).toBe('this-month:m-shop');
});

test('approves a whole group at once, then moves on, and can undo it', async () => {
  const calls = api();

  renderAt('/finance/transactions?view=review');

  const card = await screen.findByRole('region', { name: 'Mercado Exemplo' });
  expect(within(card).getByText('Groceries')).toBeDefined();
  expect(screen.getByText(/left/).textContent).toBe('5 left · 4 this month');
  expect(screen.getByRole('button', { name: /Review/ }).textContent).toContain('5');

  fireEvent.click(within(card).getByRole('button', { name: 'Approve Groceries' }));

  expect(await screen.findByRole('region', { name: 'TRF P2P 123' })).toBeDefined();
  await waitFor(() =>
    expect(calls.filter((call) => call.method === 'PATCH').map((call) => call.path)).toEqual([
      '/api/finance/transactions/t1',
      '/api/finance/transactions/t2',
      '/api/finance/transactions/t3',
    ]),
  );
  expect(calls.find((call) => call.method === 'PATCH')?.body).toEqual({
    category_id: 'c-groceries',
  });
  expect(await screen.findByText('Groceries for 3 from Mercado Exemplo')).toBeDefined();

  fireEvent.click(screen.getByRole('button', { name: 'Undo' }));
  await waitFor(() =>
    expect(calls.filter((call) => call.method === 'PATCH').at(-1)?.body).toEqual({
      category_id: null,
    }),
  );
});

test('skips with s, deciding nothing, and offers no transfer button', async () => {
  const calls = api();

  renderAt('/finance/transactions?view=review');

  const card = await screen.findByRole('region', { name: 'Mercado Exemplo' });
  expect(within(card).queryByRole('button', { name: /Transfer/ })).toBeNull();
  fireEvent.keyDown(window, { key: 's' });

  expect(await screen.findByRole('region', { name: 'TRF P2P 123' })).toBeDefined();
  expect(calls.some((call) => call.method === 'PATCH')).toBe(false);
});

test('says when there is nothing to review', async () => {
  api([]);

  renderAt('/finance/transactions?view=review');

  expect(await screen.findByRole('heading', { name: 'Nothing to review' })).toBeDefined();
});

test('lists what comes next', async () => {
  api();

  renderAt('/finance/transactions?view=review');

  await screen.findByRole('region', { name: 'Mercado Exemplo' });
  const next = screen.getByRole('button', { name: /TRF P2P 123/ });
  expect(next.textContent).toContain(formatMoney('-50', 'EUR'));
  fireEvent.click(next);
  expect(await screen.findByRole('region', { name: 'TRF P2P 123' })).toBeDefined();
});

test('opens the category picker with c, and the choice names the category', async () => {
  const calls = api();

  renderAt('/finance/transactions?view=review');

  await screen.findByRole('region', { name: 'Mercado Exemplo' });
  fireEvent.keyDown(window, { key: 'c' });
  fireEvent.click(within(await screen.findByRole('listbox')).getByText('Food (general)'));

  expect(await screen.findByText('Food for 3 from Mercado Exemplo')).toBeDefined();
  expect(calls.find((call) => call.method === 'PATCH')?.body).toEqual({ category_id: 'g-food' });
});
