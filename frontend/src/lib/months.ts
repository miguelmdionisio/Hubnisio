/** A calendar month as "YYYY-MM": the unit budgets and their month picker work in. */
const MONTH = /^\d{4}-(0[1-9]|1[0-2])$/;

export function isMonth(value: unknown): value is string {
  return typeof value === 'string' && MONTH.test(value);
}

/** The month a local date falls in. */
export function toMonth(date: Date): string {
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}`;
}

export function currentMonth(): string {
  return toMonth(new Date());
}

/** The month `delta` months after (or, if negative, before) `month`. */
export function shiftMonth(month: string, delta: number): string {
  const [year = 1970, number = 1] = month.split('-').map(Number);
  return toMonth(new Date(year, number - 1 + delta, 1));
}

/** The API takes a day: the first of the month. */
export function monthStart(month: string): string {
  return `${month}-01`;
}
