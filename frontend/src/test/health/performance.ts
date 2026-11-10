import type { Performance } from '@/api/types.gen';

/** Invented values: a season to 2026-11-10 with run power and pace, rides with heart rate
 * only, a pool swim, one triathlon. */
const DURATIONS = [1, 5, 10, 15, 30, 60, 120, 300, 600, 1200, 1800, 3600, 5400, 7200];

type Curve = Performance['run_power']['current'];

function curve(fn: (t: number) => number | null, day = '2026-10-02', id = 1): Curve {
  return DURATIONS.map((t) => {
    const value = fn(t);
    return {
      duration_s: t,
      value,
      day: value === null ? null : day,
      activity_id: value === null ? null : id,
    };
  });
}

const line = (fn: (t: number) => number) =>
  [120, 300, 600, 1200, 1800, 3600].map((t) => ({ duration_s: t, value: fn(t) }));

export function performance(overrides: Partial<Performance> = {}): Performance {
  return {
    period: 'season',
    first_day: '2026-01-01',
    last_day: '2026-11-10',
    season: 2026,
    weight_kg: 64,
    run_power: {
      current: curve((t) => (t <= 7200 ? 268 + 18400 / t : null)),
      last_season: curve((t) => 255 + 17000 / t, '2025-09-14', 9),
      model: {
        cp: 268,
        w_prime: 18400,
        cp_per_kg: 4.19,
        points: 3,
        line: line((t) => 268 + 18400 / t),
      },
    },
    run_pace: {
      current: curve((t) => 4 + 150 / t),
      last_season: curve((t) => 3.85 + 150 / t, '2025-09-14', 9),
      model: {
        speed: 4,
        d_prime: 150,
        pace_per_km_s: 250,
        points: 3,
        line: line((t) => 4 + 150 / t),
      },
    },
    swim_threshold: { speed: 200 / 196, pace_per_100_s: 98, t200_s: 170, t400_s: 366 },
    vo2max: {
      points: [
        { day: '2026-09-01', activity_id: 11, value: 50.2, line: 50.2 },
        { day: '2026-10-01', activity_id: 12, value: 47.0, line: 51.0 },
        { day: '2026-11-08', activity_id: 13, value: 52.1, line: 52.1 },
      ],
      latest: 52.1,
      change_90d: 1.4,
    },
    predictions: {
      vo2max: 52.1,
      shape: {
        score: 0.71,
        weekly_km: 48,
        weekly_target_km: 89,
        weekly_share: 0.54,
        long_runs: 4,
        long_target_km: 30.8,
        long_share: 1.05,
      },
      items: [
        { distance_m: 5000, needs: 0, vdot_s: 1150, slowed: false, riegel_s: 1170 },
        { distance_m: 10000, needs: 0.13, vdot_s: 2390, slowed: false, riegel_s: 2440 },
        { distance_m: 21097, needs: 0.43, vdot_s: 5300, slowed: false, riegel_s: 5390 },
        { distance_m: 42195, needs: 1, vdot_s: 12460, slowed: true, riegel_s: 11240 },
      ],
      riegel_from: { distance_m: 10000, seconds: 2440, day: '2026-10-12', activity_id: 14 },
    },
    efficiency: {
      points: [
        { day: '2026-06-01', activity_id: 21, value: 1.5 },
        { day: '2026-08-01', activity_id: 22, value: 1.56 },
        { day: '2026-10-01', activity_id: 23, value: 1.6 },
      ],
      trend: { start_day: '2026-06-01', start: 1.5, end_day: '2026-10-01', end: 1.6 },
      change_6m_pct: 6.7,
    },
    bike: {
      hr_curve: {
        current: curve((t) => 182 - t / 100, '2026-08-21', 31),
        last_season: curve((t) => 180 - t / 100, '2025-07-01', 32),
      },
      power_curve: null,
      climbs: [
        {
          day: '2026-08-21',
          activity_id: 31,
          distance_m: 6200,
          gain_m: 410,
          duration_s: 1500,
          grade: 0.066,
          vam: 984,
        },
      ],
    },
    records: {
      run: [
        {
          key: '1000',
          value: 221,
          day: '2026-05-01',
          activity_id: 1,
          venue: null,
          all_time: 218,
          all_time_day: '2025-06-01',
        },
        {
          key: '5000',
          value: 1252,
          day: '2026-10-02',
          activity_id: 2,
          venue: null,
          all_time: null,
          all_time_day: null,
        },
        {
          key: '10000',
          value: 2670,
          day: '2026-10-12',
          activity_id: 14,
          venue: null,
          all_time: null,
          all_time_day: null,
        },
        {
          key: '21097',
          value: 6072,
          day: '2026-09-14',
          activity_id: 3,
          venue: null,
          all_time: null,
          all_time_day: null,
        },
        {
          key: '42195',
          value: null,
          day: null,
          activity_id: null,
          venue: null,
          all_time: null,
          all_time_day: null,
        },
      ],
      swim: [
        {
          key: '100',
          value: 86,
          day: '2026-03-01',
          activity_id: 4,
          venue: 'pool',
          all_time: null,
          all_time_day: null,
        },
        {
          key: '400',
          value: 382,
          day: '2026-03-01',
          activity_id: 4,
          venue: 'pool',
          all_time: null,
          all_time_day: null,
        },
        {
          key: '1500',
          value: 1540,
          day: '2026-09-13',
          activity_id: 5,
          venue: 'open_water',
          all_time: null,
          all_time_day: null,
        },
      ],
      bike: [
        {
          key: 'longest',
          value: 121400,
          day: '2026-07-10',
          activity_id: 6,
          venue: null,
          all_time: null,
          all_time_day: null,
        },
        {
          key: 'climbing',
          value: 1850,
          day: '2026-07-10',
          activity_id: 6,
          venue: null,
          all_time: null,
          all_time_day: null,
        },
        {
          key: 'speed_1200',
          value: 10.5,
          day: '2026-08-21',
          activity_id: 31,
          venue: null,
          all_time: null,
          all_time_day: null,
        },
        {
          key: 'speed_3600',
          value: 9.4,
          day: '2026-08-21',
          activity_id: 31,
          venue: null,
          all_time: null,
          all_time_day: null,
        },
      ],
      triathlon: [
        {
          activity_id: 7,
          name: 'Olympic triathlon',
          day: '2026-09-13',
          duration_s: 9064,
          distance_m: 51500,
        },
      ],
    },
    ...overrides,
  };
}
