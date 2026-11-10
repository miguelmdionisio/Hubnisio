/** Performance's URL: the period it covers; this season when missing. */
export type PerformancePeriod = 'season' | '90d' | 'all';

export type PerformanceSearch = { period?: '90d' | 'all' };

export function validatePerformanceSearch(search: Record<string, unknown>): PerformanceSearch {
  const period = search.period;
  return { period: period === '90d' || period === 'all' ? period : undefined };
}

export function periodOf(search: PerformanceSearch): PerformancePeriod {
  return search.period ?? 'season';
}
