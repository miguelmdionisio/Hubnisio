import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, beforeAll, expect, test, vi } from 'vitest';
import { client } from '../api/client.gen';
import { HomePage } from './home';

beforeAll(() => {
  // Node's fetch can't resolve the relative URLs a browser would.
  client.setConfig({ baseUrl: 'http://localhost' });
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

function renderHome() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <HomePage />
    </QueryClientProvider>,
  );
}

test('shows the API and database status', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => Response.json({ status: 'ok', database: 'ok' })),
  );
  renderHome();
  expect(await screen.findByText('API ok, database ok.')).toBeDefined();
});

test('says so when the API is unreachable', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => {
      throw new TypeError('Failed to fetch');
    }),
  );
  renderHome();
  expect(await screen.findByText('The API is unreachable.')).toBeDefined();
});
