import { cleanup, screen, within } from '@testing-library/react';
import { afterEach, expect, test, vi } from 'vitest';
import {
  rideDetail,
  runDetail,
  strengthDetail,
  swimDetail,
  triathlonDetail,
} from '@/test/health/activities';
import { mockApi, renderAt } from '@/test/render';

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  localStorage.clear();
  document.documentElement.classList.add('dark');
  delete document.documentElement.dataset.domain;
});

const headings = () =>
  within(screen.getByRole('main'))
    .queryAllByRole('heading', { level: 2 })
    .map((h) => h.textContent);

/** The card a label sits in, as one string: "Pace5:14/kmGraded 5:09". */
const card = (label: string) => {
  const [first] = screen.getAllByText(label);
  return first?.closest('[data-slot="card"]')?.textContent;
};

test('a run shows its six figures and every section it has data for', async () => {
  const calls = mockApi({ 'GET /api/health/activities/100': () => runDetail() });
  renderAt('/health/activities/100');

  expect(await screen.findByRole('heading', { name: 'Long run', level: 1 })).toBeTruthy();
  expect(calls[0]?.path).toBe('/api/health/activities/100');
  expect(screen.getByText('Sun 8 Nov · 08:12')).toBeTruthy();
  expect(card('Distance')).toBe('Distance21.4km');
  expect(card('Time')).toBe('Time1:52:10Moving 1:43:20');
  expect(card('Pace')).toBe('Pace5:14/kmGraded 5:09');
  expect(card('Heart rate')).toBe('Heart rate148bpmMax 167');
  expect(card('Load')).toBe('Load182Garmin 141');
  expect(card('Training effect')).toBe('Training effect3.8Aerobic · 0.9 anaerobic');
  expect(headings()).toEqual([
    'Through the run',
    'Splits',
    'Route',
    'Aerobic durability',
    'Heart-rate zones',
    'Running form',
  ]);
});

test('the run charts list their values for a screen reader', async () => {
  mockApi({ 'GET /api/health/activities/100': () => runDetail() });
  renderAt('/health/activities/100');

  const pace = await screen.findByRole('list', { name: 'Pace /km' });
  expect(within(pace).getAllByRole('listitem')[0]?.textContent).toBe('0 m: 5:20');
  expect(screen.getByRole('list', { name: 'Heart rate' })).toBeTruthy();
  expect(screen.getByRole('list', { name: 'Elevation m' })).toBeTruthy();
  expect(screen.getByRole('list', { name: 'Cadence' })).toBeTruthy();
  expect(screen.getByRole('img', { name: 'Route' })).toBeTruthy();
});

test('splits are per kilometre with a short last one marked', async () => {
  mockApi({ 'GET /api/health/activities/100': () => runDetail() });
  renderAt('/health/activities/100');

  const table = await screen.findByRole('table', { name: 'Splits per kilometre' });
  const rows = within(table).getAllByRole('row');
  expect(rows.map((r) => r.textContent)).toEqual([
    'KmPace /kmHeart rateElevation',
    '15:20140+5 m',
    '24:58148−3 m',
    '3 (412 m)5:401510 m',
  ]);
});

test('durability and running form show the figures beside their 90-day references', async () => {
  mockApi({ 'GET /api/health/activities/100': () => runDetail() });
  renderAt('/health/activities/100');

  expect(await screen.findByText('vs 1.19 90-day')).toBeTruthy();
  const halves = screen.getByRole('table', { name: 'First and second half' });
  expect(
    within(halves)
      .getAllByRole('row')
      .map((r) => r.textContent),
  ).toEqual([
    'HalfPaceHeart rateEfficiency',
    'First half5:15 /km1451.27',
    'Second half5:13 /km1511.23',
  ]);
  expect(screen.getByText('Steady')).toBeTruthy();
  expect(screen.getByText('90-day 242')).toBeTruthy();
  expect(screen.getByText('90-day 1.07')).toBeTruthy();
  // the zones: ours, with the threshold
  expect(screen.getByText('Threshold 171')).toBeTruthy();
  expect(screen.getByText('<Z1')).toBeTruthy();
});

test('the original file downloads from the API', async () => {
  mockApi({ 'GET /api/health/activities/100': () => runDetail() });
  renderAt('/health/activities/100');

  const link = await screen.findByRole('link', { name: 'Download .FIT' });
  expect(link.getAttribute('href')).toBe('/api/health/activities/100/file');
  expect(link.hasAttribute('download')).toBe(true);
});

test('an activity without a stored file offers no download', async () => {
  mockApi({ 'GET /api/health/activities/100': () => runDetail({ has_file: false }) });
  renderAt('/health/activities/100');

  await screen.findByRole('heading', { name: 'Long run', level: 1 });
  expect(screen.queryByRole('link', { name: 'Download .FIT' })).toBeNull();
});

