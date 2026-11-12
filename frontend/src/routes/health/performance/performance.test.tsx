import { cleanup, fireEvent, screen, waitFor, within } from '@testing-library/react';
import { afterEach, expect, test, vi } from 'vitest';
import { pageCalls } from '@/test/health/calls';
import { performance } from '@/test/health/performance';
import { mockApi, renderAt } from '@/test/render';

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  localStorage.clear();
  document.documentElement.classList.add('dark');
  delete document.documentElement.dataset.domain;
});

function card(name: string): HTMLElement {
  return screen
    .getByRole('heading', { name, level: 2 })
    .closest('[data-slot="card"]') as HTMLElement;
}

test('shows the four figures and asks for this season by default', async () => {
  const calls = mockApi({ 'GET /api/health/performance': () => performance() });
  renderAt('/health/performance');

  expect(await screen.findByText('W′ 18.4 kJ · 4.2 W/kg')).toBeTruthy();
  expect(screen.getByText('268')).toBeTruthy();
  expect(screen.getByText('52.1')).toBeTruthy();
  expect(screen.getByText('1.4 in 90 days')).toBeTruthy();
  // In its figure; the pace curve's axis can label 4:10 too.
  expect(screen.getByText('Threshold run pace').parentElement?.textContent).toContain('4:10');
  expect(screen.getByText('1:38')).toBeTruthy();
  expect(pageCalls(calls)[0]?.search.get('period')).toBe('season');
  expect(screen.getByRole('button', { name: 'This season' }).getAttribute('aria-pressed')).toBe(
    'true',
  );
});

test('the period lives in the URL', async () => {
  const calls = mockApi({ 'GET /api/health/performance': () => performance() });
  const { router } = renderAt('/health/performance');
  await screen.findByText('52.1');
  fireEvent.click(screen.getByRole('button', { name: 'Last 90 days' }));
  await waitFor(() => expect(pageCalls(calls).at(-1)?.search.get('period')).toBe('90d'));
  expect(router.state.location.search).toEqual({ period: '90d' });
});

test('missing figures show a dash and a short marker', async () => {
  mockApi({
    'GET /api/health/performance': () => {
      const data = performance();
      data.run_power.model = null;
      data.run_pace.model = null;
      data.swim_threshold = null;
      data.vo2max = { points: [], latest: null, change_90d: null };
      return data;
    },
  });
  renderAt('/health/performance');
  expect(await screen.findAllByText('Too few efforts')).toHaveLength(2);
  expect(screen.getByText('No recent runs')).toBeTruthy();
  expect(screen.getByText('No 200 m and 400 m')).toBeTruthy();
  expect(screen.queryByText('CP model')).toBeNull();
});

test('predictions are labelled as estimates, with marathon shape', async () => {
  mockApi({ 'GET /api/health/performance': () => performance() });
  renderAt('/health/performance');
  await screen.findByText('52.1');
  const predictions = within(card('Race predictions'));
  expect(predictions.getByText('Estimate')).toBeTruthy();
  const rows = predictions.getAllByRole('row').slice(1);
  expect(rows.map((row) => row.textContent)).toEqual([
    '5 km19:103:5019:30',
    '10 km39:503:5940:40',
    'Half marathon1:28:204:111:29:50',
    'Marathon3:27:404:55, slowed by shape3:07:20',
  ]);
  expect(predictions.getByText('71%')).toBeTruthy();
  expect(predictions.getByText(/Half needs 43%/)).toBeTruthy();
  expect(predictions.getByText('Riegel from 10 km 40:40, 12 Oct')).toBeTruthy();
});

test('every chart lists its values for screen readers', async () => {
  mockApi({ 'GET /api/health/performance': () => performance() });
  renderAt('/health/performance');
  await screen.findByText('52.1');
  expect(screen.getByText('Best run power per duration')).toBeTruthy();
  expect(within(card('Run power curve')).getByText('20 min: 283 W, 2 Oct')).toBeTruthy();
  expect(within(card('Run pace curve')).getByText('1 h: 4:07, 2 Oct')).toBeTruthy();
  expect(within(card('Run VO2max')).getByText('1 Oct: 47.0, line 51.0')).toBeTruthy();
  expect(within(card('Easy-run efficiency')).getByText('1 Oct: 1.60, line 1.60')).toBeTruthy();
  expect(within(card('Bike')).getByText('1 min: 181 bpm, 21 Aug')).toBeTruthy();
});

test('the bike shows a heart-rate curve and climbs, and no power curve without power', async () => {
  mockApi({ 'GET /api/health/performance': () => performance() });
  renderAt('/health/performance');
  await screen.findByText('52.1');
  const bike = within(card('Bike'));
  expect(bike.getByText('Heart-rate curve')).toBeTruthy();
  expect(bike.queryByText('Power curve')).toBeNull();
  expect(bike.getByText('984 m/h')).toBeTruthy();
  expect(bike.getByText('6.2 km · 410 m · 6.6%')).toBeTruthy();
});

test('records in three columns with the all-time best in brackets', async () => {
  mockApi({ 'GET /api/health/performance': () => performance() });
  renderAt('/health/performance');
  await screen.findByText('52.1');
  const records = within(card('Records'));
  expect(records.getByText('All-time in brackets')).toBeTruthy();
  for (const name of ['Run', 'Bike', 'Swim', 'Triathlon']) {
    expect(records.getByRole('heading', { name })).toBeTruthy();
  }
  const run = records.getAllByRole('listitem').map((row) => row.textContent);
  expect(run).toContain('1 km3:41(3:38)');
  expect(run).toContain('5 km20:522 Oct');
  expect(run).toContain('Marathon–');
  expect(run).toContain('Longest ride121.4 km10 Jul');
  expect(run).toContain('20 min37.8 km/h21 Aug');
  expect(run.some((r) => r?.startsWith('1500 mopen water25:4013 Sep'))).toBe(true);
  expect(run.some((r) => r?.startsWith('Olympic triathlon2:31:0413 Sep'))).toBe(true);
});
