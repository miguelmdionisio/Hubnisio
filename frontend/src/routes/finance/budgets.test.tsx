import { cleanup, fireEvent, screen, waitFor, within } from '@testing-library/react';
import { afterEach, expect, test, vi } from 'vitest';
import type { CategoryGroupOut } from '@/api/types.gen';
import { currentMonth } from '@/lib/months';
import { budget, budgetsOut, categories, overallBudget } from '@/test/fixtures';
import { chooseOption, mockApi, renderAt } from '@/test/render';

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const [food] = categories as [CategoryGroupOut];
const housing: CategoryGroupOut = {
  ...food,
  id: 'g-home',
  name: 'Housing',
  children: [
    { ...(food.children[0] as CategoryGroupOut['children'][0]), id: 'c-rent', name: 'Rent' },
  ],
};
const salary: CategoryGroupOut = {
  ...food,
  id: 'g-salary',
  name: 'Salary',
  kind: 'income',
  children: [],
};

// Food is a group budget with Groceries as a sub-limit, and it's over; Transport is not.
const groceries = budget('c-groceries', 'Groceries', {
  group_id: 'g-food',
  limit: '300.00',
  available: '300.00',
  spent: '320.00',
  remaining: '-20.00',
});
const foodBudget = budget('g-food', 'Food', {
  rollover: true,
  overspend: 'carry',
  limit: '500.00',
  carried_in: '50.00',
  available: '550.00',
  spent: '450.00',
  remaining: '100.00',
  children: [groceries],
});
const transport = budget('c-transport', 'Transport', {
  limit: '80.00',
  carried_in: '-10.00',
  available: '70.00',
  spent: '40.00',
  remaining: '30.00',
});
const month = budgetsOut([foodBudget, transport], {
  total_limit: '580.00',
  total_available: '620.00',
  total_spent: '490.00',
  unbudgeted: '75.25',
  uncategorized: '12.40',
});

function api(overrides: Record<string, (request: Request) => unknown> = {}) {
  return mockApi({
    'GET /api/finance/budgets': () => month,
    'GET /api/finance/categories': () => [food, housing, salary],
    ...overrides,
  });
}

const rowOf = (name: string) => screen.getByRole('button', { name }).closest('tr') as HTMLElement;
const saved = { category_id: 'c-transport', rollover: false, overspend: 'forgive', limits: [] };
const putBodies = (calls: ReturnType<typeof api>) =>
  calls.filter((call) => call.method === 'PUT').map((call) => call.body);

test('lists the budgets with their totals, a group holding its categories', async () => {
  api();

  renderAt('/finance/budgets?month=2026-10');

  expect(await screen.findByRole('heading', { name: 'October 2026' })).toBeDefined();
  expect(await screen.findByRole('button', { name: 'Food' })).toBeDefined();
  expect(screen.getByText('€490.00')).toBeDefined(); // total spent
  expect(screen.getByText('of €620.00 available')).toBeDefined();
  expect(screen.getByText('€75.25')).toBeDefined(); // unbudgeted
  expect(screen.getByText('€12.40')).toBeDefined(); // uncategorized

  const foodRow = within(rowOf('Food'));
  expect(foodRow.getByText('Rollover')).toBeDefined();
  expect(foodRow.getByText('+€50.00 carried')).toBeDefined();
  expect(foodRow.getByText('€500.00')).toBeDefined(); // limit
  expect(foodRow.getByText('€550.00')).toBeDefined(); // available
  expect(foodRow.getByText('€450.00')).toBeDefined(); // spent
  expect(foodRow.getByText('€100.00')).toBeDefined(); // remaining
  expect(rowOf('Groceries').nextElementSibling).toBe(rowOf('Transport')); // nested under Food
  expect(rowOf('Food').nextElementSibling).toBe(rowOf('Groceries'));
  expect(within(rowOf('Transport')).getByText('-€10.00 carried')).toBeDefined();
});

