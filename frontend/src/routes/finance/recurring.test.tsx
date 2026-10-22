import { cleanup, fireEvent, screen, waitFor, within } from '@testing-library/react';
import { afterEach, expect, test, vi } from 'vitest';
import type { RecurringOut } from '@/api/types.gen';
import { formatDate } from '@/lib/format';
import { recurring } from '@/test/fixtures';
import { mockApi, renderAt } from '@/test/render';

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const netflix = recurring('s-netflix', 'Netflix', {
  counterparty_id: 'cp-netflix',
  expected_amount: '-12.99',
  previous_amount: '-10.99',
  amount_changed_on: '2026-03-05',
});
const gym = recurring('s-gym', 'Gym', {
  expected_amount: '-30.00',
  previous_amount: '-33.00',
  amount_changed_on: '2026-03-05',
  amount_varies: true,
});
const spotify = recurring('s-spotify', 'Spotify', { review: 'confirmed' });
const magazine = recurring('s-magazine', 'Magazine', { review: 'confirmed', status: 'cancelled' });
const phone = recurring('s-phone', 'Phone', { review: 'confirmed', status: 'dormant' });
const salary = recurring('s-salary', 'Salary', {
  review: 'confirmed',
  kind: 'income',
  expected_amount: '1500.00',
  previous_amount: '1400.00',
  amount_changed_on: '2026-02-01',
});
const parking = recurring('s-parking', 'Parking', { review: 'dismissed' });
const all = [netflix, gym, spotify, magazine, phone, salary, parking];

function api(overrides: Record<string, (request: Request) => unknown> = {}) {
  return mockApi({
    'GET /api/finance/recurring': () => all,
    ...overrides,
  });
}

// Radix tabs switch on mouse down, which jsdom's click doesn't send.
const openTab = (name: RegExp) =>
  fireEvent.mouseDown(screen.getByRole('tab', { name }), { button: 0, ctrlKey: false });

const patches = (calls: ReturnType<typeof api>) =>
  calls
    .filter((call) => call.method === 'PATCH')
    .map((call) => [call.path.split('/').pop(), call.body]);

const ok = (series: RecurringOut) => () => series;

test('starts on the suggestions and filters by tab, with counts', async () => {
  api();

  renderAt('/finance/recurring');

  expect(await screen.findByRole('button', { name: 'Netflix' })).toBeDefined();
  expect(screen.getByRole('button', { name: 'Gym' })).toBeDefined();
  expect(screen.queryByRole('button', { name: 'Spotify' })).toBeNull();
  expect(screen.getByText(/only confirmed ones count in upcoming payments/)).toBeDefined();
  expect(screen.getByRole('tab', { name: /Suggested\s*2/ })).toBeDefined();
  expect(screen.getByRole('tab', { name: /Confirmed\s*4/ })).toBeDefined();
  expect(screen.getByRole('tab', { name: /Dismissed\s*1/ })).toBeDefined();

  openTab(/Confirmed/);
  expect(await screen.findByRole('button', { name: 'Spotify' })).toBeDefined();
  expect(screen.queryByRole('button', { name: 'Netflix' })).toBeNull();

  openTab(/Dismissed/);
  expect(await screen.findByRole('button', { name: 'Parking' })).toBeDefined();
  expect(screen.queryByRole('button', { name: 'Spotify' })).toBeNull();
});

test('opens on the tab in the address', async () => {
  api();

  renderAt('/finance/recurring?tab=dismissed');

  expect(await screen.findByRole('button', { name: 'Parking' })).toBeDefined();
  expect(screen.getByRole('tab', { name: /Dismissed/ }).getAttribute('aria-selected')).toBe('true');
});

test('shows the repeat, amount, dates and how often it was seen', async () => {
  api();

  renderAt('/finance/recurring');

  const row = within(
    (await screen.findByRole('button', { name: 'Netflix' })).closest('tr') as HTMLElement,
  );
  expect(row.getByText('Conta à Ordem')).toBeDefined();
  expect(row.getByText('Monthly')).toBeDefined();
  expect(row.getByText('-€12.99')).toBeDefined();
  expect(row.getByText(formatDate('2026-10-05'))).toBeDefined(); // next expected
  expect(row.getByText(formatDate('2026-09-05'))).toBeDefined(); // last seen
  expect(row.getByText('6')).toBeDefined();
});

test('shows price changes, and marks amounts that vary', async () => {
  api();

  renderAt('/finance/recurring');

  const netflixRow = within(
    (await screen.findByRole('button', { name: 'Netflix' })).closest('tr') as HTMLElement,
  );
  expect(netflixRow.getByText('Up 18% since Mar 2026')).toBeDefined();
  expect(netflixRow.getByText('-€12.99')).toBeDefined(); // no "≈": the amount is steady
  const gymRow = within(screen.getByRole('button', { name: 'Gym' }).closest('tr') as HTMLElement);
  expect(gymRow.getByText('Down 9% since Mar 2026')).toBeDefined();
  expect(gymRow.getByText('≈ -€30.00')).toBeDefined();

  openTab(/Confirmed/);
  // Being paid more is not bad news.
  const salaryRow = within(
    (await screen.findByRole('button', { name: 'Salary' })).closest('tr') as HTMLElement,
  );
  expect(salaryRow.getByText('Income')).toBeDefined();
  expect(salaryRow.getByText('Up 7% since Feb 2026').className).not.toContain('text-destructive');
});

