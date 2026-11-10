import { cleanup, fireEvent, screen, within } from '@testing-library/react';
import { afterEach, expect, test, vi } from 'vitest';
import { correlated, night, sleepNight, sleepTrends } from '@/test/health/sleep';
import { mockApi, renderAt } from '@/test/render';

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

function mockSleep(overrides: Record<string, (request: Request) => unknown> = {}) {
  return mockApi({
    'GET /api/health/sleep/night': () => sleepNight(),
    'GET /api/health/sleep/trends': () => sleepTrends(),
    ...overrides,
  });
}

test('shows the four figures of the latest night', async () => {
  const calls = mockSleep();
  renderAt('/health/sleep');

  expect(await screen.findByText('84')).toBeTruthy();
  expect(screen.getByText('Good · ▲ 6 vs 30-night')).toBeTruthy();
  expect(screen.getByText('7h 20')).toBeTruthy();
  expect(screen.getByText('Need 8h 10 · 7-day avg 7h 18')).toBeTruthy();
  expect(screen.getByText('23:41')).toBeTruthy();
  expect(screen.getByText('Up 07:17 · 2 wakes')).toBeTruthy();
  expect(screen.getByText('−3h 20')).toBeTruthy();
  expect(screen.getByText('Need 57h 10 · slept 53h 50')).toBeTruthy();
  expect(calls.find((c) => c.path === '/api/health/sleep/night')?.search.get('date')).toBeNull();
  expect(calls.find((c) => c.path === '/api/health/sleep/trends')?.search.get('nights')).toBe('30');
});

test('splits the night by stage with typical ranges, and lists the overnight readings', async () => {
  mockSleep();
  renderAt('/health/sleep');

  expect(await screen.findByText('Typical 45–55%')).toBeTruthy();
  expect(screen.getByText('Typical 15–20%')).toBeTruthy();
  expect(screen.getByText('Typical 20–25%')).toBeTruthy();
  expect(screen.getByText('30m')).toBeTruthy();
  expect(screen.getByText('18%')).toBeTruthy();
  expect(screen.getByText(/04:11: heart rate 42 bpm/)).toBeTruthy();
  expect(screen.getByText(/00:41: HRV 52 ms/)).toBeTruthy();
  expect(screen.getByText('Low 42 at 04:11')).toBeTruthy();
  expect(screen.getByText('Peak 81 at 03:51')).toBeTruthy();
  expect(screen.getByText('Range 12–17')).toBeTruthy();
  expect(screen.getByText('Low 89')).toBeTruthy();
});

test('steps between nights that exist and never past the latest', async () => {
  const calls = mockSleep({
    'GET /api/health/sleep/night': (request) => {
      const date = new URL(request.url).searchParams.get('date');
      return date === '2026-11-08'
        ? sleepNight({
            day: '2026-11-08',
            night: { ...night, day: '2026-11-08', score: 71 },
            previous_day: '2026-11-05',
            next_day: '2026-11-10',
          })
        : sleepNight();
    },
  });
  const { router } = renderAt('/health/sleep');

  await screen.findByText('84');
  const next = screen.getByRole('button', { name: 'Next night' });
  expect((next as HTMLButtonElement).disabled).toBe(true);
  fireEvent.click(screen.getByRole('button', { name: 'Previous night' }));

  expect(await screen.findByText('71')).toBeTruthy();
  expect(router.state.location.search).toMatchObject({ date: '2026-11-08' });
  expect(calls.some((c) => c.search.get('date') === '2026-11-08')).toBe(true);
  expect((screen.getByRole('button', { name: 'Next night' }) as HTMLButtonElement).disabled).toBe(
    false,
  );
});

test('the period lives in the URL and refetches the trends', async () => {
  const calls = mockSleep();
  const { router } = renderAt('/health/sleep');
  await screen.findByText('84');

  fireEvent.click(screen.getByRole('button', { name: '90 nights' }));

  await screen.findByRole('button', { name: '90 nights', pressed: true });
  expect(router.state.location.search).toMatchObject({ nights: 90 });
  expect(calls.some((c) => c.search.get('nights') === '90')).toBe(true);
});

test('trends: average, gaps marked, schedule spread and weekday scores', async () => {
  mockSleep();
  renderAt('/health/sleep');

  expect(await screen.findByText('avg 7h 18')).toBeTruthy();
  expect(screen.getByText('2 nights not worn')).toBeTruthy();
  expect(screen.getByText('bedtime ± 34 min · wake ± 22 min')).toBeTruthy();
  expect(screen.getByText('Sun: 85')).toBeTruthy();
  // a gap is not listed as a night of zero hours
  expect(screen.queryByText(/slept 0h/)).toBeNull();
  expect(screen.getAllByText(/slept 7h/).length).toBeGreaterThan(0);
});

test('the scatter needs twenty nights, then shows r', async () => {
  mockSleep();
  const first = renderAt('/health/sleep');
  expect(await screen.findByText('Needs 20 nights with HRV, 0 so far')).toBeTruthy();
  first.unmount();
  cleanup();

  mockSleep({ 'GET /api/health/sleep/trends': () => sleepTrends({ correlation: correlated() }) });
  renderAt('/health/sleep');
  expect(await screen.findByText(/r = 0.62/)).toBeTruthy();
  expect(screen.queryByText(/Needs 20 nights/)).toBeNull();
  expect(screen.getByText('Thu 1 Oct: 6h 00 slept, HRV 50 ms next morning')).toBeTruthy();
});

test('a day without a night says so instead of showing zeros', async () => {
  mockSleep({
    'GET /api/health/sleep/night': () =>
      sleepNight({
        day: '2026-11-09',
        night: null,
        previous_day: '2026-11-08',
        next_day: '2026-11-10',
      }),
  });
  renderAt('/health/sleep?date=2026-11-09');

  expect(await screen.findByText('Mon 9 Nov: no night recorded')).toBeTruthy();
  const trends = await screen.findByText('Schedule');
  expect(within(trends.closest('[data-slot=card]') as HTMLElement).queryByText('0h 00')).toBeNull();
});

test('with no nights at all it says so', async () => {
  mockSleep({
    'GET /api/health/sleep/night': () =>
      sleepNight({ day: null, night: null, previous_day: null, next_day: null }),
    'GET /api/health/sleep/trends': () =>
      sleepTrends({
        nights_worn: 0,
        points: sleepTrends().points.map((p) => ({ ...p, worn: false })),
      }),
  });
  renderAt('/health/sleep');

  expect(await screen.findByText('No nights yet')).toBeTruthy();
  expect(await screen.findByText('No nights in these 30')).toBeTruthy();
});
