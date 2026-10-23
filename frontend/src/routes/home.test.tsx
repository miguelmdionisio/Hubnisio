import { cleanup, fireEvent, screen, within } from '@testing-library/react';
import { afterEach, expect, test, vi } from 'vitest';
import { formatMoney } from '@/lib/format';
import { currentMonth, monthStart, shiftMonth } from '@/lib/months';
import {
  budget,
  budgetsOut,
  cashFlow,
  netWorth,
  overallBudget,
  spending,
  spendingCategory,
  spendingGroup,
  transaction,
  upcomingPayment,
} from '@/test/fixtures';
import { mockApi, renderAt } from '@/test/render';

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  localStorage.clear();
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

const lastMonth = shiftMonth(month, -1);

// Food holds 20 beyond its categories; Tech is refunds above spending; most is uncategorized.
const groceries = spendingCategory('c-groceries', 'Groceries', ['180.00']);
const dining = spendingCategory('c-dining', 'Dining out', ['80.00']);
const thisMonth = spending(
  [monthStart(month)],
  [
    spendingGroup('g-home', 'Housing', ['800.00']),
    spendingGroup('g-food', 'Food', ['280.00'], [groceries, dining]),
    spendingGroup('g-tech', 'Tech', ['-30.00']),
  ],
  ['900.00'],
);
const previousMonth = spending(
  [monthStart(lastMonth)],
  [
    spendingGroup('g-home', 'Housing', ['800.00']),
    spendingGroup(
      'g-food',
      'Food',
      ['100.00'],
      [spendingCategory('c-eats', 'Eating out', ['100.00'])],
    ),
  ],
  ['0.00'],
);

function oneMonthOfSpending(until: string | null) {
  return until === monthStart(lastMonth) ? previousMonth : thisMonth;
}

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
    // The bars ask for twelve months; the donut for one.
    'GET /api/finance/insights/spending': (request) => {
      const params = new URL(request.url).searchParams;
      if (params.get('months') === '1') return oneMonthOfSpending(params.get('until'));
      return spending(
        ['2026-08-01', '2026-09-01', '2026-10-01'],
        [
          spendingGroup('g-food', 'Food', ['300.00', '320.00', '280.00']),
          spendingGroup('g-home', 'Housing', ['800.00', '800.00', '800.00']),
        ],
        ['10.00', '0.00', '25.00'],
        { unconverted: 2 },
      );
    },
    'GET /api/finance/insights/cash-flow': () =>
      cashFlow([
        ['2026-08-01', '2500.00', '1900.00'],
        ['2026-09-01', '2500.00', '1750.00'],
        [`${month}-01`, '2500.00', '1234.50'],
      ]),
    'GET /api/finance/budgets': () => budgets,
    'GET /api/finance/transactions': (request) =>
      new URL(request.url).searchParams.get('source') === 'ai'
        ? { items: [], next_cursor: null }
        : { items: [transaction('t1'), transaction('t2'), transaction('t3')], next_cursor: null },
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
  const request = calls.find(
    (call) => call.path === '/api/finance/transactions' && !call.search.has('source'),
  );
  expect(request?.search.get('uncategorized')).toBe('true');
  expect(request?.search.get('date_from')).toBe(`${month}-01`);
  expect(request?.search.get('limit')).toBe('200');
  expect(tile.queryByText(/suggested by AI/)).toBeNull();
});

