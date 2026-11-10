import type { Recovery } from '@/api/types.gen';

/** Invented values: 30 days to 2026-11-10, a night without HRV, one below the range. */
const DAYS = Array.from({ length: 30 }, (_, index) => {
  const date = new Date(Date.UTC(2026, 10, 10 - (29 - index)));
  return date.toISOString().slice(0, 10);
});
const last = DAYS.length - 1;

export function recovery(overrides: Partial<Recovery> = {}): Recovery {
  return {
    days: 30,
    first_day: DAYS[0] ?? '',
    last_day: DAYS[last] ?? '',
    hrv: {
      points: DAYS.map((day, index) => ({
        day,
        value: index === 10 ? null : index === last - 2 ? 38 : 55 + (index % 3),
        avg7: 56,
        band_low: 52,
        band_high: 66,
        below: index === last - 2,
      })),
      summary: {
        avg7: 58,
        band_low: 52,
        band_high: 66,
        position: 'in',
        below_nights: 1,
        swing: 6.2,
        swing_90: 7.1,
        nights: 29,
      },
    },
    resting_hr: {
      points: DAYS.map((day, index) => ({ day, value: index === 5 ? null : 46, avg7: 48 })),
      summary: { latest: 46, avg7: 48, change: -2, average: 47.3 },
    },
    body_battery: {
      points: DAYS.map((day) => ({ day, at_wake: 82, charged: 61, drained: 55 })),
      summary: { at_wake: 82, charged: 61, day: DAYS[last] ?? null },
    },
    stress: {
      points: DAYS.map((day) => ({
        day,
        rest_min: 300,
        low_min: 200,
        medium_min: 60,
        high_min: 41,
        avg: 27,
      })),
      summary: { avg: 27, high_min: 41 },
    },
    signals: {
      items: [
        {
          key: 'hrv',
          state: 'ok',
          value: 58,
          reference_low: 52,
          reference_high: 66,
          day: DAYS[last] ?? null,
        },
        {
          key: 'resting_hr',
          state: 'ok',
          value: 46,
          reference_low: 48,
          reference_high: 51,
          day: DAYS[last] ?? null,
        },
        {
          key: 'sleep',
          state: 'watch',
          value: 400,
          reference_low: 416.5,
          reference_high: 490,
          day: DAYS[last] ?? null,
        },
        {
          key: 'body_battery',
          state: 'ok',
          value: 82,
          reference_low: 60,
          reference_high: null,
          day: DAYS[last] ?? null,
        },
      ],
      ok: 3,
      total: 4,
    },
    ...overrides,
  };
}
