/** "21:10" or "1:38:20", from seconds. */
export function clockTime(seconds: number): string {
  const total = Math.round(seconds);
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = String(total % 60).padStart(2, '0');
  return h > 0 ? `${h}:${String(m).padStart(2, '0')}:${s}` : `${m}:${s}`;
}

/** Seconds per km from metres per second. */
export const secondsPerKm = (speed: number) => 1000 / speed;

/** "4:10", a pace from seconds (per km or per 100 m). */
export const pace = (seconds: number) => clockTime(seconds);

/** "5 s", "1 min", "1 h": a curve's duration. */
export function durationLabel(seconds: number): string {
  if (seconds < 60) return `${seconds} s`;
  if (seconds < 3600) return `${Math.round(seconds / 60)} min`;
  const hours = seconds / 3600;
  return `${hours.toLocaleString('en-GB', { maximumFractionDigits: 1 })} h`;
}

export const number = (value: number | null | undefined, places = 0) =>
  value === null || value === undefined
    ? '–'
    : value.toLocaleString('en-GB', {
        minimumFractionDigits: places,
        maximumFractionDigits: places,
      });

/** Records and races by distance in metres. */
export const DISTANCE_NAMES: Record<string, string> = {
  '100': '100 m',
  '400': '400 m',
  '1000': '1 km',
  '1500': '1500 m',
  '5000': '5 km',
  '10000': '10 km',
  '21097': 'Half marathon',
  '42195': 'Marathon',
};
