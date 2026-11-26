import { cleanup, screen, within } from '@testing-library/react';
import { afterEach, expect, test, vi } from 'vitest';
import { connection } from '@/test/health/garmin';
import { today } from '@/test/health/today';
import { mockApi, renderAt } from '@/test/render';

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  localStorage.clear();
  document.documentElement.classList.add('dark');
  delete document.documentElement.dataset.domain;
});

test('four figures link to their pages', async () => {
  const calls = mockApi({ 'GET /api/health/today': () => today() });
  renderAt('/health');

  expect(await screen.findByText('+4')).toBeTruthy();
  expect(screen.getByText('Neutral · fitness 81')).toBeTruthy();
  expect(screen.getByText('7h 06')).toBeTruthy();
  expect(screen.getByText('Score 84 · need 8h 10')).toBeTruthy();
  expect(screen.getByText('In range')).toBeTruthy();
  expect(screen.getByText('2 vs 7-day')).toBeTruthy();

  const href = (name: RegExp) =>
    screen
      .getAllByRole('link', { name })
      .find((l) => l.getAttribute('href')?.startsWith('/health/'))
      ?.getAttribute('href');
  expect(href(/^Form/)).toBe('/health/training');
  expect(href(/^Last night/)).toBe('/health/sleep');
  expect(href(/^HRV, 7-day/)).toBe('/health/recovery');
  expect(href(/^Resting HR/)).toBe('/health/recovery');
  // The page's own data, and the header's Garmin freshness.
  expect(new Set(calls.map((c) => c.path))).toEqual(
    new Set(['/api/health/today', '/api/health/connection']),
  );
  // No Mine / Household switch on Health.
  expect(screen.queryByRole('group', { name: 'View' })).toBeNull();
});

test('every chart has its values for a screen reader', async () => {
  mockApi({ 'GET /api/health/today': () => today() });
  renderAt('/health');

  await screen.findByText('+4');
  const fitness = screen.getByText('Fitness, fatigue and form over 90 days');
  expect(within(fitness.closest('figure') as HTMLElement).getAllByRole('listitem')).toHaveLength(
    90,
  );
  const week = screen.getByText('Hours per day by sport over the last 7 days').closest('figure');
  const items = within(week as HTMLElement).getAllByRole('listitem');
  expect(items).toHaveLength(7);
  expect(items[0]?.textContent).toContain('Bike 1.5 h');
  expect(items[6]?.textContent).toContain('no activity');
  expect(screen.getByText('Nightly HRV, its 7-day average and the normal range')).toBeTruthy();
  expect(screen.getByText('9.4 h · 1.3 h a day')).toBeTruthy();
});

test('last night shows its stages, bed and wake times', async () => {
  mockApi({ 'GET /api/health/today': () => today() });
  renderAt('/health');

  expect(await screen.findByText('Last night', { selector: 'h2' })).toBeTruthy();
  expect(screen.getByText('23:41 – 07:17')).toBeTruthy();
  expect(screen.getByText('Deep 1h 24')).toBeTruthy();
  expect(screen.getByText('Light 3h 42')).toBeTruthy();
  expect(screen.getByText('REM 2h 00')).toBeTruthy();
  expect(screen.getByText('Awake 0h 30')).toBeTruthy();
  expect(screen.getByText(/In bed 23:41, awake 07:17/)).toBeTruthy();
});

test('without last night the latest night is dated; without any, a gap', async () => {
  const data = today();
  mockApi({
    'GET /api/health/today': () => ({
      ...data,
      figures: {
        ...data.figures,
        sleep: {
          day: '2026-11-07',
          last_night: false,
          slept_s: 25200,
          score: 80,
          need_minutes: 480,
        },
      },
      night: data.night && { ...data.night, day: '2026-11-07', last_night: false },
    }),
  });
  renderAt('/health');

  expect(await screen.findByText('Night of Sat 7 Nov')).toBeTruthy();
  expect(screen.getByText('Latest night', { selector: 'h2' })).toBeTruthy();
  cleanup();

  mockApi({
    'GET /api/health/today': () => ({
      ...data,
      figures: { ...data.figures, sleep: null },
      night: null,
    }),
  });
  renderAt('/health');
  expect(await screen.findByText('No night recorded')).toBeTruthy();
});

