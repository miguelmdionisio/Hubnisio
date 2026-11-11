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

/** A number of shares, fractional ones included: "12.3456". */
export function formatQuantity(quantity: string | number, locale = LOCALE): string {
  return new Intl.NumberFormat(locale, { maximumFractionDigits: 6 }).format(Number(quantity));
}

/** A share of a whole, from 0 to 1: "12.3%". `signed` shows "+" on a gain. */
export function formatPercent(share: string | number, signed = false, locale = LOCALE): string {
  return new Intl.NumberFormat(locale, {
    style: 'percent',
    maximumFractionDigits: 1,
    signDisplay: signed ? 'exceptZero' : 'auto',
  }).format(Number(share));
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

/** Whole euros for big figures: "€1,234". */
export function formatWholeMoney(amount: string | number, currency: string, locale = LOCALE) {
  return new Intl.NumberFormat(locale, {
    style: 'currency',
    currency,
    maximumFractionDigits: 0,
  }).format(Number(amount));
}

/** "Wed 14 Oct", from a date. */
export function formatDay(isoDate: string, locale = LOCALE): string {
  return new Intl.DateTimeFormat(locale, {
    weekday: 'short',
    day: 'numeric',
    month: 'short',
  }).format(parseDate(isoDate));
}

/** A share of a whole as a whole percentage, "<1%" for a sliver. */
export function formatShare(share: string | number): string {
  const value = Number(share);
  const rounded = Math.round(value * 100);
  return rounded === 0 && value > 0 ? '<1%' : `${rounded}%`;
}

/** Seconds as a clock reading: "52:10", "1:52:10". */
export function formatDuration(seconds: number): string {
  const total = Math.round(seconds);
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const rest = String(total % 60).padStart(2, '0');
  return hours > 0 ? `${hours}:${String(minutes).padStart(2, '0')}:${rest}` : `${minutes}:${rest}`;
}

/** Seconds per kilometre (or per 100 m) as minutes and seconds: "5:14". */
export function formatPace(secondsPerUnit: number): string {
  const total = Math.round(secondsPerUnit);
  return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, '0')}`;
}

/** Metres: "850 m" under a kilometre, else "21.4 km". */
export function formatDistance(metres: number): string {
  if (Math.abs(metres) < 1000) return `${Math.round(metres)} m`;
  const km = new Intl.NumberFormat(LOCALE, { minimumFractionDigits: 1, maximumFractionDigits: 1 });
  return `${km.format(metres / 1000)} km`;
}
