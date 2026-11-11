import type { Today } from '@/api/types.gen';
import { recovery } from './recovery';

/** Invented values: the 90 days to 2026-11-10, a rest day every seventh, one night's gap. */
const day = (offset: number) =>
  new Date(Date.UTC(2026, 10, 10 + offset)).toISOString().slice(0, 10);

export function today(overrides: Partial<Today> = {}): Today {
  const { hrv, signals } = recovery();
  return {
    today: '2026-11-10',
    figures: {
      form: { form: 4.2, band: 'neutral', fitness: 81.3 },
      sleep: { day: '2026-11-10', last_night: true, slept_s: 25560, score: 84, need_minutes: 490 },
      hrv: { avg7: 58, position: 'in' },
      resting_hr: { latest: 46, avg7: 48, change: -2 },
    },
    fitness: Array.from({ length: 90 }, (_, index) => ({
      day: day(index - 89),
      load: index % 7 === 6 ? 0 : 70,
      fitness: 60 + index / 4,
      fatigue: 60 + (index % 7) * 2,
      form: -10 + (index % 7) * 3,
      band: 'neutral' as const,
    })),
    week: {
      days: [
        { day: day(-6), swim: 0, bike: 1.5, run: 0, strength: 0, other: 0 },
        { day: day(-5), swim: 0, bike: 0, run: 0.97, strength: 0, other: 0 },
        { day: day(-4), swim: 0, bike: 0, run: 0, strength: 0.75, other: 0 },
        { day: day(-3), swim: 0, bike: 3.2, run: 0, strength: 0, other: 0 },
        { day: day(-2), swim: 0, bike: 0, run: 1.87, strength: 0, other: 0 },
        { day: day(-1), swim: 1.07, bike: 0, run: 0, strength: 0, other: 0 },
        { day: day(0), swim: 0, bike: 0, run: 0, strength: 0, other: 0 },
      ],
      total_hours: 9.36,
      average_hours: 1.34,
    },
    night: {
      day: '2026-11-10',
      last_night: true,
      started_at: '2026-11-09T23:41:00',
      ended_at: '2026-11-10T07:17:00',
      bed_min: -19,
      wake_min: 437,
      slept_s: 25560,
      score: 84,
      score_qualifier: 'GOOD',
      need_minutes: 490,
      in_bed_s: 27360,
      stages: [
        { stage: 'deep', seconds: 5040, share: 0.2, typical_low: 0.15, typical_high: 0.2 },
        { stage: 'light', seconds: 13320, share: 0.53, typical_low: 0.45, typical_high: 0.55 },
        { stage: 'rem', seconds: 7200, share: 0.28, typical_low: 0.2, typical_high: 0.25 },
        { stage: 'awake', seconds: 1800, share: 0.07, typical_low: null, typical_high: null },
      ],
    },
    hrv,
    activities: [
      {
        id: 9001,
        sport: 'lap_swimming',
        group: 'swim',
        name: 'Pool swim',
        start: '2026-11-09T07:10:00',
        distance_m: 3200,
        duration_s: 3840,
        load: 62,
      },
      {
        id: 9002,
        sport: 'running',
        group: 'run',
        name: 'Long run',
        start: '2026-11-08T08:00:00',
        distance_m: 21400,
        duration_s: 6720,
        load: 182,
      },
    ],
    signals,
    ...overrides,
  };
}
