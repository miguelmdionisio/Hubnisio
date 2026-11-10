/** "7h 18", from minutes. */
export function hm(minutes: number): string {
  const total = Math.round(Math.abs(minutes));
  return `${Math.floor(total / 60)}h ${String(total % 60).padStart(2, '0')}`;
}

/** "7h 18", from seconds. */
export const hmSeconds = (seconds: number) => hm(seconds / 60);

/** "23:41", from minutes since midnight (negative before it, past 1440 the day after). */
export function clock(minutes: number): string {
  const wrapped = ((Math.round(minutes) % 1440) + 1440) % 1440;
  return `${String(Math.floor(wrapped / 60)).padStart(2, '0')}:${String(wrapped % 60).padStart(2, '0')}`;
}

export const STAGE_COLORS = {
  deep: 'var(--sleep-deep)',
  light: 'var(--sleep-light)',
  rem: 'var(--sleep-rem)',
  awake: 'var(--sleep-awake)',
} as const;

export const STAGE_NAMES = { deep: 'Deep', light: 'Light', rem: 'REM', awake: 'Awake' } as const;

export const WEEKDAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'] as const;
