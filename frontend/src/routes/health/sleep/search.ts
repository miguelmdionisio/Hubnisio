/** The Sleep page's URL: which night (the latest when missing) and how many nights of trend. */
export type SleepSearch = {
  date?: string; // "YYYY-MM-DD", the day the night ends
  nights?: 90 | 365; // 30 when missing
};

export function validateSleepSearch(search: Record<string, unknown>): SleepSearch {
  const nights = Number(search.nights);
  return {
    date:
      typeof search.date === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(search.date)
        ? search.date
        : undefined,
    nights: nights === 90 || nights === 365 ? nights : undefined,
  };
}