test('a ride has speed, climbs and no power unless it has power', async () => {
  mockApi({ 'GET /api/health/activities/101': () => rideDetail() });
  renderAt('/health/activities/101');

  expect(await screen.findByRole('heading', { name: 'Evening ride', level: 1 })).toBeTruthy();
  expect(card('Speed')).toBe('Speed36.0km/hMax 55.1');
  expect(card('Elevation')).toBe('Elevation+410m−405 m');
  expect(headings()).toEqual(['Through the ride', 'Route', 'Climbs']);
  expect(screen.getByRole('list', { name: 'Speed km/h' })).toBeTruthy();
  expect(screen.queryByRole('list', { name: 'Power W' })).toBeNull();
  expect(screen.queryByText('Power')).toBeNull();
  const climbs = screen.getByRole('table', { name: 'Climbs' });
  expect(within(climbs).getAllByRole('row')[1]?.textContent).toBe('12.4 km+118 m4.9%9:00786 m/h');
  expect(screen.getByText('Best 786 m/h')).toBeTruthy();
});

test('a ride with power shows it in a figure and a chart', async () => {
  mockApi({
    'GET /api/health/activities/101': () => {
      const ride = rideDetail();
      ride.summary = { ...ride.summary, avg_power: 210, norm_power: 228 };
      if (ride.streams) ride.streams.series.power = [180, 220, 260, 230, 210, 200];
      return ride;
    },
  });
  renderAt('/health/activities/101');

  expect(await screen.findByText('Normalized 228')).toBeTruthy();
  expect(screen.getByRole('list', { name: 'Power W' })).toBeTruthy();
});

test('a pool swim has pace per 100 m, sets and lengths with SWOLF, and no route', async () => {
  mockApi({ 'GET /api/health/activities/102': () => swimDetail() });
  renderAt('/health/activities/102');

  expect(await screen.findByRole('heading', { name: 'Pool', level: 1 })).toBeTruthy();
  expect(card('Pace')).toBe('Pace3:00/100 m');
  expect(card('SWOLF')).toBe('SWOLF4440 lengths');
  expect(headings()).toEqual(['Through the swim', 'Sets', 'SWOLF by length', 'Heart-rate zones']);
  expect(screen.getByRole('list', { name: 'Pace /100 m' })).toBeTruthy();
  const sets = screen.getByRole('table', { name: 'Sets' });
  expect(
    within(sets)
      .getAllByRole('row')
      .map((r) => r.textContent),
  ).toEqual([
    'SetLengthsDistanceTimePace /100 mRestSWOLFStroke',
    '116400 m12:003:000:4543Freestyle',
    '28200 m6:203:10–46Backstroke',
  ]);
  expect(screen.getByText('Garmin zones')).toBeTruthy();
  expect(screen.queryByRole('img', { name: 'Route' })).toBeNull();
  expect(screen.getByText(/Length 1, set 1: SWOLF 62/)).toBeTruthy();
});

test('a strength session has figures, heart rate over time and zones only', async () => {
  mockApi({ 'GET /api/health/activities/103': () => strengthDetail() });
  renderAt('/health/activities/103');

  expect(await screen.findByRole('heading', { name: 'Strength', level: 1 })).toBeTruthy();
  expect(card('Calories')).toBe('Calories240kcal');
  expect(headings()).toEqual(['Over time', 'Heart-rate zones']);
  expect(
    screen.getAllByRole('list').some((l) => l.getAttribute('aria-label') === 'Heart rate'),
  ).toBe(true);
  expect(screen.queryByRole('list', { name: 'Elevation m' })).toBeNull();
});

test('a multisport activity links to its legs', async () => {
  mockApi({ 'GET /api/health/activities/200': () => triathlonDetail() });
  renderAt('/health/activities/200');

  await screen.findByRole('heading', { name: 'Sprint triathlon', level: 1 });
  const legs = screen.getByRole('heading', { name: 'Legs' }).closest('[data-slot="card"]');
  const links = within(legs as HTMLElement).getAllByRole('link');
  expect(links.map((l) => l.getAttribute('href'))).toEqual([
    '/health/activities/201',
    '/health/activities/202',
    '/health/activities/203',
  ]);
  expect(links[0]?.textContent).toBe('Swim750 m · 13:00');
  expect(headings()).toEqual(['Legs']);
});

test('sections without data are left out, not shown empty', async () => {
  mockApi({
    'GET /api/health/activities/100': () =>
      runDetail({
        streams: null,
        splits: null,
        route: null,
        zones: null,
        durability: null,
        form: null,
      }),
  });
  renderAt('/health/activities/100');

  await screen.findByRole('heading', { name: 'Long run', level: 1 });
  expect(headings()).toEqual([]);
});

test('says so when the activity does not exist', async () => {
  mockApi({
    'GET /api/health/activities/999': () =>
      new Response(JSON.stringify({ detail: 'No such activity' }), { status: 404 }),
  });
  renderAt('/health/activities/999');

  expect(await screen.findByText("Couldn't load this")).toBeTruthy();
});
