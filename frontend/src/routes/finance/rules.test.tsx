import { cleanup, fireEvent, screen, waitFor, within } from '@testing-library/react';
import { afterEach, expect, test, vi } from 'vitest';
import { account, categories, merchant, rule, transaction } from '@/test/fixtures';
import { chooseOption, mockApi, renderAt } from '@/test/render';

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const groceries = rule('r1', 'Groceries', { position: 0 });
const exchange = rule('r2', 'Currency exchange', {
  position: 1,
  conditions: [{ field: 'bank_code', op: 'is', value: 'EXCHANGE' }],
  actions: [{ type: 'set_kind', kind: 'transfer' }],
  stop_processing: true,
});

function api(overrides: Record<string, (request: Request) => unknown> = {}) {
  return mockApi({
    'GET /api/finance/accounts': () => [account],
    'GET /api/finance/categories': () => categories,
    'GET /api/finance/counterparties': () => [merchant('m1', 'Continente')],
    'GET /api/finance/rules': () => [groceries, exchange],
    'POST /api/finance/rules/preview': () => ({
      matches: 3,
      examples: [transaction('t1', { description: 'COMPRA PADARIA', amount: '-4.5000' })],
    }),
    ...overrides,
  });
}

test('lists the rules in order, in words', async () => {
  api();

  renderAt('/finance/rules');

  expect(
    await screen.findByText(/Description contains “continente” → category Groceries/),
  ).toBeDefined();
  expect(screen.getByText(/Bank code is “EXCHANGE” → treat as a transfer/)).toBeDefined();
  expect(screen.getByText('Stops here')).toBeDefined();
});

test('turns a rule off', async () => {
  const calls = api({ 'PUT /api/finance/rules/r1': () => groceries });

  renderAt('/finance/rules');
  fireEvent.click(await screen.findByRole('switch', { name: 'Enable Groceries' }));

  await waitFor(() =>
    expect(calls.find((call) => call.method === 'PUT')?.body).toEqual({
      name: 'Groceries',
      enabled: false,
      match: 'all',
      conditions: groceries.conditions,
      actions: groceries.actions,
      stop_processing: false,
    }),
  );
});

test('reorders with the arrows', async () => {
  const calls = api({ 'PUT /api/finance/rules-order': () => [exchange, groceries] });

  renderAt('/finance/rules');
  expect(
    (await screen.findByRole('button', { name: 'Move Groceries up' })).hasAttribute('disabled'),
  ).toBe(true);
  fireEvent.click(screen.getByRole('button', { name: 'Move Currency exchange up' }));

  await waitFor(() =>
    expect(calls.find((call) => call.method === 'PUT')?.body).toEqual({ ids: ['r2', 'r1'] }),
  );
});

test('runs the rules now and reports', async () => {
  const calls = api({
    'POST /api/finance/rules/run': () => ({
      processed: 120,
      categorized: 90,
      counterparties_created: 0,
    }),
  });

  renderAt('/finance/rules');
  fireEvent.click(await screen.findByRole('button', { name: 'Run rules now' }));

  expect(
    await screen.findByText('Checked 120 transactions: 90 now have a category.'),
  ).toBeDefined();
  expect(calls.some((call) => call.path === '/api/finance/rules/run')).toBe(true);
});

test('deletes a rule after confirming', async () => {
  const calls = api({ 'DELETE /api/finance/rules/r2': () => new Response(null, { status: 204 }) });

  renderAt('/finance/rules');
  fireEvent.click(await screen.findByRole('button', { name: 'Delete Currency exchange' }));
  expect(calls.some((call) => call.method === 'DELETE')).toBe(false);
  const dialog = await screen.findByRole('dialog');
  fireEvent.click(within(dialog).getByRole('button', { name: 'Delete rule' }));

  await waitFor(() => expect(calls.some((call) => call.method === 'DELETE')).toBe(true));
});

test('creates a rule, previewing what it matches', async () => {
  const calls = api({ 'POST /api/finance/rules': () => groceries });

  renderAt('/finance/rules');
  fireEvent.click(await screen.findByRole('button', { name: 'New rule' }));
  const dialog = await screen.findByRole('dialog');
  const save = within(dialog).getByRole('button', { name: 'Save rule' });
  expect(save.hasAttribute('disabled')).toBe(true);
  expect(within(dialog).getByText(/Fill in every condition/)).toBeDefined();

  fireEvent.change(within(dialog).getByLabelText('Name'), { target: { value: 'Bakery' } });
  fireEvent.change(within(dialog).getByLabelText('Condition 1 value'), {
    target: { value: 'padaria' },
  });
  expect(await within(dialog).findByText('Matches 3 transactions')).toBeDefined();
  expect(within(dialog).getByText(/COMPRA PADARIA/)).toBeDefined();
  expect(calls.find((call) => call.path === '/api/finance/rules/preview')?.body).toEqual({
    match: 'all',
    conditions: [{ field: 'description', op: 'contains', value: 'padaria' }],
  });

  expect(save.hasAttribute('disabled')).toBe(true); // still no category
  fireEvent.click(within(dialog).getByRole('button', { name: 'Choose a category' }));
  fireEvent.click(within(await screen.findByRole('listbox')).getByText('Groceries'));
  fireEvent.click(save);

  await waitFor(() =>
    expect(
      calls.find((call) => call.method === 'POST' && call.path.endsWith('/rules'))?.body,
    ).toEqual({
      name: 'Bakery',
      enabled: true,
      match: 'all',
      conditions: [{ field: 'description', op: 'contains', value: 'padaria' }],
      actions: [{ type: 'set_category', category_id: 'c-groceries' }],
      stop_processing: false,
    }),
  );
});

