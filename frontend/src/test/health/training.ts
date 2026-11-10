import type { Training } from '@/api/types.gen';

/** Invented values: 21 days to 2026-11-10, a rest day every seventh. */
const DAYS = Array.from({ length: 21 }, (_, index) => {
  const date = new Date(Date.UTC(2026, 10, 10 - (20 - index)));
  return date.toISOString().slice(0, 10);
});

export function training(overrides: Partial<Training> = {}): Training {
  return {
    period: '90',
    first_day: DAYS[0] ?? '',
    last_day: DAYS.at(-1) ?? '',
    summary: {
      fitness: 52.4,
      fatigue: 61.2,
      form: -8.6,
      band: 'neutral',
      fitness_change: 7.2,
      ramp_per_week: 2.4,
      ramp_safe: true,
    },
    points: DAYS.map((day, index) => ({
      day,
      load: index % 7 === 6 ? 0 : 70,
      fitness: 40 + index / 2,
      fatigue: 50 + (index % 5),
      form: index === 20 ? -8.6 : -10 + (index % 4) * 4,
      band: 'neutral' as const,
    })),
    weeks: [
      {
        week_start: '2026-10-26',
        swim: 1,
        bike: 3,
        run: 2,
        strength: 0.5,
        other: 0,
        partial: false,
      },
      {
        week_start: '2026-11-02',
        swim: 0,
        bike: 4.5,
        run: 2.5,
        strength: 0,
        other: 0.25,
        partial: false,
      },
      { week_start: '2026-11-09', swim: 0, bike: 0, run: 1, strength: 0, other: 0, partial: true },
    ],
    average_week_hours: 7.25,
    intensity: [
      {
        sport: 'swim',
        z12_s: 640,
        z3_s: 220,
        z45_s: 140,
        z12_share: 0.64,
        z3_share: 0.22,
        z45_share: 0.14,
      },
      {
        sport: 'run',
        z12_s: 760,
        z3_s: 120,
        z45_s: 120,
        z12_share: 0.76,
        z3_share: 0.12,
        z45_share: 0.12,
      },
      {
        sport: 'all',
        z12_s: 1400,
        z3_s: 340,
        z45_s: 260,
        z12_share: 0.7,
        z3_share: 0.17,
        z45_share: 0.13,
      },
    ],
    months: [
      {
        month: '2026-11-01',
        swim_m: 0,
        bike_m: 62000,
        run_m: 8100,
        hours: 21.67,
        load: 905,
        climb_m: 1820,
        sessions: 14,
        partial: true,
      },
      {
        month: '2026-10-01',
        swim_m: 3200,
        bike_m: 112000,
        run_m: 17600,
        hours: 58.17,
        load: 2742,
        climb_m: 6410,
        sessions: 36,
        partial: false,
      },
    ],
    ...overrides,
  };
}
