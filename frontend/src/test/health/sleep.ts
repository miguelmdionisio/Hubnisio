import type { NightOut, NightPointOut, ReadingOut, SleepNight, SleepTrends } from '@/api/types.gen';

const empty: ReadingOut = {
  avg: null,
  low: null,
  low_at: null,
  high: null,
  high_at: null,
  series: [],
};

/** Invented: a night ending Tuesday 10 Nov 2026, in bed 23:41 to 07:17. */
export const night: NightOut = {
  day: '2026-11-10',
  started_at: '2026-11-09T23:41:00',
  ended_at: '2026-11-10T07:17:00',
  bed_min: -19,
  wake_min: 437,
  score: 84,
  score_qualifier: 'GOOD',
  score_vs_baseline: 6,
  slept_s: 26400,
  need_minutes: 490,
  in_bed_s: 27360,
  awake_count: 2,
  stages: [
    { stage: 'deep', seconds: 4800, share: 0.18, typical_low: 0.15, typical_high: 0.2 },
    { stage: 'light', seconds: 14400, share: 0.53, typical_low: 0.45, typical_high: 0.55 },
    { stage: 'rem', seconds: 6000, share: 0.22, typical_low: 0.2, typical_high: 0.25 },
    { stage: 'awake', seconds: 1800, share: 0.07, typical_low: null, typical_high: null },
  ],
  average_slept_minutes: 438,
  debt: { nights: 7, missing: 0, need_minutes: 3430, slept_minutes: 3230, debt_minutes: 200 },
  heart_rate: {
    avg: 47,
    low: 42,
    low_at: 270,
    high: 56,
    high_at: 10,
    series: [
      { t: 10, v: 56 },
      { t: 130, v: 48 },
      { t: 270, v: 42 },
      { t: 400, v: 50 },
    ],
  },
  hrv: {
    avg: 58,
    low: null,
    low_at: null,
    high: 81,
    high_at: 250,
    series: [
      { t: 60, v: 52 },
      { t: 250, v: 81 },
    ],
  },
  respiration: { ...empty, avg: 14.2, low: 12, high: 17 },
  spo2: {
    avg: 95,
    low: 89,
    low_at: 200,
    high: 97,
    high_at: 60,
    series: [
      { t: 60, v: 97 },
      { t: 200, v: 89 },
    ],
  },
};

export function sleepNight(overrides: Partial<SleepNight> = {}): SleepNight {
  return {
    day: '2026-11-10',
    night,
    previous_day: '2026-11-08',
    next_day: null,
    ...overrides,
  };
}

/** Thirty days ending 10 Nov, the 3rd and 4th from the end not worn. */
export function sleepTrends(overrides: Partial<SleepTrends> = {}): SleepTrends {
  const points: NightPointOut[] = Array.from({ length: 30 }, (_, index) => {
    const date = new Date(Date.UTC(2026, 9, 12 + index));
    const day = date.toISOString().slice(0, 10);
    const worn = index < 26 || index > 27;
    return worn
      ? {
          day,
          worn,
          slept_s: 25200 + (index % 5) * 1200,
          deep_s: 4500,
          light_s: 14000,
          rem_s: 5400,
          awake_s: 1500,
          need_minutes: 490,
          score: 70 + (index % 10),
          bed_min: -30 + (index % 4) * 10,
          wake_min: 420 + (index % 3) * 10,
        }
      : {
          day,
          worn,
          slept_s: null,
          deep_s: null,
          light_s: null,
          rem_s: null,
          awake_s: null,
          need_minutes: null,
          score: null,
          bed_min: null,
          wake_min: null,
        };
  });
  return {
    nights: 30,
    start: '2026-10-12',
    end: '2026-11-10',
    points,
    nights_worn: 28,
    average_slept_minutes: 438,
    average_need_minutes: 490,
    schedule: {
      nights: 28,
      bed_avg: -15,
      bed_sd: 34.4,
      wake_avg: 425,
      wake_sd: 22.2,
      weekday_bed_avg: -20,
      weekday_wake_avg: 420,
      weekend_bed_avg: 0,
      weekend_wake_avg: 440,
    },
    correlation: {
      pairs: [],
      slope: null,
      intercept: null,
      r: null,
    },
    weekday_scores: [82, 80, 79, 81, 76, 72, 85].map((score, weekday) => ({
      weekday,
      nights: 4,
      score,
    })),
    ...overrides,
  };
}

export function correlated(): SleepTrends['correlation'] {
  const pairs = Array.from({ length: 24 }, (_, index) => ({
    day: `2026-10-${String(1 + index).padStart(2, '0')}`,
    hours: 6 + index / 10,
    hrv: 50 + index,
  }));
  return { pairs, slope: 10, intercept: -10, r: 0.62 };
}
