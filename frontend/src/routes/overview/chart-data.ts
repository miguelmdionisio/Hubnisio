import type { CashFlow, NetWorthPoint, Spending } from '@/api/types.gen';
import { formatMonthName, parseDate } from '@/lib/format';

/** Chart rows hold numbers: the API's decimal strings are only ever shown, never summed. */
export type Row = Record<string, string | number>;

export type Series = { key: string; label: string; color: string };

const sum = (amounts: string[]) => amounts.reduce((total, amount) => total + Number(amount), 0);

const TOP_GROUPS = 6; // as many as there are `--chart-N` colours

/**
 * Stacked monthly bars: the biggest spending groups over the whole period, "Other" for the
 * rest, and "Uncategorized". A series that is zero throughout is left out.
 */
export function spendingChart(
  spending: Spending,
  topGroups = TOP_GROUPS,
): { rows: Row[]; series: Series[] } {
  const ranked = spending.groups
    .map((group) => ({ group, total: sum(group.amounts) }))
    .sort((a, b) => b.total - a.total);
  const top = ranked.slice(0, topGroups).map(({ group }) => group);
  const rest = ranked.slice(topGroups).map(({ group }) => group);

  const series: Series[] = top.map((group, index) => ({
    key: `group${index}`,
    label: group.name,
    color: `var(--chart-${index + 1})`,
  }));
  if (rest.length > 0 && sum(rest.flatMap((group) => group.amounts)) !== 0) {
    series.push({ key: 'other', label: 'Other', color: 'var(--chart-other)' });
  }
  if (sum(spending.uncategorized) !== 0) {
    series.push({
      key: 'uncategorized',
      label: 'Uncategorized',
      color: 'var(--chart-uncategorized)',
    });
  }

  const rows = spending.months.map((month, index): Row => {
    const row: Row = { month, label: formatMonthName(month) };
    top.forEach((group, position) => {
      row[`group${position}`] = Number(group.amounts[index] ?? 0);
    });
    row.other = rest.reduce((total, group) => total + Number(group.amounts[index] ?? 0), 0);
    row.uncategorized = Number(spending.uncategorized[index] ?? 0);
    return row;
  });
  return { rows, series };
}

/** The scope that holds the groups beyond the biggest few: pass it to `donutSlices` to see them. */
export const OTHER = 'other';

export type DonutSlice = {
  key: string; // names the slice in the chart's config
  kind: 'group' | 'category' | 'remainder' | 'other' | 'uncategorized';
  id: string | null; // a category or group; null for "Other" and "Uncategorized"
  label: string;
  amount: number;
  share: number; // of the ring, from 0 to 1
  color: string;
  into: string | null; // the scope to pass to `donutSlices` to drill in; null when there's nothing below
};

/** A group or category that is net negative (refunds above spending): it can't be drawn. */
export type LeftOut = { label: string; amount: number };

type Drawn = Omit<DonutSlice, 'key' | 'share'>;

const toCents = (amount: number) => Math.round(amount * 100) / 100;

/**
 * One month's spending as a donut, from a `Spending` of that month (its last, when there are
 * more). With no scope, the ring is the groups with spending, biggest first: the first six
 * coloured as in `spendingChart`, the rest folded into "Other", then "Uncategorized". Pass a
 * group to see its categories, or `OTHER` to see the groups folded into it.
 *
 * Anything net negative is returned in `leftOut` instead. `total` is what the ring stands for:
 * the month's spending, uncategorized and negatives included (cash flow's figure), or the
 * scope's own.
 */
