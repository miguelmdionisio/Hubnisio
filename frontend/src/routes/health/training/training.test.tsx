import { cleanup, fireEvent, screen, within } from '@testing-library/react';
import { afterEach, expect, test, vi } from 'vitest';
import { training } from '@/test/health/training';
import { mockApi, renderAt } from '@/test/render';

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  localStorage.clear();
  document.documentElement.classList.add('dark');
  delete document.documentElement.dataset.domain;
});

test('shows the four figures with their words', async () => {
  const calls = mockApi({ 'GET /api/health/training': () => training() });
  renderAt('/health/training');

  expect(await screen.findByText('+7 in 6 weeks')).toBeTruthy();
  expect(screen.getByText('52')).toBeTruthy();
  expect(screen.getByText('61')).toBeTruthy();
  expect(screen.getByText('7-day load')).toBeTruthy();
  expect(screen.getByText('−9')).toBeTruthy();
  expect(screen.getByText('Neutral')).toBeTruthy();
  expect(screen.getByText('+2.4')).toBeTruthy();
  expect(screen.getByText('Safe under 6')).toBeTruthy();
  expect(calls[0]?.search.get('days')).toBe('90');
});

test('a steep ramp is told by its words and icon, not colour alone', async () => {
  mockApi({
    'GET /api/health/training': () => {
      const data = training();
      data.summary = { ...data.summary, ramp_per_week: 7.5, ramp_safe: false };
      return data;
    },
  });
  renderAt('/health/training');
  expect(await screen.findByText('Steep, over 6')).toBeTruthy();
});

test('names the form bands and lists every chart value for screen readers', async () => {
  mockApi({ 'GET /api/health/training': () => training() });
  renderAt('/health/training');
  await screen.findByText('Fresh above +5');
  expect(screen.getByText('Neutral −10 to +5')).toBeTruthy();
  expect(screen.getByText('Optimal −30 to −10')).toBeTruthy();
  expect(screen.getByText('High risk below −30')).toBeTruthy();

  const load = screen.getByText('Fitness, fatigue, form and load per day')
    .nextElementSibling as HTMLElement;
  expect(load.querySelectorAll('li').length).toBe(21);
  expect(load.querySelector('li')?.textContent).toContain('form -10 (Neutral)');
  const weeks = screen.getByText('Hours per week by sport').nextElementSibling as HTMLElement;
  expect(weeks.querySelectorAll('li').length).toBe(3);
  expect(weeks.textContent).toContain('Bike 4.5 h');
  expect(weeks.textContent).toContain('(so far)');
});

test('shows the weekly average, the intensity split and the months', async () => {
  mockApi({ 'GET /api/health/training': () => training() });
  renderAt('/health/training');
  expect(await screen.findByText('Average 7h 15')).toBeTruthy();

  const intensity = screen
    .getByRole('heading', { name: 'Intensity' })
    .closest('[data-slot="card"]') as HTMLElement;
  expect(
    within(intensity)
      .getAllByRole('listitem')
      .map((li) => li.textContent),
  ).toEqual([
    'SwimZ1–2, Z3, Z4–5 percent: 64 / 22 / 14',
    'RunZ1–2, Z3, Z4–5 percent: 76 / 12 / 12',
    'AllZ1–2, Z3, Z4–5 percent: 70 / 17 / 13',
  ]);

  const table = screen.getByRole('table');
  const rows = within(table).getAllByRole('row');
  expect(rows[1]?.textContent).toContain('November 2026 (so far)');
  expect(rows[1]?.textContent).toContain('62 km');
  expect(rows[1]?.textContent).toContain('14');
  expect(rows[2]?.textContent).toContain('3.2 km');
});

test('the period lives in the URL', async () => {
  const calls = mockApi({ 'GET /api/health/training': () => training() });
  const { router } = renderAt('/health/training?days=365');
  await screen.findByText('Safe under 6');
  expect(calls[0]?.search.get('days')).toBe('365');
  expect(screen.getByRole('button', { name: '1 year' }).getAttribute('aria-pressed')).toBe('true');

  fireEvent.click(screen.getByRole('button', { name: 'All' }));
  await screen.findByText('Safe under 6');
  expect(router.state.location.search).toMatchObject({ days: 'all' });
  expect(calls.at(-1)?.search.get('days')).toBe('all');

  fireEvent.click(screen.getByRole('button', { name: '90 days' }));
  await screen.findByText('Safe under 6');
  expect(router.state.location.search).toEqual({});
});

test('without activities it says there is no data, not zeros', async () => {
  mockApi({
    'GET /api/health/training': () =>
      training({
        first_day: null,
        points: [],
        weeks: [],
        average_week_hours: null,
        intensity: [],
        months: [],
        summary: {
          fitness: null,
          fatigue: null,
          form: null,
          band: null,
          fitness_change: null,
          ramp_per_week: null,
          ramp_safe: null,
        },
      }),
  });
  renderAt('/health/training');
  expect(await screen.findByText('No data yet')).toBeTruthy();
});

test('a short history shows dashes for the ramp', async () => {
  mockApi({
    'GET /api/health/training': () => {
      const data = training();
      data.summary = {
        ...data.summary,
        ramp_per_week: null,
        ramp_safe: null,
        fitness_change: null,
      };
      data.intensity = [];
      data.weeks = [];
      data.average_week_hours = null;
      return data;
    },
  });
  renderAt('/health/training');
  expect(await screen.findByText('Not enough history')).toBeTruthy();
  expect(screen.getByText('No heart-rate zones yet')).toBeTruthy();
  expect(screen.getByText('No whole week yet')).toBeTruthy();
});
