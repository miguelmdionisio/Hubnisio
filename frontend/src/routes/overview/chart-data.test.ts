import { expect, test } from 'vitest';
import { cashFlow, netWorth, spending, spendingGroup } from '@/test/fixtures';
import { axisTicks, cashFlowRows, netWorthChange, spendingChart } from './chart-data';

const months = ['2026-08-01', '2026-10-01'];

test('stacks the six biggest groups, then Other, then Uncategorized', () => {
  // Eight groups, ranked by their total over the months.
  const groups = [
    spendingGroup('g1', 'Fun', ['10.00', '10.00']),
    spendingGroup('g2', 'Rent', ['500.00', '500.00']),
    spendingGroup('g3', 'Food', ['300.00', '200.00']),
    spendingGroup('g4', 'Car', ['100.00', '0.00']),
    spendingGroup('g5', 'Health', ['40.00', '60.00']),
    spendingGroup('g6', 'Gifts', ['0.00', '90.00']),
    spendingGroup('g7', 'Pets', ['5.00', '5.00']),
    spendingGroup('g8', 'Tech', ['7.00', '3.00']),
  ];

  const { rows, series } = spendingChart(spending(months, groups, ['12.50', '0.00']));

  expect(series.map((item) => item.label)).toEqual([
    'Rent',
    'Food',
    'Car',
    'Health',
    'Gifts',
    'Fun',
    'Other',
    'Uncategorized',
  ]);
  expect(series[0]?.color).toBe('var(--chart-1)');
  expect(series[5]?.color).toBe('var(--chart-6)');
  expect(series[6]?.color).toBe('var(--chart-other)');
  expect(rows).toHaveLength(2);
  expect(rows[0]).toMatchObject({ label: 'Aug', group0: 500, group1: 300, uncategorized: 12.5 });
  // Pets + Tech: 5 + 7, then 5 + 3.
  expect(rows[0]?.other).toBe(12);
  expect(rows[1]?.other).toBe(8);
});

test('leaves out series that are empty', () => {
  const groups = [spendingGroup('g1', 'Food', ['10.00', '20.00'])];

  const { series } = spendingChart(spending(months, groups, ['0.00', '0.00']));

  expect(series.map((item) => item.label)).toEqual(['Food']);
  expect(spendingChart(spending(months, [], ['0.00', '0.00'])).series).toEqual([]);
});

test('turns cash flow into rows of numbers', () => {
  const rows = cashFlowRows(cashFlow([['2026-10-01', '2500.00', '1234.50']]));

  expect(rows).toEqual([
    { month: '2026-10-01', label: 'Oct', income: 2500, spending: 1234.5, net: 1265.5 },
  ]);
});

test('compares net worth with the last point at least 30 days back', () => {
  const points = netWorth([
    ['2026-08-01', '900.00'],
    ['2026-09-21', '950.00'], // 31 days before the last
    ['2026-09-23', '990.00'], // 29 days: too recent
    ['2026-10-22', '1000.00'],
  ]).points;

  expect(netWorthChange(points)).toEqual({ amount: 50, days: 31 });
});

test('compares with the first point when the history is shorter, and not at all with one', () => {
  const points = netWorth([
    ['2026-10-12', '500.00'],
    ['2026-10-22', '450.00'],
  ]).points;

  expect(netWorthChange(points)).toEqual({ amount: -50, days: 10 });
  expect(netWorthChange(points.slice(1))).toBeNull();
  expect(netWorthChange([])).toBeNull();
});

test('picks a few evenly spread dates to label an axis', () => {
  const points = netWorth(
    Array.from({ length: 9 }, (_, day) => [`2026-10-0${day + 1}`, '1.00'] as [string, string]),
  ).points;

  expect(axisTicks(points)).toEqual([
    '2026-10-01',
    '2026-10-03',
    '2026-10-05',
    '2026-10-07',
    '2026-10-09',
  ]);
  expect(axisTicks(points.slice(0, 2))).toEqual(['2026-10-01', '2026-10-02']);
  expect(axisTicks(points.slice(0, 1))).toEqual(['2026-10-01']);
  expect(axisTicks([])).toEqual([]);
});
