import { cleanup, fireEvent, screen, waitFor, within } from '@testing-library/react';
import { afterEach, expect, test, vi } from 'vitest';
import { categories, merchant } from '@/test/fixtures';
import { mockApi, renderAt } from '@/test/render';

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const merchants = [
  merchant('m1', 'Continente', {
    transactions: 12,
    default_category_id: 'c-groceries',
    aliases: ['continente', 'continente modelo', 'cont bom dia', 'cont lisboa'],
  }),
  merchant('m2', 'Pingo Doce', { transactions: 4 }),
  merchant('m3', 'Continente Online', { transactions: 1 }),
];

function api(overrides: Record<string, (request: Request) => unknown> = {}) {
  return mockApi({
    'GET /api/finance/categories': () => categories,
    'GET /api/finance/counterparties': () => merchants,
    ...overrides,
  });
}

test('lists merchants with their default category and bank names', async () => {
  api();

  renderAt('/finance/merchants');

  expect(await screen.findByText('Pingo Doce')).toBeDefined();
  expect(
    screen.getByText('Bank names: continente, continente modelo, cont bom dia +1'),
  ).toBeDefined();
  expect(screen.getByRole('button', { name: 'Groceries' })).toBeDefined();
  expect(screen.getAllByRole('button', { name: 'No default' })).toHaveLength(2);
  expect(
    screen.getByRole('link', { name: '12 transactions with Continente' }).getAttribute('href'),
  ).toBe('/finance/transactions?counterparty=m1');
});

test('searches by name and by the bank’s spelling', async () => {
  api();

  renderAt('/finance/merchants');
  await screen.findByText('Pingo Doce');
  fireEvent.change(screen.getByLabelText('Search merchants'), { target: { value: 'cont lis' } });

  expect(screen.getByText('Continente')).toBeDefined();
  expect(screen.queryByText('Pingo Doce')).toBeNull();
});

test('sets and clears the default category', async () => {
  const calls = api({ 'PATCH /api/finance/counterparties/m2': () => merchants[1] });

  renderAt('/finance/merchants');
  const row = (await screen.findByText('Pingo Doce')).closest('tr') as HTMLElement;
  fireEvent.click(within(row).getByRole('button', { name: 'No default' }));
  fireEvent.click(within(await screen.findByRole('listbox')).getByText('Groceries'));
  await waitFor(() =>
    expect(calls.find((call) => call.method === 'PATCH')?.body).toEqual({
      default_category_id: 'c-groceries',
    }),
  );

  const first = screen.getByRole('button', { name: 'Groceries' });
  fireEvent.click(first);
  fireEvent.click(within(await screen.findByRole('listbox')).getByText('No default'));
  await waitFor(() =>
    expect(calls.filter((call) => call.method === 'PATCH').at(-1)).toMatchObject({
      path: '/api/finance/counterparties/m1',
      body: { default_category_id: null },
    }),
  );
});

test('renames a merchant', async () => {
  const calls = api({ 'PATCH /api/finance/counterparties/m2': () => merchants[1] });

  renderAt('/finance/merchants');
  fireEvent.click(await screen.findByRole('button', { name: 'Rename Pingo Doce' }));
  const dialog = await screen.findByRole('dialog');
  fireEvent.change(within(dialog).getByLabelText('Name'), { target: { value: 'Pingo Doce Lda' } });
  fireEvent.click(within(dialog).getByRole('button', { name: 'Rename' }));

  await waitFor(() =>
    expect(calls.find((call) => call.method === 'PATCH')?.body).toEqual({ name: 'Pingo Doce Lda' }),
  );
});

test('merges a merchant into another', async () => {
  const calls = api({ 'POST /api/finance/counterparties/m3/merge': () => merchants[0] });

  renderAt('/finance/merchants');
  fireEvent.click(await screen.findByRole('button', { name: 'Merge Continente Online' }));
  const dialog = await screen.findByRole('dialog');
  expect(within(dialog).getByRole('button', { name: 'Merge' }).hasAttribute('disabled')).toBe(true);

  fireEvent.click(within(dialog).getByRole('button', { name: 'Merge into…' }));
  const list = await screen.findByRole('listbox');
  expect(within(list).queryByText('Continente Online')).toBeNull(); // not into itself
  fireEvent.click(within(list).getByText('Continente'));
  fireEvent.click(await within(dialog).findByRole('button', { name: 'Merge into Continente' }));

  await waitFor(() =>
    expect(calls.find((call) => call.method === 'POST')?.body).toEqual({ into_id: 'm1' }),
  );
  expect(await screen.findByText('Merged into Continente.')).toBeDefined();
});
