import type { Body } from '@/api/types.gen';

/** Invented values: three weigh-ins, a goal, and three fitness-age readings, to 2026-11-10. */
export function body(overrides: Partial<Body> = {}): Body {
  return {
    days: 365,
    first_day: '2025-11-11',
    last_day: '2026-11-10',
    weight: {
      points: [
        { day: '2026-03-04', kg: 80.2, bmi: 24.6, body_fat_pct: null },
        { day: '2026-07-15', kg: 79.1, bmi: 24.3, body_fat_pct: null },
        { day: '2026-10-20', kg: 78.4, bmi: 24.1, body_fat_pct: null },
      ],
      goal_kg: 75,
      summary: {
        count: 3,
        latest_kg: 78.4,
        latest_day: '2026-10-20',
        change_kg: -1.8,
        bmi: 24.1,
        to_goal_kg: 3.4,
      },
    },
    fitness_age: {
      points: [
        { day: '2026-03-01', fitness_age: 37, chronological_age: 41 },
        { day: '2026-07-01', fitness_age: 36.5, chronological_age: 41 },
        { day: '2026-11-01', fitness_age: 35.5, chronological_age: 41 },
      ],
      latest: {
        day: '2026-11-01',
        fitness_age: 35.5,
        chronological_age: 41,
        difference: -5.5,
        resting_hr: 46,
        bmi: 24.1,
        vigorous_days_avg: 3.5,
        vigorous_minutes_avg: 210,
      },
    },
    ...overrides,
  };
}

/** Nothing stored: no weigh-ins, no goal, no fitness age. */
export function emptyBody(): Body {
  return body({
    weight: {
      points: [],
      goal_kg: null,
      summary: {
        count: 0,
        latest_kg: null,
        latest_day: null,
        change_kg: null,
        bmi: null,
        to_goal_kg: null,
      },
    },
    fitness_age: { points: [], latest: null },
  });
}

/** One weigh-in: the latest figure, no change, no chart. */
export function oneWeighIn(): Body {
  const full = body();
  const [point] = full.weight.points.slice(-1);
  return body({
    weight: {
      points: point ? [point] : [],
      goal_kg: null,
      summary: { ...full.weight.summary, count: 1, change_kg: null, to_goal_kg: null },
    },
  });
}
