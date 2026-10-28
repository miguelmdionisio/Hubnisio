import { expect, test } from 'vitest';
import { cashFlow, netWorth, spending, spendingCategory, spendingGroup } from '@/test/fixtures';
import {
  axisTicks,
  cashFlowRows,
  donutSlices,
  netWorthChange,
  OTHER,
  spendingChart,
} from './chart-data';

const months = ['2026-08-01', '2026-10-01'];

test('stacks the five biggest groups, then Other, then Uncategorized', () => {
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
    'Other',
    'Uncategorized',
  ]);
  expect(series[0]?.color).toBe('var(--chart-1)');
  expect(series[4]?.color).toBe('var(--chart-5)');
  expect(series[5]?.color).toBe('var(--chart-other)');
  expect(rows).toHaveLength(2);
  expect(rows[0]).toMatchObject({ label: 'Aug', group0: 500, group1: 300, uncategorized: 12.5 });
  // Fun + Pets + Tech: 10 + 5 + 7, then 10 + 5 + 3.
  expect(rows[0]?.other).toBe(22);
  expect(rows[1]?.other).toBe(18);
});

test('keeps a group that nets below zero negative, and ranks groups by size either way', () => {
  const groups = [
    spendingGroup('g1', 'Food', ['100.00', '120.00']),
    spendingGroup('g2', 'Housing', ['600.00', '-300.00']),
  ];

  const { rows, series } = spendingChart(spending(months, groups, ['0.00', '0.00']));

  expect(series.map((item) => item.label)).toEqual(['Housing', 'Food']);
  expect(rows[0]).toMatchObject({ group0: 600, group1: 100 });
  // Housing dips below zero while Food stacks above it (the chart's `stackOffset="sign"`).
  expect(rows[1]).toMatchObject({ group0: -300, group1: 120 });

  const folded = spendingChart(spending(months, groups, ['0.00', '0.00']), 1);
  expect(folded.series.map((item) => item.label)).toEqual(['Housing', 'Other']);
  expect(folded.rows[1]).toMatchObject({ group0: -300, other: 120 });
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

const october = ['2026-10-01'];

/** Eight groups for one month: six big ones, then Tech and Pets. */
function eightGroups() {
  return [
    spendingGroup('g1', 'Fun', ['10.00']),
    spendingGroup('g2', 'Rent', ['500.00']),
    spendingGroup('g3', 'Food', ['300.00']),
    spendingGroup('g4', 'Car', ['100.00']),
    spendingGroup('g5', 'Health', ['40.00']),
    spendingGroup('g6', 'Gifts', ['90.00']),
    spendingGroup('g7', 'Pets', ['5.00']),
    spendingGroup('g8', 'Tech', ['7.00']),
  ];
}

test('donut: the groups biggest first, then Other, then Uncategorized', () => {
  const { slices, total, leftOut } = donutSlices(spending(october, eightGroups(), ['48.00']));

  expect(slices.map((slice) => [slice.label, slice.kind, slice.amount, slice.color])).toEqual([
    ['Rent', 'group', 500, 'var(--chart-1)'],
    ['Food', 'group', 300, 'var(--chart-2)'],
    ['Car', 'group', 100, 'var(--chart-3)'],
    ['Gifts', 'group', 90, 'var(--chart-4)'],
    ['Health', 'group', 40, 'var(--chart-5)'],
    ['Fun', 'group', 10, 'var(--chart-6)'],
    ['Other', 'other', 12, 'var(--chart-other)'], // Tech and Pets
    ['Uncategorized', 'uncategorized', 48, 'var(--chart-uncategorized)'],
  ]);
  // The centre is the whole month, as cash flow's spending is.
  expect(total).toBe(1100);
  expect(slices[0]?.share).toBeCloseTo(500 / 1100);
  expect(slices.reduce((all, slice) => all + slice.share, 0)).toBeCloseTo(1);
  expect(leftOut).toEqual([]);
});

test('donut: shows Uncategorized as its own slice, however big', () => {
  const groups = [spendingGroup('g1', 'Food', ['100.00'])];

  const { slices, total } = donutSlices(spending(october, groups, ['400.00']));

  expect(slices.map((slice) => [slice.label, slice.share])).toEqual([
    ['Food', 0.2],
    ['Uncategorized', 0.8],
  ]);
  expect(total).toBe(500);
});

test('donut: leaves out what is empty or net negative, and returns the negatives', () => {
  const groups = [
    spendingGroup('g1', 'Food', ['300.00']),
    spendingGroup('g2', 'Gifts', ['0.00']),
    spendingGroup('g3', 'Tech', ['-40.00']),
  ];

  const { slices, total, leftOut } = donutSlices(spending(october, groups, ['-10.00']));

  expect(slices.map((slice) => slice.label)).toEqual(['Food']);
  expect(leftOut).toEqual([
    { label: 'Tech', amount: -40 },
    { label: 'Uncategorized', amount: -10 },
  ]);
  // The true total still counts the refunds: 300 - 40 - 10.
  expect(total).toBe(250);
});

test('donut: has nothing to draw in a month without spending', () => {
  expect(donutSlices(spending(october, [], ['0.00']))).toEqual({
    slices: [],
    total: 0,
    leftOut: [],
  });
});

test('donut: reads the last month of the spending it is given', () => {
  const groups = [spendingGroup('g1', 'Food', ['300.00', '120.00'])];

  const { slices, total } = donutSlices(
    spending(['2026-09-01', '2026-10-01'], groups, ['5.00', '0.00']),
  );

  expect(slices.map((slice) => slice.amount)).toEqual([120]);
  expect(total).toBe(120);
});

test('donut: drills into a group, with what was assigned to the group itself', () => {
  const food = spendingGroup(
    'g-food',
    'Food',
    ['300.00'],
    [
      spendingCategory('c-dining', 'Dining out', ['95.50']),
      spendingCategory('c-groceries', 'Groceries', ['180.00']),
    ],
  );
  const data = spending(october, [food, spendingGroup('g-rent', 'Rent', ['500.00'])], ['0.00']);

  const top = donutSlices(data);
  expect(top.slices.map((slice) => [slice.label, slice.into])).toEqual([
    ['Rent', null], // nothing below it to drill into
    ['Food', 'g-food'],
  ]);

  const { slices, total, leftOut } = donutSlices(data, 'g-food');

  expect(
    slices.map((slice) => [slice.label, slice.kind, slice.id, slice.amount, slice.color]),
  ).toEqual([
    ['Groceries', 'category', 'c-groceries', 180, 'var(--chart-1)'],
    ['Dining out', 'category', 'c-dining', 95.5, 'var(--chart-2)'],
    ['Food (no subcategory)', 'remainder', 'g-food', 24.5, 'var(--chart-other)'],
  ]);
  expect(slices.every((slice) => slice.into === null)).toBe(true);
  expect(total).toBe(300);
  expect(leftOut).toEqual([]);
});

test('donut: has no remainder when the categories add up to the group', () => {
  const food = spendingGroup(
    'g-food',
    'Food',
    ['100.10'],
    [
      spendingCategory('c-a', 'Groceries', ['60.07']),
      spendingCategory('c-b', 'Dining out', ['40.03']),
    ],
  );

  const { slices } = donutSlices(spending(october, [food], ['0.00']), 'g-food');

  expect(slices.map((slice) => slice.label)).toEqual(['Groceries', 'Dining out']);
});

test('donut: leaves out a net-negative category, and a negative remainder', () => {
  const food = spendingGroup(
    'g-food',
    'Food',
    ['130.00'],
    [
      spendingCategory('c-groceries', 'Groceries', ['150.00']),
      spendingCategory('c-dining', 'Dining out', ['-20.00']), // refunds above spending
    ],
  );
  // The group holds 10 less than its category: refunds assigned to the group itself.
  const odd = spendingGroup(
    'g-odd',
    'Odd',
    ['90.00'],
    [spendingCategory('c-odd', 'Odd jobs', ['100.00'])],
  );
  const data = spending(october, [food, odd], ['0.00']);

  const inFood = donutSlices(data, 'g-food');
  expect(inFood.slices.map((slice) => slice.label)).toEqual(['Groceries']);
  expect(inFood.leftOut).toEqual([{ label: 'Dining out', amount: -20 }]);
  expect(inFood.total).toBe(130);

  const inOdd = donutSlices(data, 'g-odd');
  expect(inOdd.slices.map((slice) => slice.label)).toEqual(['Odd jobs']);
  expect(inOdd.leftOut).toEqual([{ label: 'Odd (no subcategory)', amount: -10 }]);
});

test('donut: drills into Other for the groups folded into it', () => {
  const groups = eightGroups();
  groups[6] = spendingGroup('g7', 'Pets', ['5.00'], [spendingCategory('c-vet', 'Vet', ['5.00'])]);
  const data = spending(october, groups, ['48.00']);

  expect(donutSlices(data).slices.find((slice) => slice.kind === 'other')?.into).toBe(OTHER);

  const { slices, total, leftOut } = donutSlices(data, OTHER);

  expect(slices.map((slice) => [slice.label, slice.amount, slice.into, slice.color])).toEqual([
    ['Tech', 7, null, 'var(--chart-1)'],
    ['Pets', 5, 'g7', 'var(--chart-2)'], // with categories, so it can be drilled into in turn
  ]);
  expect(total).toBe(12);
  expect(leftOut).toEqual([]);
});

test('donut: has nothing for a group that is not in the month', () => {
  const data = spending(october, [spendingGroup('g1', 'Food', ['10.00'])], ['0.00']);

  expect(donutSlices(data, 'gone')).toEqual({ slices: [], total: 0, leftOut: [] });
  expect(donutSlices(data, OTHER)).toEqual({ slices: [], total: 0, leftOut: [] });
});
