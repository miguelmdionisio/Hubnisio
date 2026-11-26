import { cleanup, fireEvent, screen, within } from '@testing-library/react';
import { afterEach, expect, test, vi } from 'vitest';
import { pageCalls } from '@/test/health/calls';
import { recovery } from '@/test/health/recovery';
import { mockApi, renderAt } from '@/test/render';

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  localStorage.clear();
  document.documentElement.classList.add('dark');
  delete document.documentElement.dataset.domain;
});

test('shows the four figures, the signals and the gaps', async () => {
  const calls = mockApi({ 'GET /api/health/recovery': () => recovery() });
  renderAt('/health/recovery');

  expect(await screen.findByText('In range 52–66')).toBeTruthy();
  expect(screen.getByText('90-day 7.1%')).toBeTruthy();
  expect(screen.getByText('6.2')).toBeTruthy();
  expect(screen.getByText('2 vs 7-day')).toBeTruthy();
  expect(screen.getByText('Charged +61')).toBeTruthy();
  expect(screen.getByText('Below range 1 night')).toBeTruthy();
  expect(screen.getByText('1 night without data')).toBeTruthy();
  expect(screen.getByText('Average 47.3')).toBeTruthy();

  expect(pageCalls(calls)[0]?.search.get('days')).toBe('90');
  expect(screen.getByRole('button', { name: '90 days' }).getAttribute('aria-pressed')).toBe('true');
});

test('each signal has its own state, word and icon, and the count is not a score', async () => {
  mockApi({
    'GET /api/health/recovery': () => {
      const data = recovery();
      data.signals.items.push({
        key: 'form',
        state: 'no_data',
        value: null,
        reference_low: null,
        reference_high: null,
        day: null,
      });
      return data;
    },
  });
  renderAt('/health/recovery');

  const heading = await screen.findByRole('heading', { name: 'Signals today' });
  const card = heading.closest('[data-slot="card"]') as HTMLElement;
  const rows = within(card).getAllByRole('listitem');
  expect(rows.map((row) => row.textContent)).toEqual([
    'HRV58 vs 52–66 msOK',
    'Resting HR46 vs 48 7-dayOK',
    'Sleep6h 40 of 8h 10 needWatch',
    'Body Battery82 at wake, 60 or moreOK',
    'FormNo data',
  ]);
  // The states differ by icon, not only by colour.
  const icons = rows.map((row) => row.querySelector('svg')?.getAttribute('class'));
  expect(new Set(icons).size).toBe(3);
  // Every state is counted, so the signal without data isn't hidden behind "3 of 4".
  expect(within(card).getByText('3 OK · 1 watch · 1 no data')).toBeTruthy();
});

test('HRV above its range is no problem: neutral, not the warning colour', async () => {
  mockApi({
    'GET /api/health/recovery': () => {
      const data = recovery();
      data.hrv.summary = { ...data.hrv.summary, position: 'above', avg7: 71 };
      return data;
    },
  });
  renderAt('/health/recovery');
  const above = await screen.findByText('Above 52–66');
  expect(above.className).not.toContain('text-destructive');
  expect(above.className).not.toContain('text-good');
});

test('flags a night below the range', async () => {
  mockApi({
    'GET /api/health/recovery': () => {
      const data = recovery();
      data.hrv.summary = { ...data.hrv.summary, position: 'below', avg7: 49 };
      return data;
    },
  });
  renderAt('/health/recovery');
  expect(await screen.findByText('Below 52–66')).toBeTruthy();
  const list = screen.getByText(/below range, 7-day/);
  expect(list.textContent).toContain('38 ms');
});

test('says when there is no normal range yet', async () => {
  mockApi({
    'GET /api/health/recovery': () => {
      const data = recovery();
      data.hrv.summary = {
        ...data.hrv.summary,
        position: null,
        band_low: null,
        band_high: null,
        below_nights: 0,
      };
      return data;
    },
  });
  renderAt('/health/recovery');
  expect((await screen.findAllByText('No normal range yet')).length).toBe(2);
});

test('lists the charts values for screen readers, gaps left out', async () => {
  mockApi({ 'GET /api/health/recovery': () => recovery() });
  renderAt('/health/recovery');
  await screen.findByText('In range 52–66');

  expect(screen.getByText('Nightly HRV, its 7-day average and the normal range')).toBeTruthy();
  expect(screen.getByText('Resting heart rate and its 7-day average')).toBeTruthy();
  expect(screen.getByText('Body Battery charged and drained per day')).toBeTruthy();
  expect(screen.getByText('Minutes of rest, low, medium and high stress per day')).toBeTruthy();
  // 30 days, one without HRV and one without resting heart rate.
  const hrvList = screen.getByText('Nightly HRV, its 7-day average and the normal range')
    .nextElementSibling as HTMLElement;
  expect(hrvList.querySelectorAll('li').length).toBe(29);
  const restingList = screen.getByText('Resting heart rate and its 7-day average')
    .nextElementSibling as HTMLElement;
  expect(restingList.querySelectorAll('li').length).toBe(29);
  expect(within(restingList).getAllByRole('listitem')[0]?.textContent).toContain('46 bpm');
});

test('the period lives in the URL and sets the days asked for', async () => {
  const calls = mockApi({ 'GET /api/health/recovery': () => recovery() });
  const { router } = renderAt('/health/recovery?days=30');
  await screen.findByText('In range 52–66');
  expect(pageCalls(calls)[0]?.search.get('days')).toBe('30');

  fireEvent.click(screen.getByRole('button', { name: '1 year' }));
  await screen.findByText('In range 52–66');
  expect(router.state.location.search).toMatchObject({ days: 365 });
  expect(pageCalls(calls).at(-1)?.search.get('days')).toBe('365');

  fireEvent.click(screen.getByRole('button', { name: '90 days' }));
  await screen.findByText('In range 52–66');
  expect(router.state.location.search).toEqual({});
});

test('a member with no Garmin data sees dashes and no data, not zeros', async () => {
  mockApi({
    'GET /api/health/recovery': () => {
      const data = recovery();
      data.hrv.points = data.hrv.points.map((p) => ({
        ...p,
        value: null,
        avg7: null,
        band_low: null,
        band_high: null,
        below: false,
      }));
      data.hrv.summary = {
        avg7: null,
        band_low: null,
        band_high: null,
        position: null,
        below_nights: 0,
        swing: null,
        swing_90: null,
        nights: 0,
      };
      data.resting_hr.summary = { latest: null, avg7: null, change: null, average: null };
      data.body_battery.summary = { at_wake: null, charged: null, day: null };
      data.signals = { items: [], ok: 0, total: 0 };
      return data;
    },
  });
  renderAt('/health/recovery');
  expect((await screen.findAllByText('No data')).length).toBeGreaterThanOrEqual(3);
  expect(screen.getByText('30 nights without data')).toBeTruthy();
  expect(screen.getByText('No normal range yet')).toBeTruthy();
});
