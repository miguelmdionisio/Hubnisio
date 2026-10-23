import { cleanup, screen, within } from '@testing-library/react';
import { afterEach, expect, test, vi } from 'vitest';
import { formatMoney } from '@/lib/format';
import { currentMonth } from '@/lib/months';
import {
  budget,
  budgetsOut,
  cashFlow,
  netWorth,
  overallBudget,
  spending,
  spendingGroup,
  transaction,
  upcomingPayment,
} from '@/test/fixtures';
import { mockApi, renderAt } from '@/test/render';

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const month = currentMonth();

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

function api(overrides: Record<string, (request: Request) => unknown> = {}) {
  return mockApi({
    'GET /api/health': () => ({ status: 'ok', database: 'ok' }),
    // 120 more than 30 days before the last day.
    'GET /api/finance/insights/net-worth': () =>
      netWorth([
        ['2026-09-01', '10000.00'],
        ['2026-09-22', '10100.00'],
        ['2026-10-01', '10180.00'],
        ['2026-10-22', '10220.00'],
      ]),
    'GET /api/finance/insights/spending': () =>
      spending(
        ['2026-08-01', '2026-09-01', '2026-10-01'],
        [
          spendingGroup('g-food', 'Food', ['300.00', '320.00', '280.00']),
          spendingGroup('g-home', 'Housing', ['800.00', '800.00', '800.00']),
        ],
        ['10.00', '0.00', '25.00'],
        { unconverted: 2 },
      ),
    'GET /api/finance/insights/cash-flow': () =>
      cashFlow([
        ['2026-08-01', '2500.00', '1900.00'],
        ['2026-09-01', '2500.00', '1750.00'],
        [`${month}-01`, '2500.00', '1234.50'],
      ]),
    'GET /api/finance/budgets': () => budgets,
    'GET /api/finance/transactions': () => ({
      items: [transaction('t1'), transaction('t2'), transaction('t3')],
      next_cursor: null,
    }),
    'GET /api/finance/recurring/upcoming': () => [
      upcomingPayment('s-netflix', 'Netflix', '2026-10-25', '-12.99'),
      upcomingPayment('s-salary', 'Salary', '2026-10-27', '1500.00', { kind: 'income' }),
      upcomingPayment('s-gym', 'Gym', '2026-10-28', '-30.00'),
      upcomingPayment('s-cloud', 'Cloud storage', '2026-11-02', '-5.00', {
        currency: 'USD',
        amount_eur: null,
      }),
    ],
    ...overrides,
  });
}

/** The queries inside one card of the overview, found by its heading. */
async function card(title: string) {
  const heading = await screen.findByRole('heading', { name: title });
  return within(heading.closest('[data-slot="card"]') as HTMLElement);
}

test('shows the API and database status, small, at the bottom', async () => {
  api();

  renderAt('/');

  expect(await screen.findByText('API ok, database ok.')).toBeDefined();
  expect(screen.getByRole('heading', { name: 'Overview' })).toBeDefined();
});

test('says so when the API is unreachable', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => {
      throw new TypeError('Failed to fetch');
    }),
  );

  renderAt('/');

  expect(await screen.findByText('The API is unreachable.')).toBeDefined();
  // Each card says what it couldn't load.
  expect((await screen.findAllByText("Can't reach the hub's API.")).length).toBeGreaterThan(5);
});

test('shows net worth with its change over 30 days', async () => {
  api();

  renderAt('/');

  const netWorthTile = await card('Net worth');
  expect(await netWorthTile.findByText('€10,220.00')).toBeDefined();
  expect(netWorthTile.getByText('+€120.00 in 30 days')).toBeDefined();
  expect(await card('Net worth over time')).toBeDefined();
});

test('compares with the first day when the history is shorter than 30 days', async () => {
  api({
    'GET /api/finance/insights/net-worth': () =>
      netWorth([
        ['2026-10-12', '500.00'],
        ['2026-10-22', '450.00'],
      ]),
  });

  renderAt('/');

  expect(await (await card('Net worth')).findByText('-€50.00 in 10 days')).toBeDefined();
});

