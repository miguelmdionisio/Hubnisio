import { cleanup, screen, within } from '@testing-library/react';
import { afterEach, expect, test, vi } from 'vitest';
import { holding, investmentAccount } from '@/test/fixtures';
import { mockApi, renderAt } from '@/test/render';

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
