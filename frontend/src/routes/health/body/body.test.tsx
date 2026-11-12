import { cleanup, fireEvent, screen, within } from '@testing-library/react';
import { afterEach, expect, test, vi } from 'vitest';
import { body, emptyBody, oneWeighIn } from '@/test/health/body';
import { pageCalls } from '@/test/health/calls';
import { mockApi, renderAt } from '@/test/render';

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  localStorage.clear();
  document.documentElement.classList.add('dark');
  delete document.documentElement.dataset.domain;
});

const WEIGHT_CHART = 'Weigh-ins over time and the weight goal';

test('shows the weight figures, the goal and fitness age against real age', async () => {
  const calls = mockApi({ 'GET /api/health/body': () => body() });
  renderAt('/health/body');

  expect(await screen.findByText('78.4')).toBeTruthy();
  expect(screen.getAllByText('20 Oct 2026').length).toBeGreaterThan(0);
  expect(screen.getByText('−1.8')).toBeTruthy();
  expect(screen.getByText('3.4 to lose')).toBeTruthy();
  expect(screen.getAllByText('24.1').length).toBeGreaterThan(0);
  expect(screen.getByText('3 weigh-ins')).toBeTruthy();
  expect(screen.getByText('5.5 younger')).toBeTruthy();
  expect(screen.getByText('46 bpm')).toBeTruthy();
  expect(screen.getByText('3 readings')).toBeTruthy();

  expect(pageCalls(calls)[0]?.search.get('days')).toBe('365');
  expect(screen.getByRole('button', { name: '1 year' }).getAttribute('aria-pressed')).toBe('true');
});

test('every chart has a list of its values for a screen reader', async () => {
  mockApi({ 'GET /api/health/body': () => body() });
  renderAt('/health/body');

  const weight = (await screen.findByText(WEIGHT_CHART)).closest('figure') as HTMLElement;
  expect(
    within(weight)
      .getAllByRole('listitem')
      .map((li) => li.textContent),
  ).toEqual(['4 Mar 2026: 80.2 kg', '15 Jul 2026: 79.1 kg', '20 Oct 2026: 78.4 kg', 'Goal: 75 kg']);
  const age = screen.getByText('Fitness age against real age over time').closest('figure');
  expect(within(age as HTMLElement).getAllByRole('listitem')).toHaveLength(3);
});

test('with no weigh-ins it shows a marker, not an empty chart', async () => {
  mockApi({ 'GET /api/health/body': () => emptyBody() });
  renderAt('/health/body');

  expect(await screen.findByText('No weigh-ins')).toBeTruthy();
  expect(screen.getAllByText('No readings').length).toBeGreaterThan(0);
  expect(screen.queryByText(WEIGHT_CHART)).toBeNull();
  expect(screen.queryByText('Goal')).toBeNull();
  expect(screen.queryByText('BMI')).toBeNull();
});

test('with one weigh-in it shows the figure and the count, no chart', async () => {
  mockApi({ 'GET /api/health/body': () => oneWeighIn() });
  renderAt('/health/body');

  expect(await screen.findByText('78.4')).toBeTruthy();
  expect(screen.getByText('1 weigh-in')).toBeTruthy();
  expect(screen.queryByText(WEIGHT_CHART)).toBeNull();
});

test('with two weigh-ins it draws the chart', async () => {
  mockApi({
    'GET /api/health/body': () => {
      const data = body();
      data.weight.points = data.weight.points.slice(1);
      data.weight.summary = { ...data.weight.summary, count: 2, change_kg: -0.7 };
      return data;
    },
  });
  renderAt('/health/body');

  expect(await screen.findByText(WEIGHT_CHART)).toBeTruthy();
  expect(screen.getByText('2 weigh-ins')).toBeTruthy();
});

test('leaves BMI out when none is stored', async () => {
  mockApi({
    'GET /api/health/body': () => {
      const data = body();
      data.weight.summary = { ...data.weight.summary, bmi: null };
      return data;
    },
  });
  renderAt('/health/body');

  await screen.findByText('78.4');
  expect(screen.queryByText('BMI', { selector: 'p' })).toBeNull();
});

test('the period pills ask for 90 days or everything', async () => {
  const calls = mockApi({ 'GET /api/health/body': () => body() });
  renderAt('/health/body');
  await screen.findByText('78.4');

  fireEvent.click(screen.getByRole('button', { name: '90 days' }));
  expect(await screen.findByRole('button', { name: '90 days', pressed: true })).toBeTruthy();
  fireEvent.click(screen.getByRole('button', { name: 'All' }));
  expect(await screen.findByRole('button', { name: 'All', pressed: true })).toBeTruthy();
  expect([...new Set(pageCalls(calls).map((call) => call.search.get('days')))]).toEqual([
    '365',
    '90',
    'all',
  ]);
});
