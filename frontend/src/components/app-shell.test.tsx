import { cleanup, fireEvent, screen, waitFor, within } from '@testing-library/react';
import { afterEach, expect, test, vi } from 'vitest';
import { connection } from '@/test/fixtures';
import { mockApi, renderAt } from '@/test/render';

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  localStorage.clear();
  document.documentElement.classList.add('dark');
});

test('skips past the navigation to the page', async () => {
  mockApi({});

  renderAt('/');

  const skip = await screen.findByRole('link', { name: 'Skip to content' });
  expect(skip.getAttribute('href')).toBe('#main');
  expect(document.getElementById('main')?.tagName).toBe('MAIN');
});

test('the sidebar lists the domain, its pages in groups, and marks the current page', async () => {
  mockApi({});

  renderAt('/finance/rules');

  const sidebar = within(await screen.findByRole('navigation', { name: 'Finance' }));
  expect(screen.getByRole('button', { name: 'Domain: Finance' })).toBeDefined();
  expect(sidebar.getByText('Organise')).toBeDefined();
  expect(sidebar.getByText('Sources')).toBeDefined();
  expect(sidebar.getByRole('link', { name: 'Rules' }).getAttribute('aria-current')).toBe('page');
  expect(sidebar.getByRole('link', { name: 'Overview' }).getAttribute('aria-current')).toBeNull();
});

test('on a phone, the tab bar holds the main pages and More lists the rest', async () => {
  mockApi({});

  renderAt('/finance/budgets');

  const tabs = within(await screen.findByRole('navigation', { name: 'Tabs' }));
  expect(tabs.getAllByRole('link').map((link) => link.textContent)).toEqual([
    'Overview',
    'Transactions',
    'Budgets',
    'More',
  ]);
  expect(tabs.getByRole('link', { name: 'Budgets' }).getAttribute('aria-current')).toBe('page');

  fireEvent.click(tabs.getByRole('link', { name: 'More' }));
  expect(await screen.findByRole('heading', { name: 'More' })).toBeDefined();
  const main = within(screen.getByRole('main'));
  expect(main.getByRole('link', { name: 'Recurring' })).toBeDefined();
  expect(main.getByRole('link', { name: 'Bank connections' })).toBeDefined();
  expect(main.queryByRole('link', { name: 'Budgets' })).toBeNull();
  expect(tabs.getByRole('link', { name: 'More' }).getAttribute('aria-current')).toBe('page');

  fireEvent.click(main.getByRole('link', { name: 'Recurring' }));
  expect(await screen.findByRole('heading', { name: 'Recurring payments' })).toBeDefined();
  expect(tabs.getByRole('link', { name: 'More' }).getAttribute('aria-current')).toBe('page');
});

test('dark by default; the theme switch changes it and is remembered', async () => {
  mockApi({});

  renderAt('/');

  const theme = within((await screen.findAllByRole('group', { name: 'Theme' }))[0] as HTMLElement);
  expect(theme.getByRole('button', { name: 'Dark' }).getAttribute('aria-pressed')).toBe('true');
  expect(document.documentElement.classList.contains('dark')).toBe(true);

  fireEvent.click(theme.getByRole('button', { name: 'Light' }));
  await waitFor(() => expect(document.documentElement.classList.contains('dark')).toBe(false));

  cleanup();
  renderAt('/');
  const again = within((await screen.findAllByRole('group', { name: 'Theme' }))[0] as HTMLElement);
  expect(again.getByRole('button', { name: 'Light' }).getAttribute('aria-pressed')).toBe('true');
});

test('Ctrl K opens search, which goes to a page', async () => {
  mockApi({});

  renderAt('/');

  await screen.findByRole('heading', { name: 'Overview' });
  fireEvent.keyDown(window, { key: 'k', ctrlKey: true });
  const search = await screen.findByRole('dialog', { name: 'Search' });
  fireEvent.click(within(search).getByRole('option', { name: 'Merchants' }));
  expect(await screen.findByRole('heading', { name: 'Merchants' })).toBeDefined();
  await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
});

test('the page header says how fresh the data is, or which connection needs a look', async () => {
  mockApi({
    'GET /api/finance/connections': () => [
      connection({ last_synced_at: new Date(Date.now() - 2 * 3_600_000).toISOString() }),
      connection({ id: 'c2', institution_name: 'Revolut' }),
    ],
  });

  renderAt('/finance/categories');

  const header = within(
    (await screen.findByRole('heading', { name: 'Categories' })).parentElement as HTMLElement,
  );
  expect(await header.findByText('Synced 2 hours ago')).toBeDefined();

  cleanup();
  mockApi({
    'GET /api/finance/connections': () => [
      connection(),
      connection({ id: 'c2', institution_name: 'Revolut', status: 'expired' }),
    ],
  });
  renderAt('/finance/categories');
  expect(await screen.findByRole('link', { name: 'Revolut needs a look' })).toBeDefined();
});
