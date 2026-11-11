import type { Group } from './sport';

/** The list's URL: a sport, a period and a search; each missing when it doesn't narrow. */
export type ActivitiesSearch = { sport?: Group; period?: Period; q?: string };

export const PERIODS = [
  { value: 'all', label: 'Any time' },
  { value: '30', label: 'Last 30 days' },
  { value: '90', label: 'Last 90 days' },
  { value: 'year', label: 'This year' },
  { value: 'last-year', label: 'Last year' },
] as const;

export type Period = (typeof PERIODS)[number]['value'];

export const SPORT_PILLS: { value: Group | undefined; label: string }[] = [
  { value: undefined, label: 'All' },
  { value: 'swim', label: 'Swim' },
  { value: 'bike', label: 'Bike' },
  { value: 'run', label: 'Run' },
  { value: 'strength', label: 'Strength' },
  { value: 'other', label: 'Other' },
];

export function validateActivitiesSearch(search: Record<string, unknown>): ActivitiesSearch {
  const sport = SPORT_PILLS.find((pill) => pill.value && pill.value === search.sport)?.value;
  const period = PERIODS.find((p) => p.value !== 'all' && p.value === search.period)?.value;
  return { sport, period, q: typeof search.q === 'string' && search.q ? search.q : undefined };
}

const iso = (date: Date) =>
  `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`;

/** The first and last day a period covers, as the API takes them; none for any time. */
export function periodRange(
  period: Period | undefined,
  today = new Date(),
): { from?: string; to?: string } {
  const back = (days: number) => {
    const start = new Date(today);
    start.setDate(start.getDate() - days);
    return iso(start);
  };
  switch (period) {
    case '30':
      return { from: back(30) };
    case '90':
      return { from: back(90) };
    case 'year':
      return { from: `${today.getFullYear()}-01-01` };
    case 'last-year':
      return { from: `${today.getFullYear() - 1}-01-01`, to: `${today.getFullYear() - 1}-12-31` };
    default:
      return {};
  }
}
