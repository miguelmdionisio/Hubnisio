/**
 * Display formatting. The UI is in English, so every format uses one locale: dates, numbers
 * and phrases like "5 minutes ago" then match the words around them, whatever the browser's
 * language. Change it here.
 */
export const LOCALE = 'en-GB';

export function formatMoney(amount: string | number, currency: string, locale = LOCALE): string {
  return new Intl.NumberFormat(locale, { style: 'currency', currency }).format(Number(amount));
}

/** For chart axes: "€1.2k". */
export function formatCompactMoney(
  amount: string | number,
  currency: string,
  locale = LOCALE,
): string {
  return new Intl.NumberFormat(locale, {
    style: 'currency',
    currency,
    notation: 'compact',
    maximumFractionDigits: 1,
  }).format(Number(amount));
}

/** A calendar date ("2026-10-14") as a local date, so no timezone can shift it a day. */
export function parseDate(isoDate: string): Date {
  const [year = 1970, month = 1, day = 1] = isoDate.split('-').map(Number);
  return new Date(year, month - 1, day);
}

export function formatDate(isoDate: string, locale = LOCALE): string {
  return new Intl.DateTimeFormat(locale, {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
  }).format(parseDate(isoDate));
}

/** "October 2026", from a month ("2026-10") or any date in it. */
export function formatMonth(isoMonth: string, locale = LOCALE): string {
  return new Intl.DateTimeFormat(locale, { month: 'long', year: 'numeric' }).format(
    parseDate(isoMonth),
  );
}

/** "Oct", from a month ("2026-10") or any date in it. */
export function formatMonthName(isoMonth: string, locale = LOCALE): string {
  return new Intl.DateTimeFormat(locale, { month: 'short' }).format(parseDate(isoMonth));
}

/** "Mar 2026", from a date. */
export function formatShortMonth(isoDate: string, locale = LOCALE): string {
  return new Intl.DateTimeFormat(locale, { month: 'short', year: 'numeric' }).format(
    parseDate(isoDate),
  );
}

const UNITS: [Intl.RelativeTimeFormatUnit, number][] = [
  ['day', 86_400],
  ['hour', 3_600],
  ['minute', 60],
];

/** "5 minutes ago", "yesterday", "just now". */
export function formatRelative(isoDateTime: string, now = Date.now(), locale = LOCALE): string {
  const seconds = (Date.parse(isoDateTime) - now) / 1000;
  const format = new Intl.RelativeTimeFormat(locale, { numeric: 'auto' });
  for (const [unit, size] of UNITS) {
    if (Math.abs(seconds) >= size) return format.format(Math.round(seconds / size), unit);
  }
  return format.format(0, 'second');
}
