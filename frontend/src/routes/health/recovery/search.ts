/** Recovery's URL: how many days it covers; 90 when missing. */
export type RecoverySearch = { days?: 30 | 365 };

export type Days = 30 | 90 | 365;

export function validateRecoverySearch(search: Record<string, unknown>): RecoverySearch {
  const days = Number(search.days);
  return { days: days === 30 || days === 365 ? days : undefined };
}

export function daysOf(search: RecoverySearch): Days {
  return search.days ?? 90;
}