test('confirms and dismisses suggestions', async () => {
  const calls = api({
    'PATCH /api/finance/recurring/s-netflix': ok({ ...netflix, review: 'confirmed' }),
    'PATCH /api/finance/recurring/s-gym': ok({ ...gym, review: 'dismissed' }),
  });

  renderAt('/finance/recurring');
  fireEvent.click(await screen.findByRole('button', { name: 'Confirm Netflix' }));
  await waitFor(() => expect(patches(calls)).toEqual([['s-netflix', { review: 'confirmed' }]]));
  fireEvent.click(screen.getByRole('button', { name: 'Dismiss Gym' }));

  await waitFor(() =>
    expect(patches(calls)).toEqual([
      ['s-netflix', { review: 'confirmed' }],
      ['s-gym', { review: 'dismissed' }],
    ]),
  );
});

test('marks a confirmed payment as stopped, and undoes it', async () => {
  const calls = api({
    'PATCH /api/finance/recurring/s-spotify': ok(spotify),
    'PATCH /api/finance/recurring/s-magazine': ok(magazine),
    'PATCH /api/finance/recurring/s-phone': ok(phone),
  });

  renderAt('/finance/recurring?tab=confirmed');
  const magazineRow = within(
    (await screen.findByRole('button', { name: 'Magazine' })).closest('tr') as HTMLElement,
  );
  expect(magazineRow.getByText('Stopped')).toBeDefined();
  expect(
    within(screen.getByRole('button', { name: 'Phone' }).closest('tr') as HTMLElement).getByText(
      'Late',
    ),
  ).toBeDefined();
  expect(screen.queryByRole('button', { name: 'Mark stopped Magazine' })).toBeNull();

  fireEvent.click(screen.getByRole('button', { name: 'Mark stopped Spotify' }));
  await waitFor(() => expect(patches(calls)).toEqual([['s-spotify', { cancelled: true }]]));
  fireEvent.click(screen.getByRole('button', { name: 'Undo stopped Magazine' }));
  await waitFor(() => expect(patches(calls).at(-1)).toEqual(['s-magazine', { cancelled: false }]));
  fireEvent.click(screen.getByRole('button', { name: 'Dismiss Phone' }));
  await waitFor(() => expect(patches(calls).at(-1)).toEqual(['s-phone', { review: 'dismissed' }]));
});

test('restores a dismissed payment to the suggestions', async () => {
  const calls = api({ 'PATCH /api/finance/recurring/s-parking': ok(parking) });

  renderAt('/finance/recurring?tab=dismissed');
  fireEvent.click(await screen.findByRole('button', { name: 'Restore Parking' }));

  await waitFor(() => expect(patches(calls)).toEqual([['s-parking', { review: 'suggested' }]]));
});

test('renames a payment, and resets the name when emptied', async () => {
  const calls = api({ 'PATCH /api/finance/recurring/s-netflix': ok(netflix) });

  renderAt('/finance/recurring');
  fireEvent.click(await screen.findByRole('button', { name: 'Netflix' }));
  let dialog = await screen.findByRole('dialog');
  const input = within(dialog).getByLabelText('Name') as HTMLInputElement;
  expect(input.value).toBe('Netflix');
  expect(within(dialog).getByRole('button', { name: 'Rename' }).hasAttribute('disabled')).toBe(
    true,
  );
  fireEvent.change(input, { target: { value: ' Netflix UK ' } });
  fireEvent.click(within(dialog).getByRole('button', { name: 'Rename' }));
  await waitFor(() => expect(patches(calls)).toEqual([['s-netflix', { name: 'Netflix UK' }]]));
  await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());

  fireEvent.click(screen.getByRole('button', { name: 'Netflix' }));
  dialog = await screen.findByRole('dialog');
  fireEvent.change(within(dialog).getByLabelText('Name'), { target: { value: '' } });
  fireEvent.click(within(dialog).getByRole('button', { name: 'Rename' }));
  await waitFor(() => expect(patches(calls).at(-1)).toEqual(['s-netflix', { name: '' }]));
});

test("links to a merchant's transactions when there is one", async () => {
  api();

  renderAt('/finance/recurring');

  const link = await screen.findByRole('link', { name: 'Transactions for Netflix' });
  expect(link.getAttribute('href')).toBe('/finance/transactions?counterparty=cp-netflix');
  expect(screen.queryByRole('link', { name: 'Transactions for Gym' })).toBeNull();
});

test('says what is missing on an empty tab', async () => {
  api({ 'GET /api/finance/recurring': () => [parking] });

  renderAt('/finance/recurring');

  expect(await screen.findByText(/Nothing to review/)).toBeDefined();
  expect(screen.queryByRole('table')).toBeNull();
  openTab(/Confirmed/);
  expect(await screen.findByText(/No confirmed payments yet/)).toBeDefined();
});

test('shows why a change failed', async () => {
  api({
    'PATCH /api/finance/recurring/s-netflix': () =>
      Response.json({ detail: 'That payment is gone.' }, { status: 404 }),
  });

  renderAt('/finance/recurring');
  fireEvent.click(await screen.findByRole('button', { name: 'Confirm Netflix' }));

  expect(await screen.findByText('That payment is gone.')).toBeDefined();
});