test('links to the categories an AI suggested, whatever their month, for review', async () => {
  const calls = api({
    'GET /api/finance/transactions': (request) =>
      new URL(request.url).searchParams.get('source') === 'ai'
        ? { items: [transaction('t4'), transaction('t5')], next_cursor: null }
        : { items: [], next_cursor: null },
  });

  renderAt('/');

  const tile = await card('To categorize');
  const link = await tile.findByRole('link', { name: '2 suggested by AI to review' });
  expect(link.getAttribute('href')).toBe('/finance/transactions?category=suggested');
  expect(tile.getByText('Everything this month has a category.')).toBeDefined();
  const request = calls.find((call) => call.search.get('source') === 'ai');
  expect(request?.path).toBe('/api/finance/transactions');
  expect(request?.search.has('date_from')).toBe(false);
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

/** The last day of a month, as the Transactions page's `to`. */
function lastDayOf(isoMonth: string): string {
  const [year = 1970, number = 1] = isoMonth.split('-').map(Number);
  return `${isoMonth}-${String(new Date(year, number, 0).getDate()).padStart(2, '0')}`;
}

/** A link's target: its path, and its search params as an object. */
function target(link: HTMLElement) {
  const url = new URL(link.getAttribute('href') as string, 'http://localhost');
  return { path: url.pathname, search: Object.fromEntries(url.searchParams) };
}

/** The legend of the donut: each row's name, amount and share. */
function legend(rows: HTMLElement[]) {
  return rows.map((row) =>
    Array.from(row.firstElementChild?.children ?? [])
      .slice(1) // the colour dot
      .map((cell) => cell.textContent),
  );
}

test('breaks a month down by group, with Uncategorized as its own slice', async () => {
  const calls = api();

  renderAt('/');

  const donut = await card('Spending breakdown');
  // The centre is the month's whole spending: 800 + 280 + 900, less 30 of refunds.
  expect(await donut.findByText('€1,950.00')).toBeDefined();
  expect(donut.getByText('Spent')).toBeDefined();
  expect(legend(donut.getAllByRole('listitem'))).toEqual([
    ['Housing', '€800.00', '40%'],
    ['Food', '€280.00', '14%'],
    ['Uncategorized', '€900.00', '45%'],
  ]);
  expect(donut.getByText(/Left out of the chart.*Tech \(-€30\.00\)/)).toBeDefined();
  const request = calls.find(
    (call) => call.path === '/api/finance/insights/spending' && call.search.get('months') === '1',
  );
  expect(request?.search.get('until')).toBe(monthStart(month));
});

test('links each slice to its transactions of the month', async () => {
  api();

  renderAt('/');

  const donut = await card('Spending breakdown');
  const range = { from: monthStart(month), to: lastDayOf(month) };
  expect(target(await donut.findByRole('link', { name: 'Housing: view transactions' }))).toEqual({
    path: '/finance/transactions',
    search: { category: 'g-home', ...range },
  });
  expect(target(donut.getByRole('link', { name: 'Food: view transactions' })).search).toEqual({
    category: 'g-food',
    ...range,
  });
  const uncategorized = donut.getByRole('link', { name: 'Uncategorized: view transactions' });
  expect(target(uncategorized).search).toEqual({
    category: 'uncategorized',
    kind: 'expense',
    ...range,
  });
});

test('drills into a group, with what was assigned to the group itself, and goes back', async () => {
  api();

  renderAt('/');

  const donut = await card('Spending breakdown');
  expect(donut.queryByRole('button', { name: /Back/ })).toBeNull();
  // Only a group with categories can be drilled into.
  expect(donut.queryByRole('button', { name: /Housing/ })).toBeNull();
  fireEvent.click(await donut.findByRole('button', { name: /^Food/ }));

  expect(legend(donut.getAllByRole('listitem'))).toEqual([
    ['Groceries', '€180.00', '64%'],
    ['Dining out', '€80.00', '29%'],
    ['Food (no subcategory)', '€20.00', '7%'],
  ]);
  expect(donut.getByText('€280.00', { selector: 'span.text-lg' })).toBeDefined(); // the centre
  expect(donut.queryByText('Housing')).toBeNull();
  expect(donut.queryByText(/Left out/)).toBeNull();
  const range = { from: monthStart(month), to: lastDayOf(month) };
  expect(target(donut.getByRole('link', { name: 'Groceries: view transactions' })).search).toEqual({
    category: 'c-groceries',
    ...range,
  });
  // The group's filter includes its categories: the closest there is to "no subcategory".
  const remainder = donut.getByRole('link', { name: 'Food (no subcategory): view transactions' });
  expect(target(remainder).search).toEqual({ category: 'g-food', ...range });

  fireEvent.click(donut.getByRole('button', { name: /Back/ }));

  expect(donut.getByText('€1,950.00')).toBeDefined();
  expect(donut.getByRole('link', { name: 'Housing: view transactions' })).toBeDefined();
  expect(donut.queryByRole('button', { name: /Back/ })).toBeNull();
});

test('drills in by clicking a slice of the ring too', async () => {
  api();

  renderAt('/');

  const donut = await card('Spending breakdown');
  await donut.findByRole('button', { name: /^Food/ });
  const sectors = document.querySelectorAll('.recharts-pie-sector');
  expect(sectors.length).toBe(3); // Housing, Food, Uncategorized
  fireEvent.click(sectors[1]?.querySelector('path') as Element);

  expect(await donut.findByRole('button', { name: /Back/ })).toBeDefined();
  expect(donut.getByRole('link', { name: 'Groceries: view transactions' })).toBeDefined();
});

// Eight groups: the six biggest are drawn as such, and Tech and Pets fold into Other.
const manyGroups = spending(
  [monthStart(month)],
  [
    spendingGroup('g1', 'Rent', ['500.00']),
    spendingGroup('g2', 'Food', ['300.00']),
    spendingGroup('g3', 'Car', ['100.00']),
    spendingGroup('g4', 'Gifts', ['90.00']),
    spendingGroup('g5', 'Health', ['40.00']),
    spendingGroup('g6', 'Fun', ['10.00']),
    spendingGroup('g7', 'Pets', ['5.00'], [spendingCategory('c-vet', 'Vet', ['5.00'])]),
    spendingGroup('g8', 'Tech', ['7.00']),
  ],
  ['0.00'],
);

test('folds the smaller groups into Other, which opens onto them', async () => {
  api({ 'GET /api/finance/insights/spending': () => manyGroups });

  renderAt('/');

  const donut = await card('Spending breakdown');
  const other = await donut.findByRole('button', { name: /^Other/ });
  // Several groups have no one list of transactions.
  expect(donut.queryByRole('link', { name: /Other/ })).toBeNull();
  fireEvent.click(other);

  expect(legend(donut.getAllByRole('listitem'))).toEqual([
    ['Tech', '€7.00', '58%'],
    ['Pets', '€5.00', '42%'],
  ]);
  expect(donut.getByText('€12.00', { selector: 'span.text-lg' })).toBeDefined();
  // Pets has categories, so it opens in turn; Back climbs one level at a time.
  fireEvent.click(donut.getByRole('button', { name: /^Pets/ }));
  expect(donut.getByRole('link', { name: 'Vet: view transactions' })).toBeDefined();
  fireEvent.click(donut.getByRole('button', { name: /Back/ }));
  expect(donut.getByRole('button', { name: /^Pets/ })).toBeDefined();
  fireEvent.click(donut.getByRole('button', { name: /Back/ }));
  expect(donut.getByRole('button', { name: /^Other/ })).toBeDefined();
});

test('switches months, back to the first level, and stops at the current month', async () => {
  const calls = api();

  renderAt('/');

  const donut = await card('Spending breakdown');
  fireEvent.click(await donut.findByRole('button', { name: /^Food/ }));
  expect(donut.getByRole('button', { name: /Back/ })).toBeDefined();
  expect((donut.getByRole('button', { name: 'Next month' }) as HTMLButtonElement).disabled).toBe(
    true,
  );

  fireEvent.click(donut.getByRole('button', { name: 'Previous month' }));

  // Housing 800 and Food 100.
  expect(await donut.findByText('€900.00', { selector: 'span.text-lg' })).toBeDefined();
  expect(legend(donut.getAllByRole('listitem'))).toEqual([
    ['Housing', '€800.00', '89%'],
    ['Food', '€100.00', '11%'],
  ]);
  expect(donut.queryByRole('button', { name: /Back/ })).toBeNull();
  const asked = calls
    .filter((call) => call.search.get('months') === '1')
    .map((call) => call.search.get('until'));
  expect(asked).toContain(monthStart(lastMonth));
  // The links follow the month shown.
  const link = donut.getByRole('link', { name: 'Housing: view transactions' });
  expect(target(link).search).toEqual({
    category: 'g-home',
    from: monthStart(lastMonth),
    to: lastDayOf(lastMonth),
  });

  fireEvent.click(donut.getByRole('button', { name: 'Next month' }));

  expect(await donut.findByText('€1,950.00')).toBeDefined();
});

test('says so when a month has no spending', async () => {
  api({ 'GET /api/finance/insights/spending': () => spending([monthStart(month)], [], ['0.00']) });

  renderAt('/');

  const donut = await card('Spending breakdown');
  expect(await donut.findByText(/No spending to chart in/)).toBeDefined();
  expect(donut.queryByRole('list')).toBeNull();
});

test('counts Mine by default; the toggle switches the cards to Household and is remembered', async () => {
  const calls = api();
  const counted = (view: string) =>
    new Set(
      calls
        .filter((call) => call.search.get('view') === view)
        .map((call) => call.path.replace('/api/finance/', '')),
    );

  renderAt('/');

  const toggle = within(await screen.findByRole('group', { name: 'View' }));
  expect(toggle.getByRole('button', { name: 'Mine' }).getAttribute('aria-pressed')).toBe('true');
  expect(await screen.findByText(/A shared pot counts as what you move into it/)).toBeDefined();
  await card('Net worth');
  expect(counted('personal')).toEqual(
    new Set(['insights/net-worth', 'insights/spending', 'insights/cash-flow', 'budgets']),
  );
  expect(counted('household').size).toBe(0);

  fireEvent.click(toggle.getByRole('button', { name: 'Household' }));
  expect(await screen.findByText('Every account in full, shared pots included.')).toBeDefined();
  await vi.waitFor(() =>
    expect(counted('household')).toEqual(
      new Set(['insights/net-worth', 'insights/spending', 'insights/cash-flow', 'budgets']),
    ),
  );

  cleanup();
  renderAt('/');
  const again = within(await screen.findByRole('group', { name: 'View' }));
  expect(again.getByRole('button', { name: 'Household' }).getAttribute('aria-pressed')).toBe(
    'true',
  );
});
