import { cleanup, fireEvent, screen, waitFor, within } from '@testing-library/react';
import { afterEach, expect, test, vi } from 'vitest';
import { HEALTH_PAGES } from '@/test/health/pages';
import { mockApi, renderAt } from '@/test/render';

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  localStorage.clear();
  document.documentElement.classList.add('dark');
  delete document.documentElement.dataset.domain;
});

test('the Health sidebar lists its pages in groups', async () => {
  const calls = mockApi({});

  renderAt('/health/sleep');

  const sidebar = within(await screen.findByRole('navigation', { name: 'Health' }));
  expect(screen.getByRole('button', { name: 'Domain: Health' })).toBeDefined();
  expect(sidebar.getAllByRole('link').map((link) => link.textContent)).toEqual(
    HEALTH_PAGES.map((page) => page.title),
  );
  expect(sidebar.getByText('Analyse')).toBeDefined();
  expect(sidebar.getByText('Sources')).toBeDefined();
  expect(sidebar.getByRole('link', { name: 'Sleep' }).getAttribute('aria-current')).toBe('page');
  expect(sidebar.getByRole('link', { name: 'Today' }).getAttribute('aria-current')).toBeNull();
  // No Finance bank sync, no household view, no API calls at all.
  expect(screen.queryByRole('group', { name: 'View' })).toBeNull();
  expect(calls).toEqual([]);
});

test('the Health tab bar holds four pages and More', async () => {
  mockApi({});

  renderAt('/health/recovery');

  const tabs = within(await screen.findByRole('navigation', { name: 'Tabs' }));
  expect(tabs.getAllByRole('link').map((link) => link.textContent)).toEqual([
    'Today',
    'Activities',
    'Sleep',
    'Recovery',
    'More',
  ]);
  expect(tabs.getByRole('link', { name: 'Recovery' }).getAttribute('aria-current')).toBe('page');
});

test('the switcher moves between Finance and Health', async () => {
  mockApi({});

  renderAt('/health/body');

  fireEvent.click(await screen.findByRole('button', { name: 'Domain: Health' }));
  fireEvent.click(await screen.findByRole('button', { name: 'Finance' }));
  expect(await screen.findByRole('heading', { name: 'Overview' })).toBeDefined();
  expect(screen.getByRole('navigation', { name: 'Finance' })).toBeDefined();

  fireEvent.click(screen.getByRole('button', { name: 'Domain: Finance' }));
  fireEvent.click(await screen.findByRole('button', { name: 'Health' }));
  expect(await screen.findByRole('heading', { name: 'Today' })).toBeDefined();
  expect(screen.getByRole('navigation', { name: 'Health' })).toBeDefined();
});

// Recovery has its own tests (routes/health/recovery).
test.each(HEALTH_PAGES.filter((page) => page.title !== 'Recovery'))(
  '$title renders its title and an honest gap',
  async ({ to, title }) => {
    mockApi({});

    renderAt(to);

    expect(await screen.findByRole('heading', { name: title })).toBeDefined();
    expect(screen.getByText('No data yet')).toBeDefined();
    expect(screen.queryByText(/Synced/)).toBeNull();
  },
);

test('More lists the pages the tabs leave out and the domains to switch to', async () => {
  mockApi({});

  renderAt('/health/more');

  expect(await screen.findByRole('heading', { name: 'More' })).toBeDefined();
  const main = within(screen.getByRole('main'));
  for (const name of ['Training', 'Performance', 'Body', 'Garmin']) {
    expect(main.getByRole('link', { name })).toBeDefined();
  }
  for (const name of ['Today', 'Activities', 'Sleep', 'Recovery']) {
    expect(main.queryByRole('link', { name })).toBeNull();
  }
  expect(main.getByRole('link', { name: /Health/ }).getAttribute('aria-current')).toBe('page');

  fireEvent.click(main.getByRole('link', { name: /Finance/ }));
  expect(await screen.findByRole('heading', { name: 'Overview' })).toBeDefined();
});

test('the accent follows the domain', async () => {
  mockApi({});

  const { router } = renderAt('/health');
  await screen.findByRole('heading', { name: 'Today' });
  expect(document.documentElement.dataset.domain).toBe('health');

  await router.navigate({ to: '/finance/rules' });
  await screen.findByRole('heading', { name: 'Rules' });
  await waitFor(() => expect(document.documentElement.dataset.domain).toBe('finance'));
});

test('search lists Health pages', async () => {
  mockApi({});

  renderAt('/');

  await screen.findByRole('heading', { name: 'Overview' });
  fireEvent.keyDown(window, { key: 'k', ctrlKey: true });
  const search = await screen.findByRole('dialog', { name: 'Search' });
  fireEvent.click(within(search).getByRole('option', { name: 'Garmin' }));
  expect(await screen.findByRole('heading', { name: 'Garmin' })).toBeDefined();
});
