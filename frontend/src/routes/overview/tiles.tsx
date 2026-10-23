import { useQuery } from '@tanstack/react-query';
import { Link } from '@tanstack/react-router';
import type { ReactNode } from 'react';
import {
  getCashFlowOptions,
  getNetWorthOptions,
  listBudgetsOptions,
  listTransactionsOptions,
} from '@/api/@tanstack/react-query.gen';
import { formatMoney } from '@/lib/format';
import { currentMonth, monthStart } from '@/lib/months';
import { cn } from '@/lib/utils';
import { netWorthChange } from './chart-data';
import { Note, Panel, QueryView } from './panel';

const eur = (amount: string | number) => formatMoney(amount, 'EUR');
const UNCATEGORIZED_LIMIT = 200;

function Figure({ className, children }: { className?: string; children: ReactNode }) {
  return <p className={cn('text-2xl font-semibold tabular-nums', className)}>{children}</p>;
}

export function NetWorthTile() {
  const netWorth = useQuery(getNetWorthOptions());
  return (
    <Panel title="Net worth" query={netWorth}>
      {(data) => {
        const change = netWorthChange(data.points);
        return (
          <>
            <Figure>{eur(data.total)}</Figure>
            {change && (
              <Note
                className={cn(
                  change.amount > 0 && 'text-emerald-700 dark:text-emerald-400',
                  change.amount < 0 && 'text-destructive',
                )}
              >
                {change.amount > 0 && '+'}
                {eur(change.amount)} in {change.days} {change.days === 1 ? 'day' : 'days'}
              </Note>
            )}
          </>
        );
      }}
    </Panel>
  );
}

/** Spent against the overall budget, else against the category budgets; without either, just
 * what was spent. */
export function ThisMonthTile() {
  const month = currentMonth();
  const budgets = useQuery(listBudgetsOptions({ query: { month: monthStart(month) } }));
  return (
    <Panel title="This month" query={budgets}>
      {(data) => {
        const figures = data.overall
          ? { spent: data.overall.spent, available: data.overall.available, note: 'available' }
          : data.budgets.length > 0
            ? { spent: data.total_spent, available: data.total_available, note: 'budgeted' }
            : null;
        if (!figures) return <SpendingWithoutBudgets month={month} />;
        return (
          <>
            <Figure
              className={cn(
                Number(figures.spent) > Number(figures.available) && 'text-destructive',
              )}
            >
              {eur(figures.spent)}
            </Figure>
            <Note>
              of {eur(figures.available)} {figures.note}
            </Note>
          </>
        );
      }}
    </Panel>
  );
}

function SpendingWithoutBudgets({ month }: { month: string }) {
  const cashFlow = useQuery(getCashFlowOptions({ query: { months: 12 } }));
  return (
    <QueryView query={cashFlow}>
      {(data) => {
        const thisMonth = data.months.find((row) => row.month.startsWith(month));
        return (
          <>
            <Figure>{eur(thisMonth?.spending ?? 0)}</Figure>
            <Note>
              spent so far.{' '}
              <Link to="/finance/budgets" className="underline underline-offset-4">
                Set budgets
              </Link>
            </Note>
          </>
        );
      }}
    </QueryView>
  );
}

/** Transactions from this month that no category covers yet. */
export function ToCategorizeTile() {
  const from = monthStart(currentMonth());
  const uncategorized = useQuery(
    listTransactionsOptions({
      query: { uncategorized: true, date_from: from, limit: UNCATEGORIZED_LIMIT },
    }),
  );
  return (
    <Panel title="To categorize" query={uncategorized}>
      {(page) => {
        const count = page.items.length;
        return (
          <>
            <Figure>{page.next_cursor ? `${UNCATEGORIZED_LIMIT}+` : count}</Figure>
            {count === 0 ? (
              <Note>Everything this month has a category.</Note>
            ) : (
              <Note>
                uncategorized this month.{' '}
                <Link
                  to="/finance/transactions"
                  search={{ category: 'uncategorized', from }}
                  className="underline underline-offset-4"
                >
                  Review
                </Link>
              </Note>
            )}
          </>
        );
      }}
    </Panel>
  );
}
