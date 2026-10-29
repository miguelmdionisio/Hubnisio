import { expect, test } from 'vitest';
import { netWorth } from '@/test/fixtures';
import { axisTicks, netWorthChange } from './chart-data';

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