test('marks a budget that is over', async () => {
  api();

  renderAt('/finance/budgets?month=2026-10');

  await screen.findByRole('button', { name: 'Groceries' });
  const over = within(rowOf('Groceries'));
  expect(over.getByText('Over budget')).toBeDefined();
  expect(over.getByText('-€20.00').className).toContain('text-destructive');
  const bar = over.getByRole('progressbar', { name: 'Groceries spent' });
  expect(bar.getAttribute('aria-valuenow')).toBe('100');
  expect(bar.getAttribute('aria-valuetext')).toBe('€320.00 of €300.00, over budget');
  expect(bar.firstElementChild?.className).toContain('bg-destructive');

  const fine = within(rowOf('Food'));
  expect(fine.queryByText('Over budget')).toBeNull();
  const foodBar = fine.getByRole('progressbar', { name: 'Food spent' });
  expect(foodBar.getAttribute('aria-valuenow')).toBe('82');
  expect(foodBar.firstElementChild?.className).not.toContain('bg-destructive');
});

test('a budget whose repayments exceed its spending shows the net, with an empty bar', async () => {
  const utilities = budget('c-utilities', 'Utilities', {
    rollover: true,
    limit: '100.00',
    available: '100.00',
    spent: '-50.00',
    remaining: '150.00',
  });
  api({ 'GET /api/finance/budgets': () => budgetsOut([utilities]) });

  renderAt('/finance/budgets?month=2026-10');

  await screen.findByRole('button', { name: 'Utilities' });
  const row = within(rowOf('Utilities'));
  expect(row.getByText('-€50.00')).toBeDefined(); // spent
  const remaining = row.getByText('€150.00'); // above the €100.00 limit
  expect(remaining.className).not.toContain('text-destructive');
  expect(row.queryByText('Over budget')).toBeNull();
  const bar = row.getByRole('progressbar', { name: 'Utilities spent' });
  expect(bar.getAttribute('aria-valuenow')).toBe('0');
  expect(bar.firstElementChild?.className).not.toContain('bg-destructive');
});

test('says so when the month has no budgets', async () => {
  api({ 'GET /api/finance/budgets': () => budgetsOut([]) });

  renderAt('/finance/budgets?month=2026-10');

  expect(await screen.findByText(/No budgets in October 2026/)).toBeDefined();
  expect(screen.queryByRole('table')).toBeNull();
});

test('edits a budget from a month on', async () => {
  const calls = api({ 'PUT /api/finance/budgets/c-transport': () => saved });

  renderAt('/finance/budgets?month=2026-10');
  fireEvent.click(await screen.findByRole('button', { name: 'Transport' }));
  const sheet = await screen.findByRole('dialog');
  const amount = within(sheet).getByLabelText('Amount per month (EUR)') as HTMLInputElement;
  expect(amount.value).toBe('80.00');
  expect((within(sheet).getByLabelText('Applies from') as HTMLInputElement).value).toBe('2026-10');
  fireEvent.change(amount, { target: { value: '95.5' } });
  fireEvent.change(within(sheet).getByLabelText('Applies from'), { target: { value: '2026-11' } });
  fireEvent.click(within(sheet).getByRole('button', { name: 'Save budget' }));

  await waitFor(() =>
    expect(putBodies(calls)).toEqual([
      { amount: '95.50', from_month: '2026-11-01', rollover: false, overspend: 'forgive' },
    ]),
  );
  expect(calls.find((call) => call.method === 'PUT')?.path).toBe(
    '/api/finance/budgets/c-transport',
  );
  await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
  // The list is fetched again to show the change.
  await waitFor(() => {
    const afterSave = calls.slice(calls.findIndex((call) => call.method === 'PUT'));
    expect(afterSave.some((call) => call.method === 'GET' && call.path.endsWith('/budgets'))).toBe(
      true,
    );
  });
});

