import { cleanup, fireEvent, screen, waitFor, within } from '@testing-library/react';
import { afterEach, expect, test, vi } from 'vitest';
import {
  account,
  budget,
  budgetsOut,
  categories,
  merchant,
  spendingMonth,
  spendingRank,
  transaction,
} from '@/test/fixtures';
import { mockApi, renderAt } from '@/test/render';

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const pot = { ...account, id: 'a-pot', name: 'Joint pot', is_pot: true };
const revolut = { ...account, id: 'a-rev', name: 'Revolut Main' };

function mockSpending(overrides: Record<string, (request: Request) => unknown> = {}) {
  return mockApi({
    'GET /api/finance/insights/spending/month': () => spendingMonth(),
    'GET /api/finance/accounts': () => [account, revolut, pot],
    'GET /api/finance/categories': () => categories,
    'GET /api/finance/transactions': () => ({ items: [], next_cursor: null }),
    'GET /api/finance/counterparties': () => [merchant('m-pingo', 'Pingo Doce')],
    'GET /api/finance/budgets': () => budgetsOut([]),
    ...overrides,
  });
}

test('shows the month total, its average and the ranked categories', async () => {
  const calls = mockSpending();
  renderAt('/finance/spending?month=2026-09');

  expect(await screen.findByText('€100')).toBeTruthy();
  expect(screen.getByText('€3 avg. per day')).toBeTruthy();
  const groceries = await screen.findByRole('link', { name: /Groceries 1 transaction/ });
  expect(groceries.getAttribute('href')).toBe(
    '/finance/spending/category/c-groceries?month=2026-09',
  );
  expect(screen.getByRole('link', { name: /Uncategorized/ }).getAttribute('href')).toContain(
    'category=uncategorized',
  );
  expect(within(groceries).getByText('60%')).toBeTruthy();

  const call = calls.find((c) => c.path === '/api/finance/insights/spending/month');
  expect(call?.search.get('month')).toBe('2026-09-01');
  expect(call?.search.get('view')).toBe('personal');
});

test('groups by merchant and switches to the running total', async () => {
  mockSpending();
  const { router } = renderAt('/finance/spending?month=2026-09');

  fireEvent.click(await screen.findByRole('button', { name: 'Group by category' }));
  expect((await screen.findByRole('link', { name: /Pingo Doce/ })).getAttribute('href')).toBe(
    '/finance/spending/merchant/m-pingo?month=2026-09',
  );

  fireEvent.click(screen.getByRole('button', { name: 'Running total' }));
  expect(await screen.findByText('vs August')).toBeTruthy();
  expect(screen.getByText(/€50/).textContent).toContain('less');
  expect(screen.getByText('Partial')).toBeTruthy();
  expect(router.state.location.search).toMatchObject({ chart: 'line', group: 'merchant' });
});

test('picking a day shows its payments until the whole month is back', async () => {
  const calls = mockSpending({
    'GET /api/finance/transactions': () => ({
      items: [
        transaction('t1', {
          occurred_on: '2026-09-14',
          amount: '-40.00',
          counterparty_name: 'Café Central',
        }),
      ],
      next_cursor: null,
    }),
  });
  renderAt('/finance/spending?month=2026-09');

  fireEvent.click(await screen.findByRole('button', { name: /14 Sept?: €40\.00/ }));
  expect(await screen.findByText('€40')).toBeTruthy();
  expect(await screen.findByRole('button', { name: /Café Central/ })).toBeTruthy();
  const listed = calls.filter((c) => c.path === '/api/finance/transactions').at(-1);
  expect(listed?.search.get('date_from')).toBe('2026-09-14');
  expect(listed?.search.get('date_to')).toBe('2026-09-14');

  fireEvent.click(screen.getByRole('button', { name: 'Show the whole month' }));
  expect(await screen.findByRole('link', { name: /Groceries/ })).toBeTruthy();
});

test('the account filter leaves the shared pot out of Mine', async () => {
  const calls = mockSpending();
  renderAt('/finance/spending?month=2026-09');

  fireEvent.click(await screen.findByRole('button', { name: 'Account' }));
  expect(await screen.findByRole('button', { name: 'Revolut Main' })).toBeTruthy();
  expect(screen.queryByRole('button', { name: 'Joint pot' })).toBeNull();

  fireEvent.click(screen.getByRole('button', { name: 'Revolut Main' }));
  await waitFor(() =>
    expect(
      calls.some(
        (c) =>
          c.path === '/api/finance/insights/spending/month' &&
          c.search.get('account_id') === 'a-rev',
      ),
    ).toBe(true),
  );
});

test('a category page has its budget, merchants and transactions', async () => {
  const calls = mockSpending({
    'GET /api/finance/budgets': () =>
      budgetsOut([
        budget('c-groceries', 'Groceries', {
          available: '80.00',
          spent: '60.00',
          remaining: '20.00',
        }),
      ]),
    'GET /api/finance/insights/spending/month': () =>
      spendingMonth({
        total: '60.00',
        categories: [spendingRank('c-groceries', 'Groceries', '60.00', { share: '1' })],
        merchants: [spendingRank('m-pingo', 'Pingo Doce', '60.00', { share: '1' })],
      }),
    'GET /api/finance/transactions': () => ({
      items: [
        transaction('t1', {
          occurred_on: '2026-09-03',
          amount: '-60.00',
          counterparty_name: 'Pingo Doce',
          category: { id: 'c-groceries', name: 'Groceries', group_name: 'Food', source: 'rule' },
        }),
      ],
      next_cursor: null,
    }),
  });
  renderAt('/finance/spending/category/c-groceries?month=2026-09');

  expect(await screen.findByRole('heading', { name: 'Groceries' })).toBeTruthy();
  expect(await screen.findByText('€60.00')).toBeTruthy();
  expect(await screen.findByText('€20.00 left')).toBeTruthy();
  expect(screen.getByRole('link', { name: /Pingo Doce/ })).toBeTruthy();
  expect(await screen.findByRole('button', { name: /Pingo Doce Groceries/ })).toBeTruthy();
  expect(screen.queryByRole('button', { name: /Group by/ })).toBeNull();

  const call = calls.find((c) => c.path === '/api/finance/insights/spending/month');
  expect(call?.search.get('category_id')).toBe('c-groceries');
  const listed = calls.find((c) => c.path === '/api/finance/transactions');
  expect(listed?.search.get('category_id')).toBe('c-groceries');
});

test('a merchant page is named from the merchant list', async () => {
  const calls = mockSpending();
  renderAt('/finance/spending/merchant/m-pingo?month=2026-09');

  expect(await screen.findByRole('heading', { name: 'Pingo Doce' })).toBeTruthy();
  const call = calls.find((c) => c.path === '/api/finance/insights/spending/month');
  expect(call?.search.get('merchant')).toBe('m-pingo');
});

test('the month stepper stops at this month', async () => {
  mockSpending();
  const { router } = renderAt('/finance/spending');

  expect(await screen.findByText('This month')).toBeTruthy();
  expect(screen.getByRole<HTMLButtonElement>('button', { name: 'Next month' }).disabled).toBe(true);
  fireEvent.click(screen.getByRole('button', { name: 'Previous month' }));
  await waitFor(() => expect(router.state.location.search).toHaveProperty('month'));
});
