import { cleanup, fireEvent, screen, waitFor, within } from '@testing-library/react';
import { afterEach, expect, test, vi } from 'vitest';
import { holding, investmentAccount, investmentReturns } from '@/test/fixtures';
import { type ApiCall, mockApi, renderAt } from '@/test/render';

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const MONTHS = ['2026-08-01', '2026-09-01', '2026-10-01'];

test('shows the value, the holdings with their weight, and what they paid', async () => {
  const calls = mockApi({
    'GET /api/finance/investments': () => ({
      months: MONTHS,
      accounts: [
        investmentAccount(3, {
          value: '1234.56',
          cash: '34.56',
          cost: '1100.00',
          result: '100.00',
          realised_result: '12.50',
          holdings: [
            holding('XWLD_EQ', 'Test World ETF', {
              quantity: '7.1234567000',
              value: '800.00',
              cost: '700.00',
              result: '100.00',
              weight: '0.6667',
            }),
            holding('XACM_US_EQ', 'Acme Test Inc', {
              type: 'STOCK',
              value: '400.00',
              cost: '400.00',
              result: '-5.00',
              weight: '0.3333',
            }),
          ],
          dividends: ['0.00', '1.50', '3.21'],
          interest: ['0.10', '0.00', '0.42'],
        }),
      ],
    }),
  });

  renderAt('/finance/investments');

  expect(await screen.findByRole('heading', { name: 'Trading 212 EUR' })).toBeDefined();
  expect(screen.getByRole('link', { name: 'Investments' })).toBeDefined();
  expect(screen.getByText('€1,234.56')).toBeDefined();
  expect(screen.getByText('€34.56')).toBeDefined();
  expect(screen.getByText('€1,100.00')).toBeDefined();
  expect(screen.getByText('+€100.00', { selector: 'p' })).toBeDefined();
  expect(screen.getByText('+9.1%')).toBeDefined(); // the result on the cost
  expect(screen.getByText('€12.50 realised on sales')).toBeDefined();

  const rows = screen.getAllByRole('row').slice(1);
  expect(rows).toHaveLength(2);
  const world = within(rows[0] as HTMLElement);
  expect(world.getByText('Test World ETF')).toBeDefined();
  expect(world.getByText('XWLD_EQ · ETF')).toBeDefined();
  expect(world.getByText('7.123457')).toBeDefined();
  expect(world.getByText('US$110.00')).toBeDefined(); // the price, in the instrument's currency
  expect(world.getByText('66.7%')).toBeDefined();
  const acme = within(rows[1] as HTMLElement);
  expect(acme.getByText('XACM_US_EQ · Stock')).toBeDefined();
  expect(acme.getByText('-€5.00').className).toContain('text-destructive');

  expect(screen.getByText(/the last 3 months: €5\.23 in all/)).toBeDefined();
  expect(calls[0]?.search.get('months')).toBe('12');
});

test('says when there are no investment accounts', async () => {
  mockApi({ 'GET /api/finance/investments': () => ({ months: MONTHS, accounts: [] }) });

  renderAt('/finance/investments');

  expect(await screen.findByText('No investment accounts')).toBeDefined();
});

test('an account not synced since holdings came shows no figures yet', async () => {
  mockApi({
    'GET /api/finance/investments': () => ({
      months: MONTHS,
      accounts: [
        investmentAccount(3, { as_of: null, value: null, cash: null, cost: null, result: null }),
      ],
    }),
  });

  renderAt('/finance/investments');

  expect(await screen.findByText('No holdings yet')).toBeDefined();
  expect(screen.queryByText('Value')).toBeNull();
  expect(screen.getByText('Nothing paid in these months.')).toBeDefined();
});

test('checks the value rebuilt from trades against Trading 212', async () => {
  const check = {
    on: '2026-10-20',
    rebuilt_value: '1070.00',
    difference: '0.00',
    unpriced: [],
    unexplained_cash: '0.00',
    unexplained: [],
  };
  mockApi({
    'GET /api/finance/investments': () => ({
      months: MONTHS,
      accounts: [investmentAccount(3, { value: '1070.00', check })],
    }),
  });

  renderAt('/finance/investments');

  expect(await screen.findByRole('heading', { name: 'Check against Trading 212' })).toBeDefined();
  expect(screen.getByText(/On 20 Oct 2026, the day of the latest sync/)).toBeDefined();
  expect(screen.getByText('They match to the cent.')).toBeDefined();
});