test('shows what was spent of what is budgeted this month', async () => {
  api();

  renderAt('/');

  const tile = await card('This month');
  expect(await tile.findByText('€550.00')).toBeDefined();
  expect(tile.getByText('of €670.00 budgeted')).toBeDefined();
  expect(tile.queryByRole('link', { name: 'Set budgets' })).toBeNull();
});

test('shows spending, and a way to set budgets, when there are none', async () => {
  api({ 'GET /api/finance/budgets': () => budgetsOut([]) });

  renderAt('/');

  const tile = await card('This month');
  expect(await tile.findByText('€1,234.50')).toBeDefined();
  expect(tile.getByRole('link', { name: 'Set budgets' }).getAttribute('href')).toBe(
    '/finance/budgets',
  );
  const budgetsCard = await card('Budgets this month');
  expect(await budgetsCard.findByText(/No budgets yet/)).toBeDefined();
  expect(budgetsCard.getByRole('link', { name: 'Create a budget' }).getAttribute('href')).toBe(
    '/finance/budgets',
  );
});

// A cap on all spending: 1,800 spent of 2,000 plus 100 carried in.
const overall = overallBudget({
  rollover: true,
  limit: '2000.00',
  carried_in: '100.00',
  available: '2100.00',
  spent: '1800.00',
  remaining: '300.00',
});

test('shows what was spent of the overall budget this month, when there is one', async () => {
  api({ 'GET /api/finance/budgets': () => ({ ...budgets, overall }) });

  renderAt('/');

  const tile = await card('This month');
  const figure = await tile.findByText('€1,800.00');
  expect(figure.className).not.toContain('text-destructive');
  expect(tile.getByText('of €2,100.00 available')).toBeDefined();
  expect(tile.queryByText('€550.00')).toBeNull(); // not the category budgets' total
});

test('marks the overall budget when it is over', async () => {
  const over = overallBudget({ available: '1500.00', spent: '1800.00', remaining: '-300.00' });
  api({ 'GET /api/finance/budgets': () => ({ ...budgets, overall: over }) });

  renderAt('/');

  expect((await (await card('This month')).findByText('€1,800.00')).className).toContain(
    'text-destructive',
  );
  const bar = (await card('Budgets this month')).getByRole('progressbar', {
    name: 'All spending spent',
  });
  expect(bar.getAttribute('aria-valuetext')).toBe('€1,800.00 of €1,500.00, over budget');
});

test('puts the overall budget at the top of the budgets card', async () => {
  api({ 'GET /api/finance/budgets': () => ({ ...budgets, overall }) });

  renderAt('/');

  const budgetsCard = await card('Budgets this month');
  expect(await budgetsCard.findByText('€1,800.00 of €2,100.00')).toBeDefined();
  const [first, second] = budgetsCard.getAllByRole('listitem');
  expect(first?.textContent).toContain('All spending');
  expect(second?.textContent).toContain('Food');
  expect(budgetsCard.getByRole('progressbar', { name: 'All spending spent' })).toBeDefined();
});

test('lists the overall budget alone when no category has a budget', async () => {
  api({ 'GET /api/finance/budgets': () => budgetsOut([], { overall }) });

  renderAt('/');

  const budgetsCard = await card('Budgets this month');
  expect(await budgetsCard.findByText('€1,800.00 of €2,100.00')).toBeDefined();
  expect(budgetsCard.queryByText(/No budgets yet/)).toBeNull();
  const tile = await card('This month');
  expect(await tile.findByText('of €2,100.00 available')).toBeDefined();
  expect(tile.queryByRole('link', { name: 'Set budgets' })).toBeNull();
});

