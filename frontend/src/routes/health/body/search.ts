/** Body's URL: how far back it looks; a year when missing. */
export type BodySearch = { days?: '90' | 'all' };

export type Period = '90' | '365' | 'all';

export function validateBodySearch(search: Record<string, unknown>): BodySearch {
  const days = String(search.days);
  return { days: days === '90' || days === 'all' ? days : undefined };
}

export function periodOf(search: BodySearch): Period {
  return search.days ?? '365';
}