test('creates the merchant a rule sets, from the picker', async () => {
  const known = [merchant('m1', 'Continente'), merchant('m2', 'Uber Eats')];
  const uber = merchant('m3', 'Uber', { aliases: [] });
  const calls = api({
    'GET /api/finance/counterparties': () => known,
    'POST /api/finance/counterparties': () => {
      known.push(uber);
      return Response.json(uber, { status: 201 });
    },
    'POST /api/finance/rules': () => groceries,
  });

  renderAt('/finance/rules');
  fireEvent.click(await screen.findByRole('button', { name: 'New rule' }));
  const dialog = await screen.findByRole('dialog');
  await chooseOption(
    within(dialog).getByRole('combobox', { name: 'Action 1' }),
    'Set the merchant',
  );
  fireEvent.change(within(dialog).getByLabelText('Name'), { target: { value: 'Uber' } });
  fireEvent.change(within(dialog).getByLabelText('Condition 1 value'), {
    target: { value: 'uber' },
  });
  await within(dialog).findByText('Matches 3 transactions');

  fireEvent.click(within(dialog).getByRole('button', { name: 'Choose a merchant' }));
  const search = await screen.findByPlaceholderText('Search merchants');
  fireEvent.change(search, { target: { value: 'uber eats' } });
  expect(screen.queryByText(/Create/)).toBeNull(); // that one exists
  fireEvent.change(search, { target: { value: 'Uber' } });
  fireEvent.click(await screen.findByText('Create “Uber”'));

  expect(await within(dialog).findByRole('button', { name: 'Uber' })).toBeDefined();
  expect(
    calls.find((call) => call.method === 'POST' && call.path.endsWith('/counterparties'))?.body,
  ).toEqual({ name: 'Uber' });
  fireEvent.click(within(dialog).getByRole('button', { name: 'Save rule' }));
  await waitFor(() =>
    expect(
      calls.find((call) => call.method === 'POST' && call.path.endsWith('/rules'))?.body,
    ).toMatchObject({ actions: [{ type: 'set_counterparty', counterparty_id: 'm3' }] }),
  );
});

test('builds amount, direction and kind rules', async () => {
  const calls = api({ 'POST /api/finance/rules': () => groceries });

  renderAt('/finance/rules');
  fireEvent.click(await screen.findByRole('button', { name: 'New rule' }));
  const dialog = await screen.findByRole('dialog');
  fireEvent.change(within(dialog).getByLabelText('Name'), { target: { value: 'Big top-ups' } });

  await chooseOption(within(dialog).getByRole('combobox', { name: 'Condition 1 field' }), /Amount/);
  await chooseOption(
    within(dialog).getByRole('combobox', { name: 'Condition 1 operator' }),
    'is between',
  );
  fireEvent.change(within(dialog).getByLabelText('Condition 1 value'), {
    target: { value: '10,5' },
  });
  fireEvent.change(within(dialog).getByLabelText('Condition 1 upper value'), {
    target: { value: '50' },
  });

  fireEvent.click(within(dialog).getByRole('button', { name: 'Add condition' }));
  await chooseOption(
    within(dialog).getByRole('combobox', { name: 'Condition 2 field' }),
    'Direction',
  );
  await chooseOption(within(dialog).getByRole('combobox', { name: 'Match' }), 'any');

  await chooseOption(within(dialog).getByRole('combobox', { name: 'Action 1' }), 'Treat as');
  await chooseOption(within(dialog).getByRole('combobox', { name: 'Action 1 kind' }), 'income');
  fireEvent.click(within(dialog).getByRole('switch', { name: /Stop processing/ }));
  fireEvent.click(within(dialog).getByRole('button', { name: 'Save rule' }));

  await waitFor(() =>
    expect(
      calls.find((call) => call.method === 'POST' && call.path.endsWith('/rules'))?.body,
    ).toEqual({
      name: 'Big top-ups',
      enabled: true,
      match: 'any',
      conditions: [
        { field: 'amount', op: 'between', value: ['10.5', '50'] },
        { field: 'direction', op: 'is', value: 'out' },
      ],
      actions: [{ type: 'set_kind', kind: 'income' }],
      stop_processing: true,
    }),
  );
});

test('edits an existing rule', async () => {
  const calls = api({ 'PUT /api/finance/rules/r1': () => groceries });

  renderAt('/finance/rules');
  fireEvent.click(await screen.findByRole('button', { name: 'Edit Groceries' }));
  const dialog = await screen.findByRole('dialog');
  const value = within(dialog).getByLabelText('Condition 1 value') as HTMLInputElement;
  expect(value.value).toBe('continente');
  expect(within(dialog).getByRole('button', { name: 'Groceries' })).toBeDefined();
  fireEvent.change(value, { target: { value: 'continente modelo' } });
  fireEvent.click(within(dialog).getByRole('button', { name: 'Save rule' }));

  await waitFor(() =>
    expect(calls.find((call) => call.method === 'PUT')?.body).toMatchObject({
      name: 'Groceries',
      conditions: [{ field: 'description', op: 'contains', value: 'continente modelo' }],
    }),
  );
});
