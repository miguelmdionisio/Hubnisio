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
