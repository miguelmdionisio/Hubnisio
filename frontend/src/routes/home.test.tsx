import { cleanup, fireEvent, screen, waitFor, within } from '@testing-library/react';
import { afterEach, expect, test, vi } from 'vitest';
import type { ConnectionOut } from '@/api/types.gen';
import { currentMonth, monthStart } from '@/lib/months';
import {
  budget,
  budgetsOut,
  categories,
  netWorth,
  overallBudget,
  spendingMonth,
  transaction,
  upcomingPayment,
} from '@/test/fixtures';
import { mockApi, renderAt } from '@/test/render';

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  localStorage.clear();
});

const budgets = budgetsOut(
  [
    budget('c-food', 'Food', {
      limit: '500.00',
      available: '550.00',
      spent: '450.00',
      remaining: '100.00',
    }),
    budget('c-transport', 'Transport', {
      limit: '70.00',
      available: '70.00',
      spent: '40.00',
      remaining: '30.00',
    }),
    budget('c-fun', 'Fun', {
      limit: '50.00',
      available: '50.00',
      spent: '60.00',
      remaining: '-10.00',
    }),
  ],
  { total_available: '670.00', total_spent: '550.00' },
);

/** A day `days` from today, as the API writes dates. */
function inDays(days: number): string {
  const date = new Date();
  date.setDate(date.getDate() + days);
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`;
}

function api(overrides: Record<string, (request: Request) => unknown> = {}) {
  return mockApi({
    'GET /api/finance/connections': () => [
      connection({ id: 'c-bpi', institution_name: 'Banco BPI', minutesAgo: 120 }),
      connection({ id: 'c-revolut', institution_name: 'Revolut', minutesAgo: 30 }),
    ],
    // 120 more than 30 days before the last day.
    'GET /api/finance/insights/net-worth': () =>
      netWorth([
        ['2026-09-01', '10000.00'],
        ['2026-09-22', '10100.00'],
        ['2026-10-01', '10180.00'],
        ['2026-10-22', '10220.00'],
      ]),
    // €100 spent, €150 by this day of the month before.
    'GET /api/finance/insights/spending/month': () => spendingMonth(),
    'GET /api/finance/budgets': () => budgets,
    'GET /api/finance/categories': () => categories,
    'GET /api/finance/transactions': (request) =>
      new URL(request.url).searchParams.get('source') === 'ai'
        ? { items: [transaction('t9')], next_cursor: null }
        : { items: [transaction('t1'), transaction('t2'), transaction('t3')], next_cursor: null },
    'GET /api/finance/recurring/upcoming': () => [
      upcomingPayment('s-netflix', 'Netflix', inDays(2), '-12.99'),
      upcomingPayment('s-salary', 'Salary', inDays(3), '1500.00', { kind: 'income' }),
      upcomingPayment('s-gym', 'Gym', inDays(6), '-30.00'),
      upcomingPayment('s-insurance', 'Insurance', inDays(20), '-80.00'),
      upcomingPayment('s-cloud', 'Cloud storage', inDays(25), '-5.00', {
        currency: 'USD',
        amount_eur: null,
      }),
    ],
    ...overrides,
  });
}

function connection({
  minutesAgo = 5,
  ...overrides
}: Partial<ConnectionOut> & { minutesAgo?: number }): ConnectionOut {
  return {
    id: 'c1',
    provider: 'enable_banking',
    institution_name: 'Banco BPI',
    institution_country: 'PT',
    status: 'active',
    valid_until: '2027-04-20T12:00:00Z',
    days_left: 170,
    key_file: null,
    last_synced_at: new Date(Date.now() - minutesAgo * 60_000).toISOString(),
    syncing: false,
    last_error: null,
    account_ids: ['a1'],
    ...overrides,
  };
}

/** One of the four figures at the top, by its label. */
async function tile(label: string | RegExp) {
  return (await screen.findByText(label)).closest('a') as HTMLAnchorElement;
}

/** The queries inside one section, found by its heading. */
async function section(title: string) {
  const heading = await screen.findByRole('heading', { name: title });
  return within(heading.closest('section') as HTMLElement);
}

test('says when each bank last synced, next to the title', async () => {
  api();

  renderAt('/');

  expect(await screen.findByText('Banco BPI synced 2 hours ago')).toBeDefined();
  expect(screen.getByText('Revolut synced 30 minutes ago')).toBeDefined();
  expect(screen.queryByRole('link', { name: 'Check bank connections' })).toBeNull();
  expect(screen.getByRole('heading', { name: 'Overview' })).toBeDefined();
});

test('flags a bank that needs a look, and links to the connections', async () => {
  api({
    'GET /api/finance/connections': () => [
      connection({ id: 'c-bpi', institution_name: 'Banco BPI', minutesAgo: 3 * 24 * 60 }),
      connection({ id: 'c-revolut', institution_name: 'Revolut', status: 'expired' }),
      connection({ id: 'c-t212', institution_name: 'Trading 212', last_error: 'HTTP_500' }),
    ],
  });

  renderAt('/');

  const stale = await screen.findByText('Banco BPI synced 3 days ago');
  expect(stale.className).toContain('text-destructive');
  expect(screen.getByText('Revolut needs reconnecting')).toBeDefined();
  expect(screen.getByText('Trading 212 failed its last sync')).toBeDefined();
  expect(screen.getByRole('link', { name: 'Check bank connections' }).getAttribute('href')).toBe(
    '/finance/connections',
  );
});

test('four figures open their pages: spent, left to spend, due soon, net worth', async () => {
  api();

  renderAt('/');

  const spent = await tile('Spent this month');
  expect(spent.getAttribute('href')).toBe('/finance/spending');
  await waitFor(() => expect(spent.textContent).toContain('€100'));
  expect(spent.textContent).toContain('−€50 vs Aug');

  const left = await tile('Left to spend');
  expect(left.getAttribute('href')).toBe('/finance/budgets');
  await waitFor(() => expect(left.textContent).toContain('€120')); // 670 available, 550 spent

  const due = await tile('Due in 7 days');
  expect(due.getAttribute('href')).toBe('/finance/recurring');
  await waitFor(() => expect(due.textContent).toContain('€42.99'));
  expect(due.textContent).toContain('2 bills');

  const worth = await tile('Net worth');
  expect(worth.getAttribute('href')).toBe('/finance/accounts');
  await waitFor(() => expect(worth.textContent).toContain('€10,220'));
  expect(worth.textContent).toContain('+€120');
});

test('left to spend counts the overall budget, and says when it is over', async () => {
  api({
    'GET /api/finance/budgets': () =>
      budgetsOut([], { overall: overallBudget({ spent: '2100.00', remaining: '-100.00' }) }),
  });

  renderAt('/');

  const left = await tile('Left to spend');
  await waitFor(() => expect(left.textContent).toContain('€100 over'));
});

test('without budgets, left to spend says so and the section offers to set one', async () => {
  api({ 'GET /api/finance/budgets': () => budgetsOut([]) });

  renderAt('/');

  const left = await tile('Left to spend');
  await waitFor(() => expect(left.textContent).toContain('No budget'));
  expect(
    await (await section('Budgets')).findByRole('link', { name: 'Set a budget' }),
  ).toBeDefined();
});

test('lists the overall budget first, then each budget with what is left or over', async () => {
  api({
    'GET /api/finance/budgets': () => ({
      ...budgets,
      overall: overallBudget({ spent: '550.00', remaining: '1450.00' }),
    }),
  });

  renderAt('/');

  const list = await section('Budgets');
  const rows = await list.findAllByRole('link', { name: /left|over/ });
  expect(rows.map((row) => row.textContent)).toEqual([
    'All spending€1,450 left',
    'Food€100 left',
    'Transport€30 left',
    'Fun€10 over',
  ]);
  expect(rows[1]?.getAttribute('href')).toBe('/finance/spending/category/c-food');
  expect(list.getByRole('progressbar', { name: 'Fun spent' }).getAttribute('aria-valuetext')).toBe(
    '€60.00 of €50.00, over budget',
  );
});

test('lists the expense payments coming up', async () => {
  api();

  renderAt('/');

  const list = await section('Coming up');
  await list.findByText('Netflix');
  expect(list.queryByText('Salary')).toBeNull();
  expect(list.getByText('−€12.99')).toBeDefined();
  expect(list.getAllByRole('listitem')).toHaveLength(4);
});

test('offers to confirm recurring payments when none is coming up', async () => {
  api({ 'GET /api/finance/recurring/upcoming': () => [] });

  renderAt('/');

  expect(
    await (await section('Coming up')).findByRole('link', { name: 'Confirm recurring payments' }),
  ).toBeDefined();
});

test('links what still needs a category, and the AI suggestions, to the review', async () => {
  const calls = api();

  renderAt('/');

  const review = await screen.findByRole('link', { name: '3 uncategorized · 1 suggested' });
  expect(review.getAttribute('href')).toBe('/finance/transactions?view=review');
  const uncategorized = calls.find((call) => call.search.get('uncategorized') === 'true');
  expect(uncategorized?.search.get('date_from')).toBe(monthStart(currentMonth()));
});

test('says over 200 when there are more than a page of them', async () => {
  api({
    'GET /api/finance/transactions': () => ({ items: [transaction('t1')], next_cursor: 'c2' }),
  });

  renderAt('/');

  expect(
    await screen.findByRole('link', { name: '200+ uncategorized · 200+ suggested' }),
  ).toBeDefined();
});

test('charts what was spent each day', async () => {
  api();

  renderAt('/');

  const perDay = await section('Spent per day');
  expect(await perDay.findByText(/3 Sept?: €60\.00/)).toBeDefined();
  expect(perDay.getByRole('link', { name: 'Spending' }).getAttribute('href')).toBe(
    '/finance/spending',
  );
});

test('says so when the API is unreachable', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => {
      throw new TypeError('Failed to fetch');
    }),
  );

  renderAt('/');

  // The sections and the sync line say what they couldn't load; the figures show a dash.
  await waitFor(() =>
    expect(screen.getAllByText("Can't reach the hub's API.").length).toBeGreaterThan(2),
  );
  expect((await tile('Net worth')).textContent).toContain('—');
});

test('one figure failing leaves the others alone', async () => {
  api({
    'GET /api/finance/insights/net-worth': () =>
      Response.json({ detail: 'Net worth is broken.' }, { status: 500 }),
  });

  renderAt('/');

  await waitFor(async () =>
    expect((await tile('Net worth')).querySelector('strong')?.title).toBe('Net worth is broken.'),
  );
  expect(await (await section('Budgets')).findByText('Food')).toBeDefined();
});

test('counts Mine by default; the toggle switches the figures to Household and is remembered', async () => {
  const calls = api();
  const counted = (view: string) =>
    new Set(
      calls
        .filter((call) => call.search.get('view') === view)
        .map((call) => call.path.replace('/api/finance/', '')),
    );
  const all = new Set(['insights/net-worth', 'insights/spending/month', 'budgets']);

  renderAt('/');

  const toggle = within(await screen.findByRole('group', { name: 'View' }));
  expect(toggle.getByRole('button', { name: 'Mine' }).getAttribute('aria-pressed')).toBe('true');
  await vi.waitFor(() => expect(counted('personal')).toEqual(all));
  expect(counted('household').size).toBe(0);

  fireEvent.click(toggle.getByRole('button', { name: 'Household' }));
  await vi.waitFor(() => expect(counted('household')).toEqual(all));

  cleanup();
  renderAt('/');
  const again = within(await screen.findByRole('group', { name: 'View' }));
  expect(again.getByRole('button', { name: 'Household' }).getAttribute('aria-pressed')).toBe(
    'true',
  );
});
