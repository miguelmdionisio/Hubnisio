import type { HealthConnection } from '@/api/types.gen';

/** The date `days` from today, as the API sends one ("2026-11-10"). */
export function inDays(days: number): string {
  const date = new Date();
  date.setDate(date.getDate() + days);
  return [
    date.getFullYear(),
    String(date.getMonth() + 1).padStart(2, '0'),
    String(date.getDate()).padStart(2, '0'),
  ].join('-');
}

/** A linked watch with invented counts and ranges; the key lapses in 200 days. */
export function connection(overrides: Partial<HealthConnection> = {}): HealthConnection {
  return {
    linked: true,
    provider: 'garmin',
    status: 'active',
    key_expires_on: inDays(200),
    key_expires_soon: false,
    last_synced_at: new Date(Date.now() - 2 * 3_600_000).toISOString(),
    last_run: {
      trigger: 'scheduled',
      status: 'succeeded',
      error_code: null,
      skipped: [],
      started_at: new Date(Date.now() - 2 * 3_600_000).toISOString(),
      finished_at: new Date(Date.now() - 2 * 3_600_000 + 60_000).toISOString(),
    },
    synced_through: { sleep: '2026-11-10' },
    counts: { daily_summaries: 280, sleeps: 262, 'samples.heart_rate': 41_300, weights: 3 },
    ranges: {
      daily_summaries: { first: '2026-02-01', last: '2026-11-10' },
      sleeps: { first: '2026-02-03', last: '2026-11-10' },
      'samples.heart_rate': { first: '2026-10-01', last: '2026-11-10' },
      weights: { first: '2026-03-04', last: '2026-10-20' },
    },
    syncing: false,
    ...overrides,
  };
}