export function donutSlices(
  spending: Spending,
  scope?: string,
): { slices: DonutSlice[]; total: number; leftOut: LeftOut[] } {
  const last = spending.months.length - 1;
  const at = (amounts: string[]) => Number(amounts[last] ?? 0);
  const leftOut: LeftOut[] = [];

  const finish = (drawn: Drawn[], total: number) => {
    const ring = drawn.reduce((all, slice) => all + slice.amount, 0);
    const slices = drawn.map((slice, index) => ({
      ...slice,
      key: `slice${index}`,
      share: ring === 0 ? 0 : slice.amount / ring,
    }));
    return { slices, total: toCents(total), leftOut };
  };
  // Inside a group, or "Other", there can be more slices than colours: they cycle.
  const cycled = (index: number) => `var(--chart-${(index % TOP_GROUPS) + 1})`;

  const groups = spending.groups
    .map((group) => ({ group, amount: at(group.amounts) }))
    .sort((a, b) => b.amount - a.amount);
  const groupSlice = ({ group, amount }: (typeof groups)[number], color: string): Drawn => ({
    kind: 'group',
    id: group.id,
    label: group.name,
    amount,
    color,
    into: group.categories.length > 0 ? group.id : null,
  });
  const positive = groups.filter(({ amount }) => amount > 0);

  if (scope === OTHER) {
    const rest = positive.slice(TOP_GROUPS);
    return finish(
      rest.map((item, index) => groupSlice(item, cycled(index))),
      rest.reduce((all, item) => all + item.amount, 0),
    );
  }

  if (scope !== undefined) {
    const found = groups.find(({ group }) => group.id === scope);
    if (!found) return finish([], 0);
    const categories = found.group.categories.map((category) => ({
      category,
      amount: at(category.amounts),
    }));
    const drawn: Drawn[] = [];
    for (const { category, amount } of categories.sort((a, b) => b.amount - a.amount)) {
      if (amount < 0) leftOut.push({ label: category.name, amount });
      if (amount <= 0) continue;
      drawn.push({
        kind: 'category',
        id: category.id,
        label: category.name,
        amount,
        color: cycled(drawn.length),
        into: null,
      });
    }
    // What the group holds beyond its categories was assigned to the group itself.
    const remainder = toCents(
      found.amount - categories.reduce((all, item) => all + item.amount, 0),
    );
    const label = `${found.group.name} (no subcategory)`;
    if (remainder < 0) leftOut.push({ label, amount: remainder });
    if (remainder > 0) {
      drawn.push({
        kind: 'remainder',
        id: found.group.id,
        label,
        amount: remainder,
        color: 'var(--chart-other)',
        into: null,
      });
    }
    return finish(drawn, found.amount);
  }

  for (const { group, amount } of groups) {
    if (amount < 0) leftOut.push({ label: group.name, amount });
  }
  const drawn = positive
    .slice(0, TOP_GROUPS)
    .map((item, index) => groupSlice(item, `var(--chart-${index + 1})`));
  const rest = positive.slice(TOP_GROUPS);
  if (rest.length > 0) {
    drawn.push({
      kind: 'other',
      id: null,
      label: 'Other',
      amount: rest.reduce((all, item) => all + item.amount, 0),
      color: 'var(--chart-other)',
      into: OTHER,
    });
  }
  const uncategorized = at(spending.uncategorized);
  if (uncategorized < 0) leftOut.push({ label: 'Uncategorized', amount: uncategorized });
  if (uncategorized > 0) {
    drawn.push({
      kind: 'uncategorized',
      id: null,
      label: 'Uncategorized',
      amount: uncategorized,
      color: 'var(--chart-uncategorized)',
      into: null,
    });
  }
  return finish(
    drawn,
    groups.reduce((all, item) => all + item.amount, uncategorized),
  );
}

export function cashFlowRows(cashFlow: CashFlow): Row[] {
  return cashFlow.months.map((month) => ({
    month: month.month,
    label: formatMonthName(month.month),
    income: Number(month.income),
    spending: Number(month.spending),
    net: Number(month.net),
  }));
}

const DAY = 86_400_000;

/** Whole days from one calendar date ("2026-10-14") to a later one. */
function daysBetween(from: string, to: string): number {
  return Math.round((parseDate(to).getTime() - parseDate(from).getTime()) / DAY);
}

/**
 * How net worth moved over the last `days` days: against the last point at least that far
 * back, or the first point when the history is shorter. Null when there's nothing to compare.
 */
export function netWorthChange(
  points: NetWorthPoint[],
  days = 30,
): { amount: number; days: number } | null {
  const last = points.at(-1);
  if (!last) return null;
  const base = points.findLast((point) => daysBetween(point.on, last.on) >= days) ?? points[0];
  if (!base) return null;
  const span = daysBetween(base.on, last.on);
  if (span <= 0) return null;
  return { amount: Number(last.amount) - Number(base.amount), days: span };
}

/** A few evenly spread dates to label a time axis with. */
export function axisTicks(points: NetWorthPoint[], count = 5): string[] {
  if (points.length === 0) return [];
  const steps = Math.min(count, points.length) - 1;
  const ticks = Array.from({ length: steps + 1 }, (_, step) => {
    const index = steps === 0 ? 0 : Math.round((step * (points.length - 1)) / steps);
    return (points[index] as NetWorthPoint).on;
  });
  return [...new Set(ticks)];
}