test('counts what still needs a category this month, and links to it', async () => {
  const calls = api();

  renderAt('/');

  const tile = await card('To categorize');
  expect(await tile.findByText('3')).toBeDefined();
  expect(tile.getByRole('link', { name: 'Review' }).getAttribute('href')).toBe(
    `/finance/transactions?category=uncategorized&from=${month}-01`,
  );
  const request = calls.find((call) => call.path === '/api/finance/transactions');
  expect(request?.search.get('uncategorized')).toBe('true');
  expect(request?.search.get('date_from')).toBe(`${month}-01`);
  expect(request?.search.get('limit')).toBe('200');
});

test('says 200+ when there are more than a page of them', async () => {
  api({
    'GET /api/finance/transactions': () => ({ items: [transaction('t1')], next_cursor: 'more' }),
  });

  renderAt('/');

  expect(await (await card('To categorize')).findByText('200+')).toBeDefined();
});

test('lists each budget against what is available, marking one that is over', async () => {
  api();

  renderAt('/');

  const budgetsCard = await card('Budgets this month');
  expect(await budgetsCard.findByText('€450.00 of €550.00')).toBeDefined();
  expect(budgetsCard.getByText('€40.00 of €70.00')).toBeDefined();
  expect(budgetsCard.getByRole('progressbar', { name: 'Food spent' })).toBeDefined();
  const over = budgetsCard.getByRole('progressbar', { name: 'Fun spent' });
  expect(over.getAttribute('aria-valuetext')).toBe('€60.00 of €50.00, over budget');
  expect(over.firstElementChild?.className).toContain('bg-destructive');
  expect(budgetsCard.getByRole('link', { name: 'All budgets' }).getAttribute('href')).toBe(
    '/finance/budgets',
  );
});

test('charts spending by category and income against spending', async () => {
  api();

  renderAt('/');

  const spendingCard = await card('Spending by category');
  // The legend names the series: the groups, then what has no category.
  expect(await spendingCard.findByText('Food')).toBeDefined();
  expect(spendingCard.getByText('Housing')).toBeDefined();
  expect(spendingCard.getByText('Uncategorized')).toBeDefined();
  expect(spendingCard.getByText(/2 transactions are left out/)).toBeDefined();

  const flowCard = await card('Income vs spending');
  expect(await flowCard.findByText('Income')).toBeDefined();
  expect(flowCard.getByText('Spending')).toBeDefined();
  expect(flowCard.getByText('Net')).toBeDefined();
});

test('lists the expense payments due, with a total', async () => {
  api();

  renderAt('/');

  const upcoming = await card('Upcoming payments');
  expect(await upcoming.findByText('Netflix')).toBeDefined();
  expect(upcoming.getByText('Gym')).toBeDefined();
  expect(upcoming.queryByText('Salary')).toBeNull(); // income isn't a payment
  expect(upcoming.getByText('-€12.99')).toBeDefined();
  // Without a rate, a payment shows in its own currency and stays out of the total.
  expect(upcoming.getByText(formatMoney('-5.00', 'USD'))).toBeDefined();
  expect(upcoming.getByText('-€42.99')).toBeDefined();
  expect(upcoming.getByText(/leaves out 1 in another currency/)).toBeDefined();
});

test('explains where upcoming payments come from when there are none', async () => {
  api({ 'GET /api/finance/recurring/upcoming': () => [] });

  renderAt('/');

  const upcoming = await card('Upcoming payments');
  expect(await upcoming.findByText(/once you've confirmed recurring payments/)).toBeDefined();
  expect(
    upcoming.getByRole('link', { name: 'Review recurring payments' }).getAttribute('href'),
  ).toBe('/finance/recurring');
});

test('one card failing leaves the others alone', async () => {
  api({
    'GET /api/finance/insights/net-worth': () =>
      Response.json({ detail: 'Net worth is broken.' }, { status: 500 }),
  });

  renderAt('/');

  // The tile and the chart both ask for it.
  expect((await screen.findAllByText('Net worth is broken.')).length).toBe(2);
  expect(await (await card('Budgets this month')).findByText('€450.00 of €550.00')).toBeDefined();
});
