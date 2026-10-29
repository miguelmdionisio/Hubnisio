import { useQuery } from '@tanstack/react-query';
import { useEffect, useState } from 'react';
import { getSpendingMonthOptions, listTransactionsOptions } from '@/api/@tanstack/react-query.gen';
import type { TransactionOut } from '@/api/types.gen';
import { currentMonth, isMonth, monthStart } from '@/lib/months';
import { useView } from '@/lib/view';
import { useCategories } from '../category-picker';
import { useAccounts } from '../use-accounts';

export type SpendingChart = 'bars' | 'line' | 'donut';

/** The Spending pages' URL: which month, account, grouping, chart and day. */
export type SpendingSearch = {
  month?: string; // "YYYY-MM"; this month when missing
  account?: string;
  group?: 'merchant'; // by category when missing
  chart?: Exclude<SpendingChart, 'bars'>; // bars when missing
  day?: string; // "YYYY-MM-DD": the day picked on the bars
};

export function validateSpendingSearch(search: Record<string, unknown>): SpendingSearch {
  const month = isMonth(search.month) && search.month < currentMonth() ? search.month : undefined;
  const day =
    typeof search.day === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(search.day)
      ? search.day
      : undefined;
  return {
    month,
    account: typeof search.account === 'string' && search.account ? search.account : undefined,
    group: search.group === 'merchant' ? 'merchant' : undefined,
    chart: search.chart === 'line' || search.chart === 'donut' ? search.chart : undefined,
    day: day?.startsWith(month ?? currentMonth()) ? day : undefined,
  };
}

/** The accounts the filter offers: not investments, and a shared pot only in Household. */
export function useSpendingAccounts() {
  const accounts = useAccounts();
  const { view } = useView();
  const options = accounts.listed.filter(
    (account) => !account.is_investment && (view === 'household' || !account.is_pot),
  );
  return { ...accounts, options };
}

/** One month's spending as the page's controls narrow it. */
export function useSpendingMonth(
  search: SpendingSearch,
  narrowed: { category_id?: string; merchant?: string } = {},
) {
  const { view } = useView();
  const { options } = useSpendingAccounts();
  const account = options.some((option) => option.id === search.account)
    ? search.account
    : undefined;
  const month = search.month ?? currentMonth();
  return useQuery(
    getSpendingMonthOptions({
      query: { month: monthStart(month), view, account_id: account, ...narrowed },
    }),
  );
}

function monthEnd(month: string): string {
  const [year = 1970, number = 1] = month.split('-').map(Number);
  return `${month}-${String(new Date(year, number, 0).getDate()).padStart(2, '0')}`;
}

const LIMIT = 200;

/**
 * The transactions behind a month's (or a day's) spending, as the totals count them: in an
 * expense category, or uncategorized expenses; in Mine, not a shared pot's own.
 */
export function useSpendingTransactions(
  search: SpendingSearch,
  narrowed: { category_id?: string; counterparty_id?: string } = {},
) {
  const { view } = useView();
  const { options, data: accounts } = useSpendingAccounts();
  const categories = useCategories();
  const account = options.some((option) => option.id === search.account)
    ? search.account
    : undefined;
  const month = search.month ?? currentMonth();
  const query = useQuery(
    listTransactionsOptions({
      query: {
        account_id: account,
        date_from: search.day ?? monthStart(month),
        date_to: search.day ?? monthEnd(month),
        status: 'booked',
        limit: LIMIT,
        ...narrowed,
      },
    }),
  );
  const expense = new Set(
    (categories.data ?? []).flatMap((group) =>
      group.kind === 'expense' ? [group.id, ...group.children.map((child) => child.id)] : [],
    ),
  );
  const pots = new Set((accounts ?? []).filter((a) => a.is_pot).map((a) => a.id));
  const counts = (t: TransactionOut) =>
    (t.category ? expense.has(t.category.id) : t.kind === 'expense') &&
    (view === 'household' || account !== undefined || !pots.has(t.account_id));
  return {
    ...query,
    items: query.data?.items.filter(counts),
    more: Boolean(query.data?.next_cursor),
  };
}

/** True from 768px: the sidebar's breakpoint. */
export function useIsDesktop(): boolean {
  const query = '(min-width: 768px)';
  const [matches, setMatches] = useState(() => window.matchMedia(query).matches);
  useEffect(() => {
    const list = window.matchMedia(query);
    const update = () => setMatches(list.matches);
    list.addEventListener('change', update);
    return () => list.removeEventListener('change', update);
  }, []);
  return matches;
}