test('turning rollover on takes overspending from next month by default', async () => {
  const calls = api({ 'PUT /api/finance/budgets/c-transport': () => saved });

  renderAt('/finance/budgets?month=2026-10');
  fireEvent.click(await screen.findByRole('button', { name: 'Transport' }));
  const sheet = await screen.findByRole('dialog');
  const overspend = within(sheet).getByRole('combobox', { name: 'If I overspend' });
  expect(overspend.textContent).toBe('Start fresh next month');

  fireEvent.click(within(sheet).getByRole('switch', { name: "Roll over what's left" }));
  expect(overspend.textContent).toBe('Take it from next month');
  await chooseOption(overspend, 'Start fresh next month');
  expect(overspend.textContent).toBe('Start fresh next month');
  fireEvent.click(within(sheet).getByRole('button', { name: 'Save budget' }));

  await waitFor(() =>
    expect(putBodies(calls)).toEqual([
      { amount: '80.00', from_month: '2026-10-01', rollover: true, overspend: 'forgive' },
    ]),
  );
});

test('rollover and overspend are set independently', async () => {
  const calls = api({
    'PUT /api/finance/budgets/g-food': () => ({ ...saved, category_id: 'g-food' }),
  });

  renderAt('/finance/budgets?month=2026-10');
  fireEvent.click(await screen.findByRole('button', { name: 'Food' }));
  const sheet = await screen.findByRole('dialog');
  expect(within(sheet).getByRole('combobox', { name: 'If I overspend' }).textContent).toBe(
    'Take it from next month',
  );
  // Rollover off keeps the overspend choice: unspent money resets, overspending still carries.
  fireEvent.click(within(sheet).getByRole('switch', { name: "Roll over what's left" }));
  expect(within(sheet).getByRole('combobox', { name: 'If I overspend' }).textContent).toBe(
    'Take it from next month',
  );
  fireEvent.click(within(sheet).getByRole('button', { name: 'Save budget' }));

  await waitFor(() =>
    expect(putBodies(calls)).toEqual([
      { amount: '500.00', from_month: '2026-10-01', rollover: false, overspend: 'carry' },
    ]),
  );
});

test('removes a budget', async () => {
  const calls = api({
    'DELETE /api/finance/budgets/c-transport': () => new Response(null, { status: 204 }),
  });

  renderAt('/finance/budgets?month=2026-10');
  fireEvent.click(await screen.findByRole('button', { name: 'Transport' }));
  fireEvent.click(await screen.findByRole('button', { name: 'Remove budget' }));

  await waitFor(() =>
    expect(
      calls.some(
        (call) => call.method === 'DELETE' && call.path === '/api/finance/budgets/c-transport',
      ),
    ).toBe(true),
  );
  await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
});

test('adds a budget for a spending category that has none', async () => {
  const calls = api({
    'PUT /api/finance/budgets/c-rent': () => ({ ...saved, category_id: 'c-rent' }),
  });

  renderAt('/finance/budgets?month=2026-10');
  await screen.findByRole('button', { name: 'Food' });
  fireEvent.click(screen.getByRole('button', { name: 'Add budget' }));
  const sheet = await screen.findByRole('dialog');
  const save = within(sheet).getByRole('button', { name: 'Save budget' });
  expect(save.hasAttribute('disabled')).toBe(true);

  // Food and Groceries have budgets, Salary is income, Old stuff is archived.
  fireEvent.keyDown(within(sheet).getByRole('combobox', { name: 'Category' }), { key: 'Enter' });
  const options = await screen.findAllByRole('option');
  expect(options.map((option) => option.textContent)).toEqual(['All of Housing', 'Rent']);
  fireEvent.keyDown(options[1] as HTMLElement, { key: 'Enter' });
  expect(save.hasAttribute('disabled')).toBe(true); // no amount yet
  fireEvent.change(within(sheet).getByLabelText('Amount per month (EUR)'), {
    target: { value: '600' },
  });
  expect(save.hasAttribute('disabled')).toBe(false);
  fireEvent.click(save);

  await waitFor(() =>
    expect(putBodies(calls)).toEqual([
      { amount: '600.00', from_month: '2026-10-01', rollover: false, overspend: 'forgive' },
    ]),
  );
});

