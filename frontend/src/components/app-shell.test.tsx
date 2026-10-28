import { cleanup, fireEvent, screen, waitFor, within } from '@testing-library/react';
import { afterEach, expect, test, vi } from 'vitest';
import { mockApi, renderAt } from '@/test/render';

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  localStorage.clear();
});

test('skips past the navigation to the page', async () => {
  mockApi({});

  renderAt('/');

  const skip = await screen.findByRole('link', { name: 'Skip to content' });
  expect(skip.getAttribute('href')).toBe('#main');
  expect(document.getElementById('main')?.tagName).toBe('MAIN');
});

test('opens the navigation from the menu on a phone, and closes it on the way to a page', async () => {
  mockApi({});

  renderAt('/');

  fireEvent.click(await screen.findByRole('button', { name: 'Menu' }));
  const menu = await screen.findByRole('dialog', { name: 'Hubnisio' });
  expect(within(menu).getByRole('button', { name: 'Household' })).toBeDefined();
  fireEvent.click(within(menu).getByRole('link', { name: 'Budgets' }));
  await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
});
