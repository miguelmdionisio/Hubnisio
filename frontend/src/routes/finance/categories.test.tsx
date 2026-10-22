import { cleanup, fireEvent, screen, waitFor, within } from '@testing-library/react';
import { afterEach, expect, test, vi } from 'vitest';
import type { CategoryGroupOut } from '@/api/types.gen';
import { categories } from '@/test/fixtures';
import { chooseOption, mockApi, renderAt } from '@/test/render';

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const [food] = categories as [CategoryGroupOut];
const home: CategoryGroupOut = {
  ...food,
  id: 'g-home',
  name: 'Housing',
  transactions: 2,
  children: [],
};
const updated = { id: 'c-groceries', name: 'Groceries', kind: 'expense' as const };

function api(overrides: Record<string, (request: Request) => unknown> = {}) {
  return mockApi({
    'GET /api/finance/categories': () => [food, home],
    ...overrides,
  });
}

test('shows the tree, with archived categories behind a switch', async () => {
  api();

  renderAt('/finance/categories');

  expect(await screen.findByText('Groceries')).toBeDefined();
  expect(screen.getByText('Housing')).toBeDefined();
  expect(screen.getByText('3 transactions')).toBeDefined(); // the group's total
  expect(screen.queryByText('Old stuff')).toBeNull();

  fireEvent.click(screen.getByRole('switch', { name: 'Show archived' }));
  expect(screen.getByText('Old stuff')).toBeDefined();
  expect(screen.getByRole('button', { name: 'Unarchive Old stuff' })).toBeDefined();
});

test('adds a category to a group', async () => {
  const calls = api({
    'POST /api/finance/categories': () => ({ ...updated, id: 'c-new', name: 'Takeaway' }),
  });

  renderAt('/finance/categories');
  const [addToFood] = await screen.findAllByRole('button', { name: 'Add category' });
  fireEvent.click(addToFood as HTMLElement);
  const dialog = await screen.findByRole('dialog');
  fireEvent.change(within(dialog).getByLabelText('Category name'), {
    target: { value: ' Takeaway ' },
  });
  fireEvent.click(within(dialog).getByRole('button', { name: 'Create category' }));

  await waitFor(() =>
    expect(calls.find((call) => call.method === 'POST')?.body).toEqual({
      name: 'Takeaway',
      parent_id: 'g-food',
    }),
  );
});

test('creates an income group', async () => {
  const calls = api({ 'POST /api/finance/categories': () => ({ ...updated, id: 'g-new' }) });

  renderAt('/finance/categories');
  fireEvent.click(await screen.findByRole('button', { name: 'New group' }));
  const dialog = await screen.findByRole('dialog');
  fireEvent.change(within(dialog).getByLabelText('Group name'), { target: { value: 'Side jobs' } });
  await chooseOption(within(dialog).getByRole('combobox', { name: 'Holds' }), 'Income');
  fireEvent.click(within(dialog).getByRole('button', { name: 'Create group' }));

  await waitFor(() =>
    expect(calls.find((call) => call.method === 'POST')?.body).toEqual({
      name: 'Side jobs',
      kind: 'income',
    }),
  );
});

test('renames and archives', async () => {
  const calls = api({ 'PATCH /api/finance/categories/c-groceries': () => updated });

  renderAt('/finance/categories');
  fireEvent.click(await screen.findByRole('button', { name: 'Rename Groceries' }));
  const dialog = await screen.findByRole('dialog');
  fireEvent.change(within(dialog).getByLabelText('Name'), { target: { value: 'Supermarket' } });
  fireEvent.click(within(dialog).getByRole('button', { name: 'Rename' }));
  await waitFor(() =>
    expect(calls.find((call) => call.method === 'PATCH')?.body).toEqual({ name: 'Supermarket' }),
  );

  fireEvent.click(await screen.findByRole('button', { name: 'Archive Groceries' }));
  await waitFor(() =>
    expect(calls.filter((call) => call.method === 'PATCH').at(-1)?.body).toEqual({
      archived: true,
    }),
  );
});

test('moves a category to another group', async () => {
  const calls = api({ 'PATCH /api/finance/categories/c-groceries': () => updated });

  renderAt('/finance/categories');
  fireEvent.click(await screen.findByRole('button', { name: 'Move Groceries' }));
  const dialog = await screen.findByRole('dialog');
  expect(within(dialog).getByRole('button', { name: 'Move' }).hasAttribute('disabled')).toBe(true);
  await chooseOption(within(dialog).getByRole('combobox', { name: 'New group' }), 'Housing');
  fireEvent.click(within(dialog).getByRole('button', { name: 'Move' }));

  await waitFor(() =>
    expect(calls.find((call) => call.method === 'PATCH')?.body).toEqual({ parent_id: 'g-home' }),
  );
});

test("says why a category in use can't be deleted", async () => {
  const calls = api({
    'DELETE /api/finance/categories/c-groceries': () =>
      Response.json({ detail: 'This category is in use. Archive it instead.' }, { status: 409 }),
    'DELETE /api/finance/categories/g-home': () => new Response(null, { status: 204 }),
  });

  renderAt('/finance/categories');
  fireEvent.click(await screen.findByRole('button', { name: 'Delete Groceries' }));
  expect(await screen.findByText('This category is in use. Archive it instead.')).toBeDefined();

  fireEvent.click(screen.getByRole('button', { name: 'Delete Housing' }));
  await waitFor(() =>
    expect(calls.some((call) => call.path.endsWith('/g-home') && call.method === 'DELETE')).toBe(
      true,
    ),
  );
});