test("shows the API's reason when a budget can't be saved", async () => {
  api({
    'PUT /api/finance/budgets/c-transport': () =>
      Response.json({ detail: 'Only spending can be budgeted.' }, { status: 422 }),
  });

  renderAt('/finance/budgets?month=2026-10');
  fireEvent.click(await screen.findByRole('button', { name: 'Transport' }));
  fireEvent.click(await screen.findByRole('button', { name: 'Save budget' }));

  expect(await screen.findByText('Only spending can be budgeted.')).toBeDefined();
  expect(screen.getByRole('dialog')).toBeDefined(); // still open, to try again
});

test('steps between months', async () => {
  const calls = api({
    'GET /api/finance/budgets': (request) =>
      budgetsOut([], { month: new URL(request.url).searchParams.get('month') ?? '' }),
  });

  renderAt('/finance/budgets?month=2026-01');
  expect(await screen.findByRole('heading', { name: 'January 2026' })).toBeDefined();
  expect(calls.find((call) => call.path === '/api/finance/budgets')?.search.get('month')).toBe(
    '2026-01-01',
  );

  fireEvent.click(screen.getByRole('button', { name: 'Previous month' }));
  expect(await screen.findByRole('heading', { name: 'December 2025' })).toBeDefined();
  await waitFor(() => expect(calls.at(-1)?.search.get('month')).toBe('2025-12-01'));

  fireEvent.click(screen.getByRole('button', { name: 'Next month' }));
  expect(await screen.findByRole('heading', { name: 'January 2026' })).toBeDefined();
});

test('opens on the current month', async () => {
  const calls = api({ 'GET /api/finance/budgets': () => budgetsOut([]) });

  renderAt('/finance/budgets');

  await screen.findByText(/No budgets in/);
  expect(calls.find((call) => call.path === '/api/finance/budgets')?.search.get('month')).toBe(
    `${currentMonth()}-01`,
  );
  expect(screen.queryByRole('button', { name: 'This month' })).toBeNull();
});

// A cap on all spending, with 100 carried in from last month.
const overall = overallBudget({
  rollover: true,
  overspend: 'carry',
  limit: '2000.00',
  carried_in: '100.00',
  available: '2100.00',
  spent: '1800.00',
  remaining: '300.00',
});
const savedOverall = { category_id: null, rollover: false, overspend: 'forgive', limits: [] };
const headline = async () =>
  within(
    (await screen.findByRole('button', { name: 'All spending' })).closest(
      '[data-slot="card"]',
    ) as HTMLElement,
  );

test('shows the overall budget as a headline above the category budgets', async () => {
  api({ 'GET /api/finance/budgets': () => ({ ...month, overall }) });

  renderAt('/finance/budgets?month=2026-10');

  const card = await headline();
  expect(card.getByText('€1,800.00')).toBeDefined();
  expect(card.getByText('of €2,100.00 available')).toBeDefined();
  expect(card.getByText('€300.00 remaining')).toBeDefined();
  expect(card.getByText('Rollover')).toBeDefined();
  expect(card.getByText('+€100.00 carried')).toBeDefined();
  expect(card.queryByText('Over budget')).toBeNull();
  const bar = card.getByRole('progressbar', { name: 'All spending spent' });
  expect(bar.getAttribute('aria-valuenow')).toBe('86');
  // The summary below it is the category budgets', under their own name.
  expect(screen.getByText('Category budgets')).toBeDefined();
  expect(screen.getByText('of €620.00 available')).toBeDefined();
});

