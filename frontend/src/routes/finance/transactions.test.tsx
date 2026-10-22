import { cleanup, fireEvent, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, test, vi } from 'vitest';
import { account, transaction } from '@/test/fixtures';
import { mockApi, renderAt } from '@/test/render';

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

function api() {
  return mockApi({
    'GET /api/finance/accounts': () => [account],
    'GET /api/finance/transactions': (request) =>
      new URL(request.url).searchParams.get('cursor')
        ? {
            items: [transaction('t3', { counterparty_name: 'Café Exemplo', amount: '-3.5000' })],
            next_cursor: null,
          }
        : {
            items: [
              transaction('t1', {
                status: 'pending',
                counterparty_name: 'Supermercado Exemplo',
                description: 'COMPRA 4450',
              }),
              transaction('t2', { description: 'SALARIO OUTUBRO', amount: '2100.0000' }),
            ],
            next_cursor: 'c1',
          },
  });
}

test('lists transactions and loads more pages', async () => {
  const calls = api();

  renderAt('/finance/transactions');

  expect(await screen.findByText('Supermercado Exemplo')).toBeDefined();
  expect(screen.getByText('COMPRA 4450')).toBeDefined();
  expect(screen.getByText('Pending')).toBeDefined();
  expect(screen.getByText(/2,100\.00/)).toBeDefined();
  fireEvent.click(screen.getByRole('button', { name: 'Load more' }));

  expect(await screen.findByText('Café Exemplo')).toBeDefined();
  expect(screen.queryByRole('button', { name: 'Load more' })).toBeNull();
  const pages = calls.filter((call) => call.path === '/api/finance/transactions');
  // Strict mode mounts twice, and the abort on the first unmount re-requests a page; pages matter.
  const cursors = new Set(pages.map((call) => call.search.get('cursor')));
  expect([...cursors]).toEqual([null, 'c1']);
});

test('search goes into the URL and the query', async () => {
  const calls = api();
  const { router } = renderAt('/finance/transactions?q=cafe');

  const input = (await screen.findByLabelText('Search transactions')) as HTMLInputElement;
  expect(input.value).toBe('cafe');
  fireEvent.change(input, { target: { value: 'padaria' } });

  await waitFor(() => expect(router.state.location.search).toEqual({ q: 'padaria' }));
  await waitFor(() => expect(calls.some((call) => call.search.get('q') === 'padaria')).toBe(true));
  expect(calls.find((call) => call.path === '/api/finance/transactions')?.search.get('q')).toBe(
    'cafe',
  );
});