test('recent activities link to the activity, with a pill to all', async () => {
  mockApi({ 'GET /api/health/today': () => today() });
  renderAt('/health');

  const swim = await screen.findByRole('link', { name: /Pool swim/ });
  expect(swim.getAttribute('href')).toBe('/health/activities/9001');
  expect(swim.textContent).toContain('3.2 km');
  expect(swim.textContent).toContain('1:04:00');
  expect(swim.textContent).toContain('load 62');
  expect(screen.getByRole('link', { name: 'All activities' }).getAttribute('href')).toBe(
    '/health/activities',
  );
});

test('the signals strip tells each signal apart without colour', async () => {
  mockApi({ 'GET /api/health/today': () => today() });
  renderAt('/health');

  const heading = await screen.findByRole('heading', { name: 'Signals today' });
  const card = heading.closest('a')?.parentElement as HTMLElement;
  expect(within(card).getByText('3 OK · 1 watch')).toBeTruthy();
  // The verdict shows at every width, desktop too, and comes first.
  expect(card.className).not.toMatch(/(^|\s)(md:)?hidden(\s|$)/);
  const main = screen.getByRole('main');
  expect(main.querySelector('[data-slot="card"]')).toBe(card);
  const items = within(card).getAllByRole('listitem');
  expect(items.map((i) => i.textContent)).toEqual([
    'HRV: OK',
    'Resting HR: OK',
    'Sleep: Watch',
    'Body Battery: OK',
  ]);
});

test('a signal without data is counted, and HRV above its range is not a warning', async () => {
  const data = today();
  data.signals.items = data.signals.items.map((signal) =>
    signal.key === 'sleep' ? { ...signal, state: 'no_data', value: null } : signal,
  );
  data.figures.hrv = { ...data.figures.hrv, position: 'above' };
  mockApi({ 'GET /api/health/today': () => data });
  renderAt('/health');

  expect(await screen.findByText('3 OK · 1 no data')).toBeTruthy();
  const above = screen.getByText('Above');
  expect(above.className).not.toContain('text-destructive');
});

test('a gap in the data is a dash and a note, never a zero', async () => {
  const data = today();
  mockApi({
    'GET /api/health/today': () => ({
      ...data,
      figures: {
        form: { form: null, band: null, fitness: null },
        sleep: null,
        hrv: { avg7: null, position: null },
        resting_hr: { latest: null, avg7: null, change: null },
      },
      fitness: [],
      activities: [],
      night: null,
    }),
  });
  renderAt('/health');

  expect(await screen.findAllByText('No data')).toHaveLength(4);
  expect(screen.getAllByText('No activities yet')).toHaveLength(2);
  expect(screen.getByText('No night recorded')).toBeTruthy();
});

test('stale Garmin data is said first, linking to the Garmin page', async () => {
  const synced = new Date(Date.now() - 3 * 86_400_000).toISOString();
  mockApi({
    'GET /api/health/today': () => today(),
    'GET /api/health/connection': () => connection({ last_synced_at: synced }),
  });
  renderAt('/health');

  const notice = await screen.findByRole('link', { name: /^Garmin last synced/ });
  expect(notice.getAttribute('href')).toBe('/health/garmin');
  expect(notice.textContent).toContain('Sync now');
});

test('fresh Garmin data needs no notice', async () => {
  mockApi({
    'GET /api/health/today': () => today(),
    'GET /api/health/connection': () => connection(),
  });
  renderAt('/health');

  expect(await screen.findByText('+4')).toBeTruthy();
  expect(await screen.findByText(/^Garmin synced/)).toBeTruthy();
  expect(screen.queryByRole('link', { name: /^Garmin last synced/ })).toBeNull();
});