test('marks the overall budget when it is over', async () => {
  const over = overallBudget({ available: '1500.00', spent: '1800.00', remaining: '-300.00' });
  api({ 'GET /api/finance/budgets': () => ({ ...month, overall: over }) });

  renderAt('/finance/budgets?month=2026-10');

  const card = await headline();
  expect(card.getByText('Over budget')).toBeDefined();
  expect(card.getByText('-€300.00 remaining').className).toContain('text-destructive');
  expect(
    card.getByRole('progressbar', { name: 'All spending spent' }).firstElementChild?.className,
  ).toContain('bg-destructive');
});

test('offers to set a monthly cap when there is none', async () => {
  const calls = api({
    'PUT /api/finance/budgets/overall': () => savedOverall,
  });

  renderAt('/finance/budgets?month=2026-10');
  expect(screen.queryByRole('button', { name: 'All spending' })).toBeNull();
  fireEvent.click(await screen.findByRole('button', { name: 'Set a monthly cap' }));

  // The sheet has no category to choose, and the amount to fill in.
  const sheet = await screen.findByRole('dialog');
  expect(within(sheet).getByText('All spending')).toBeDefined();
  expect(within(sheet).queryByLabelText('Category')).toBeNull();
  expect(within(sheet).queryByRole('button', { name: 'Remove budget' })).toBeNull();
  const save = within(sheet).getByRole('button', { name: 'Save budget' });
  expect(save.hasAttribute('disabled')).toBe(true); // no amount yet
  fireEvent.change(within(sheet).getByLabelText('Amount per month (EUR)'), {
    target: { value: '2000' },
  });
  expect(save.hasAttribute('disabled')).toBe(false);
  fireEvent.click(save);

  await waitFor(() =>
    expect(putBodies(calls)).toEqual([
      { amount: '2000.00', from_month: '2026-10-01', rollover: false, overspend: 'forgive' },
    ]),
  );
  expect(calls.find((call) => call.method === 'PUT')?.path).toBe('/api/finance/budgets/overall');
  await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
});

test('edits the overall budget from a month on', async () => {
  const calls = api({
    'GET /api/finance/budgets': () => ({ ...month, overall }),
    'PUT /api/finance/budgets/overall': () => savedOverall,
  });

  renderAt('/finance/budgets?month=2026-10');
  fireEvent.click(await screen.findByRole('button', { name: 'All spending' }));
  const sheet = await screen.findByRole('dialog');
  expect(within(sheet).getByText('€2,100.00 available in October 2026.')).toBeDefined();
  expect(within(sheet).queryByLabelText('Category')).toBeNull();
  const amount = within(sheet).getByLabelText('Amount per month (EUR)') as HTMLInputElement;
  expect(amount.value).toBe('2000.00');
  expect(within(sheet).getByRole('switch', { name: "Roll over what's left" })).toHaveProperty(
    'ariaChecked',
    'true',
  );
  expect(within(sheet).getByRole('combobox', { name: 'If I overspend' }).textContent).toBe(
    'Take it from next month',
  );
  fireEvent.change(amount, { target: { value: '2200' } });
  fireEvent.change(within(sheet).getByLabelText('Applies from'), { target: { value: '2026-11' } });
  fireEvent.click(within(sheet).getByRole('button', { name: 'Save budget' }));

  await waitFor(() =>
    expect(putBodies(calls)).toEqual([
      { amount: '2200.00', from_month: '2026-11-01', rollover: true, overspend: 'carry' },
    ]),
  );
});

test('removes the overall budget', async () => {
  const calls = api({
    'GET /api/finance/budgets': () => ({ ...month, overall }),
    'DELETE /api/finance/budgets/overall': () => new Response(null, { status: 204 }),
  });

  renderAt('/finance/budgets?month=2026-10');
  fireEvent.click(await screen.findByRole('button', { name: 'All spending' }));
  fireEvent.click(await screen.findByRole('button', { name: 'Remove budget' }));

  await waitFor(() =>
    expect(
      calls.some(
        (call) => call.method === 'DELETE' && call.path === '/api/finance/budgets/overall',
      ),
    ).toBe(true),
  );
  await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
});
