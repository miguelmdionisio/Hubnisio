import type {
  ActivityDetail,
  ActivityLeg,
  ActivityList,
  ActivityRow,
  ActivitySummary,
} from '@/api/types.gen';

/** Invented values throughout. */
export function leg(overrides: Partial<ActivityLeg> = {}): ActivityLeg {
  return {
    id: 100,
    sport: 'running',
    group: 'run',
    name: 'Long run',
    start: '2026-11-08T08:12:00',
    duration_s: 6730,
    distance_m: 21412,
    load: 182,
    figure_kind: 'pace_km',
    figure: 314.3,
    ...overrides,
  };
}

export function row(overrides: Partial<ActivityRow> = {}): ActivityRow {
  return { ...leg(), legs: [], ...overrides };
}

export function activityList(
  items: ActivityRow[] = [
    row(),
    row({
      id: 101,
      sport: 'cycling',
      group: 'bike',
      name: 'Evening ride',
      start: '2026-11-08T18:30:00',
      duration_s: 3600,
      distance_m: 36000,
      load: 64,
      figure_kind: 'speed_kmh',
      figure: 36,
    }),
    row({
      id: 102,
      sport: 'lap_swimming',
      group: 'swim',
      name: 'Pool',
      start: '2026-11-06T07:00:00',
      duration_s: 1800,
      distance_m: 1000,
      load: null,
      figure_kind: 'pace_100m',
      figure: 180,
    }),
  ],
  nextCursor: string | null = null,
): ActivityList {
  return { items, next_cursor: nextCursor };
}

const SUMMARY: ActivitySummary = {
  distance_m: null,
  duration_s: null,
  moving_s: null,
  elapsed_s: null,
  avg_speed: null,
  max_speed: null,
  graded_speed: null,
  avg_hr: null,
  max_hr: null,
  elevation_gain_m: null,
  elevation_loss_m: null,
  avg_cadence: null,
  max_cadence: null,
  avg_power: null,
  norm_power: null,
  max_power: null,
  calories: null,
  steps: null,
  pool_length_m: null,
  lengths: null,
  avg_swolf: null,
  avg_strokes: null,
  vo2max: null,
};

function bare(overrides: Partial<ActivityDetail>): ActivityDetail {
  return {
    id: 100,
    sport: 'running',
    group: 'run',
    family: 'run',
    name: 'Long run',
    start: '2026-11-08T08:12:00',
    pool: false,
    parent_id: null,
    legs: [],
    has_file: false,
    summary: SUMMARY,
    loads: { ours: null, garmin: null, aerobic_te: null, anaerobic_te: null, te_label: null },
    streams: null,
    splits: null,
    pool_sets: null,
    zones: null,
    durability: null,
    form: null,
    climbs: [],
    best_vam: null,
    route: null,
    ...overrides,
  };
}

const X = [0, 1000, 2000, 3000, 4000, 5000];

export function runDetail(overrides: Partial<ActivityDetail> = {}): ActivityDetail {
  return bare({
    has_file: true,
    summary: {
      ...SUMMARY,
      distance_m: 21412,
      duration_s: 6730,
      moving_s: 6200,
      avg_hr: 148,
      max_hr: 167,
      graded_speed: 3.236,
      elevation_gain_m: 212,
      elevation_loss_m: 209,
      avg_power: 268,
    },
    loads: { ours: 182, garmin: 141, aerobic_te: 3.8, anaerobic_te: 0.9, te_label: 'Tempo' },
    streams: {
      axis: 'distance',
      x: X,
      series: {
        pace: [320, 310, 305, 300, 315, 330],
        heart_rate: [140, 145, 148, 150, 152, 155],
        altitude: [40, 45, 52, 48, 44, 41],
        cadence: [174, 176, 177, 176, 175, 175],
      },
    },
    splits: {
      kind: 'km',
      rows: [
        {
          index: 1,
          distance_m: 1000,
          duration_s: 320,
          avg_hr: 140,
          avg_speed: 3.125,
          avg_power: null,
          elevation_change_m: 5,
        },
        {
          index: 2,
          distance_m: 1000,
          duration_s: 298,
          avg_hr: 148,
          avg_speed: 3.356,
          avg_power: null,
          elevation_change_m: -3,
        },
        {
          index: 3,
          distance_m: 412,
          duration_s: 140,
          avg_hr: 151,
          avg_speed: 2.943,
          avg_power: null,
          elevation_change_m: 0,
        },
      ],
    },
    zones: { source: 'ours', below_s: 60, seconds: [600, 3000, 2400, 600, 70], threshold: 171 },
    durability: {
      decoupling_pct: 3.1,
      efficiency_factor: 1.25,
      steady: true,
      efficiency_90d: 1.19,
      first: { speed: 3.17, heart_rate: 145, efficiency: 1.27 },
      second: { speed: 3.19, heart_rate: 151, efficiency: 1.23 },
    },
    form: {
      cadence: { value: 176, avg_90d: 176 },
      stride_cm: { value: 109, avg_90d: 107 },
      ground_contact_ms: { value: 238, avg_90d: 242 },
      vertical_oscillation_cm: { value: 8.4, avg_90d: 8.5 },
      vertical_ratio_pct: { value: 7.6, avg_90d: 7.8 },
      power: { value: 268, avg_90d: null },
    },
    route: [
      [38.7, -9.1],
      [38.701, -9.099],
      [38.703, -9.098],
      [38.702, -9.096],
      [38.7, -9.095],
    ],
    ...overrides,
  });
}

