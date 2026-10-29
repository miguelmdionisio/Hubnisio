import type { NetWorthPoint } from '@/api/types.gen';
import { parseDate } from '@/lib/format';

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
export function axisTicks(points: { on: string }[], count = 5): string[] {
  if (points.length === 0) return [];
  const steps = Math.min(count, points.length) - 1;
  const ticks = Array.from({ length: steps + 1 }, (_, step) => {
    const index = steps === 0 ? 0 : Math.round((step * (points.length - 1)) / steps);
    return (points[index] as { on: string }).on;
  });
  return [...new Set(ticks)];
}
