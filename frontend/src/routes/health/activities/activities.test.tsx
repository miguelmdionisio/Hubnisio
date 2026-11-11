import { cleanup, fireEvent, screen, waitFor, within } from '@testing-library/react';
import { afterEach, expect, test, vi } from 'vitest';
import { activityList, row } from '@/test/health/activities';
import { mockApi, renderAt } from '@/test/render';

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  localStorage.clear();
  document.documentElement.classList.add('dark');
  delete document.documentElement.dataset.domain;
});

test('lists activities by day with distance, time, load and the sport figure', async () => {
  const calls = mockApi({ 'GET /api/health/activities': () => activityList() });
  renderAt('/health/activities');

  const sunday = await screen.findByRole('region', { name: 'Sun 8 Nov' });
  const rows = within(sunday).getAllByRole('link');
  expect(rows.map((link) => link.textContent)).toEqual([
    'Long run08:12 · 5:14 /km21.4 km1:52:10 · load 182',
    'Evening ride18:30 · 36 km/h36.0 km1:00:00 · load 64',
  ]);
  expect(rows[0]?.getAttribute('href')).toBe('/health/activities/100');
  const friday = screen.getByRole('region', { name: 'Fri 6 Nov' });
  // no load yet: the row says nothing about it
  expect(within(friday).getByRole('link').textContent).toBe('Pool07:00 · 3:00 /100 m1.0 km30:00');
  expect(calls[0]?.search.get('limit')).toBe('30');
  expect(calls[0]?.search.get('sport')).toBeNull();
});

test('a multisport activity is one row naming its legs', async () => {
  mockApi({
    'GET /api/health/activities': () =>
      activityList([
        row({
          id: 200,
          sport: 'multi_sport',
          group: 'other',
          name: 'Sprint triathlon',
          legs: [
            row({ id: 201, group: 'swim' }),
            row({ id: 202, group: 'bike' }),
            row({ id: 203, group: 'run' }),
          ],
        }),
      ]),
  });
  renderAt('/health/activities');

  expect(await screen.findByRole('img', { name: 'Legs: Swim, Bike, Run' })).toBeTruthy();
  const rows = screen
    .getAllByRole('link')
    .filter((link) => link.getAttribute('href')?.startsWith('/health/activities/'));
  expect(rows.map((link) => link.getAttribute('href'))).toEqual(['/health/activities/200']);
});

test('sport pills narrow the list and All clears them', async () => {
  const calls = mockApi({ 'GET /api/health/activities': () => activityList() });
  const { router } = renderAt('/health/activities');
  await screen.findByRole('region', { name: 'Sun 8 Nov' });

  fireEvent.click(screen.getByRole('button', { name: 'Run' }));
  await waitFor(() => expect(calls.at(-1)?.search.get('sport')).toBe('run'));
  expect(router.state.location.search).toMatchObject({ sport: 'run' });
  expect(screen.getByRole('button', { name: 'Run' }).getAttribute('aria-pressed')).toBe('true');

  fireEvent.click(screen.getByRole('button', { name: 'All' }));
  await waitFor(() => expect(router.state.location.search).not.toHaveProperty('sport', 'run'));
  expect(screen.getByRole('button', { name: 'All' }).getAttribute('aria-pressed')).toBe('true');
});

test('a period sets the first day, and last year bounds both ends', async () => {
  const calls = mockApi({ 'GET /api/health/activities': () => activityList() });
  renderAt('/health/activities');
  await screen.findByRole('region', { name: 'Sun 8 Nov' });

  fireEvent.click(screen.getByRole('button', { name: 'Period' }));
  fireEvent.click(await screen.findByRole('button', { name: 'Last year' }));

  const year = new Date().getFullYear() - 1;
  await waitFor(() => expect(calls.at(-1)?.search.get('from')).toBe(`${year}-01-01`));
  expect(calls.at(-1)?.search.get('to')).toBe(`${year}-12-31`);
});

test('searching asks for the text once typing pauses', async () => {
  const calls = mockApi({ 'GET /api/health/activities': () => activityList() });
  renderAt('/health/activities');
  await screen.findByRole('region', { name: 'Sun 8 Nov' });

  fireEvent.change(screen.getByRole('textbox', { name: 'Search activities' }), {
    target: { value: 'long' },
  });

  await waitFor(() => expect(calls.at(-1)?.search.get('q')).toBe('long'));
});

test('loads the next page with the cursor', async () => {
  const calls = mockApi({
    'GET /api/health/activities': (request) =>
      new URL(request.url).searchParams.get('cursor')
        ? activityList([row({ id: 300, name: 'Older run', start: '2026-10-01T07:00:00' })])
        : activityList([row()], 'abc.1'),
  });
  renderAt('/health/activities');

  fireEvent.click(await screen.findByRole('button', { name: 'Load more' }));

  expect(await screen.findByText('Older run')).toBeTruthy();
  expect(calls.at(-1)?.search.get('cursor')).toBe('abc.1');
  expect(screen.queryByRole('button', { name: 'Load more' })).toBeNull();
});

test('says so when nothing matches', async () => {
  mockApi({ 'GET /api/health/activities': () => activityList([]) });
  renderAt('/health/activities');

  expect(await screen.findByText('No activities')).toBeTruthy();
});