export function rideDetail(overrides: Partial<ActivityDetail> = {}): ActivityDetail {
  return bare({
    id: 101,
    sport: 'cycling',
    group: 'bike',
    family: 'ride',
    name: 'Evening ride',
    start: '2026-11-08T18:30:00',
    has_file: true,
    summary: {
      ...SUMMARY,
      distance_m: 36000,
      duration_s: 3600,
      avg_speed: 10,
      max_speed: 15.3,
      avg_hr: 138,
      max_hr: 171,
      elevation_gain_m: 410,
      elevation_loss_m: 405,
    },
    loads: { ours: 64, garmin: null, aerobic_te: null, anaerobic_te: null, te_label: null },
    streams: {
      axis: 'distance',
      x: X,
      series: {
        speed: [30, 34, 38, 36, 35, 33],
        heart_rate: [120, 130, 140, 142, 138, 136],
        altitude: [10, 40, 80, 60, 30, 12],
      },
    },
    splits: null,
    climbs: [
      { start_s: 600, duration_s: 540, distance_m: 2400, gain_m: 118, grade: 0.049, vam: 786 },
    ],
    best_vam: 786,
    route: [
      [38.7, -9.1],
      [38.71, -9.09],
    ],
    ...overrides,
  });
}

export function swimDetail(overrides: Partial<ActivityDetail> = {}): ActivityDetail {
  return bare({
    id: 102,
    sport: 'lap_swimming',
    group: 'swim',
    family: 'swim',
    name: 'Pool',
    start: '2026-11-06T07:00:00',
    pool: true,
    summary: {
      ...SUMMARY,
      distance_m: 1000,
      duration_s: 1800,
      avg_hr: 125,
      max_hr: 150,
      pool_length_m: 25,
      lengths: 40,
      avg_swolf: 44,
      avg_strokes: 17,
    },
    loads: { ours: 38, garmin: 40, aerobic_te: 2.9, anaerobic_te: 0, te_label: null },
    streams: {
      axis: 'time',
      x: [0, 600, 1200, 1800],
      series: { pace100: [185, 180, 178, 182], heart_rate: [110, 125, 130, 128] },
    },
    pool_sets: {
      sets: [
        {
          index: 1,
          lengths: 16,
          distance_m: 400,
          duration_s: 720,
          rest_s: 45,
          strokes: 280,
          swolf: 43,
          stroke: 'freestyle',
        },
        {
          index: 2,
          lengths: 8,
          distance_m: 200,
          duration_s: 380,
          rest_s: 0,
          strokes: 140,
          swolf: 46,
          stroke: 'backstroke',
        },
      ],
      lengths: [
        { index: 0, stroke: 'freestyle', strokes: 17, duration_s: 45, swolf: 62, set_index: 1 },
        { index: 1, stroke: 'freestyle', strokes: 16, duration_s: 44, swolf: 60, set_index: 1 },
        { index: 3, stroke: 'backstroke', strokes: 19, duration_s: 47, swolf: 66, set_index: 2 },
      ],
    },
    zones: { source: 'garmin', below_s: 0, seconds: [120, 900, 700, 80, 0], threshold: null },
    ...overrides,
  });
}

export function strengthDetail(overrides: Partial<ActivityDetail> = {}): ActivityDetail {
  return bare({
    id: 103,
    sport: 'strength_training',
    group: 'strength',
    family: 'other',
    name: null,
    start: '2026-11-05T17:45:00',
    summary: { ...SUMMARY, duration_s: 2700, avg_hr: 112, max_hr: 148, calories: 240 },
    loads: { ours: 21, garmin: null, aerobic_te: null, anaerobic_te: null, te_label: null },
    streams: { axis: 'time', x: [0, 900, 1800, 2700], series: { heart_rate: [95, 120, 130, 110] } },
    zones: { source: 'ours', below_s: 400, seconds: [1500, 700, 100, 0, 0], threshold: 171 },
    ...overrides,
  });
}

export function triathlonDetail(): ActivityDetail {
  return bare({
    id: 200,
    sport: 'multi_sport',
    group: 'other',
    family: 'other',
    name: 'Sprint triathlon',
    summary: { ...SUMMARY, distance_m: 25800, duration_s: 4800 },
    legs: [
      leg({
        id: 201,
        sport: 'lap_swimming',
        group: 'swim',
        name: 'Swim',
        distance_m: 750,
        duration_s: 780,
      }),
      leg({
        id: 202,
        sport: 'cycling',
        group: 'bike',
        name: 'Bike',
        distance_m: 20000,
        duration_s: 2400,
      }),
      leg({
        id: 203,
        sport: 'running',
        group: 'run',
        name: 'Run',
        distance_m: 5000,
        duration_s: 1500,
      }),
    ],
  });
}
