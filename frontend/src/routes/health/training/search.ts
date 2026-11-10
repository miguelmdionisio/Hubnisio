/** Training's URL: the period it covers; 90 days when missing. */
export type Period = '90' | '180' | '365' | 'all';
export type TrainingSearch = { days?: Exclude<Period, '90'> };

export function validateTrainingSearch(search: Record<string, unknown>): TrainingSearch {
  const days = String(search.days);
  return { days: days === '180' || days === '365' || days === 'all' ? days : undefined };
}

export function periodOf(search: TrainingSearch): Period {
  return search.days ?? '90';
}