test('says what the rebuild leaves out and what the history misses', async () => {
  const check = {
    on: '2026-10-20',
    rebuilt_value: '775.00',
    difference: '-165.00',
    unpriced: ['Acme Test Inc'],
    unexplained_cash: '-5.00',
    unexplained: [{ ticker: 'XWLD_EQ', name: 'Test World ETF', quantity: '3.0000000000' }],
  };
  mockApi({
    'GET /api/finance/investments': () => ({
      months: MONTHS,
      accounts: [investmentAccount(3, { value: '940.00', check })],
    }),
  });

  renderAt('/finance/investments');

  expect(await screen.findByText('-€165.00')).toBeDefined();
  expect(screen.getByText('€775.00')).toBeDefined();
  expect(screen.queryByText('They match to the cent.')).toBeNull();
  expect(screen.getByText('Left out, with no price for that day: Acme Test Inc.')).toBeDefined();
  expect(
    screen.getByText(/Trading 212 has €5\.00 less cash and 3 more shares of Test World ETF than/),
  ).toBeDefined();
});

const RETURNS = '/api/finance/investments/returns';

function mockReturns(returns = investmentReturns()): ApiCall[] {
  return mockApi({
    'GET /api/finance/investments': () => ({ months: MONTHS, accounts: [investmentAccount(3)] }),
    [`GET ${RETURNS}`]: () => ({ accounts: [returns] }),
  });
}

test('shows the returns over the period, broken down, against net deposits', async () => {
  const calls = mockReturns(investmentReturns({ date_from: '2025-08-01' }));

  renderAt('/finance/investments');

  expect(await screen.findByRole('heading', { name: 'Returns' })).toBeDefined();
  expect(await screen.findByText('1 Aug 2025 to 20 Oct 2026')).toBeDefined();
  expect(screen.getByText('+12.3%')).toBeDefined();
  expect(screen.getByText('+11% a year')).toBeDefined();
  expect(screen.getByText(/whatever the timing of deposits and withdrawals/)).toBeDefined();
  expect(screen.getByText('+11.5%')).toBeDefined();
  expect(screen.getByText('+10.2% a year')).toBeDefined();
  expect(screen.getByText(/given when it went in and came out/)).toBeDefined();

  const line = (label: string) =>
    screen.getByText(label, { selector: 'dt' }).nextElementSibling?.textContent;
  expect(line('Value at the start')).toBe('€0.00');
  expect(line('Net deposits')).toBe('+€800.00');
  expect(line('Result')).toBe('+€100.00');
  expect(line('Price movements, realised')).toBe('+€55.25');
  expect(line('Price movements, unrealised')).toBe('+€40.00');
  expect(line('Fees and taxes')).toBe('-€2.75');
  expect(line('Value at the end')).toBe('€900.00');
  expect(screen.queryByText('Other cash movements')).toBeNull();
  expect(screen.getByText('Value against net deposits')).toBeDefined();

  const asked = calls.filter((call) => call.path === RETURNS);
  expect(asked.length).toBeGreaterThan(0);
  expect(asked.some((call) => call.search.has('date_from'))).toBe(false); // all time
});

test('switches the period', async () => {
  const calls = mockReturns();
  const today = new Date();
  const dated = (date: Date) =>
    [date.getFullYear(), date.getMonth() + 1, date.getDate()]
      .map((part) => String(part).padStart(2, '0'))
      .join('-');
  const asked = () =>
    calls.filter((call) => call.path === RETURNS).map((call) => call.search.get('date_from'));

  renderAt('/finance/investments');
  await screen.findByText('+12.3%');
  // Radix tabs switch on mouse down, which jsdom's click doesn't send.
  fireEvent.mouseDown(screen.getByRole('tab', { name: 'This year' }), { button: 0 });
  await waitFor(() => expect(asked()).toContain(`${today.getFullYear()}-01-01`));
  fireEvent.mouseDown(screen.getByRole('tab', { name: '12 months' }), { button: 0 });
  const yearAgo = new Date(today.getFullYear() - 1, today.getMonth(), today.getDate() + 1);
  await waitFor(() => expect(asked()).toContain(dated(yearAgo)));
});

test('says why a return is missing and what the value leaves out', async () => {
  mockReturns(
    investmentReturns({
      time_weighted: null,
      time_weighted_annual: null,
      time_weighted_gap: 'no_money',
      money_weighted: null,
      money_weighted_annual: null,
      money_weighted_gap: 'no_solution',
      unpriced: 4,
      breakdown: { ...investmentReturns().breakdown!, other: '3.00' },
    }),
  );

  renderAt('/finance/investments');

  expect(await screen.findByText('Nothing was invested in this period.')).toBeDefined();
  expect(screen.getByText("No single rate fits this period's money in and out.")).toBeDefined();
  expect(screen.getAllByText('—')).toHaveLength(2);
  expect(screen.getByText(/^4 holding-days have no price and are left out/)).toBeDefined();
  expect(screen.getByText('Other cash movements').nextElementSibling?.textContent).toBe('+€3.00');
});
