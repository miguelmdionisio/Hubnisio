import { useQuery } from '@tanstack/react-query';
import { Link } from '@tanstack/react-router';
import type { ReactNode } from 'react';
import {
  getCashFlowOptions,
  getNetWorthOptions,
  listBudgetsOptions,
  listTransactionsOptions,
  listUpcomingPaymentsOptions,
} from '@/api/@tanstack/react-query.gen';
import { formatDate, formatMoney, formatPercent } from '@/lib/format';
import { currentMonth, monthStart } from '@/lib/months';
import { cn } from '@/lib/utils';
import { useView } from '@/lib/view';
import { netWorthChange } from './chart-data';
import { Note, Panel, QueryView } from './panel';

const eur = (amount: string | number) => formatMoney(amount, 'EUR');
const UNCATEGORIZED_LIMIT = 200;
export const UPCOMING_DAYS = 30;

function Figure({ className, children }: { className?: string; children: ReactNode }) {
  return <p className={cn('text-2xl font-semibold tabular-nums', className)}>{children}</p>;
}

export function NetWorthTile() {
  const { view } = useView();
  const netWorth = useQuery(getNetWorthOptions({ query: { view } }));
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

/** What's left of the overall budget, else of the category budgets, with how much of it and of
 * the month has gone; without either budget, just what was spent. */
export function ThisMonthTile() {
  const month = currentMonth();
  const { view } = useView();
  const budgets = useQuery(listBudgetsOptions({ query: { month: monthStart(month), view } }));
  return (
    <Panel title="This month" query={budgets}>
      {(data) => {
        const figures = data.overall
          ? { spent: data.overall.spent, available: data.overall.available, note: 'available' }
          : data.budgets.length > 0
            ? { spent: data.total_spent, available: data.total_available, note: 'budgeted' }
            : null;
        if (!figures) return <SpendingWithoutBudgets month={month} />;
        const spent = Number(figures.spent);
        const available = Number(figures.available);
        const left = available - spent;
        return (
          <>
            {left < 0 ? (
              <Figure className="text-destructive">Over by {eur(-left)}</Figure>
            ) : (
              <Figure>
                {eur(left)} <span className="text-sm font-normal text-muted-foreground">left</span>
              </Figure>
            )}
            <Note>
              {eur(figures.spent)} spent of {eur(figures.available)} {figures.note}
            </Note>
            {available > 0 && (
              <Note>
                {wholePercent(spent / available)} spent, {wholePercent(monthGone())} of the month
                gone
              </Note>
            )}
          </>
        );
      }}
    </Panel>
  );
}

const wholePercent = (share: number) => formatPercent(Math.round(share * 100) / 100);

/** How much of the current month has gone, counting today. */
function monthGone(today = new Date()): number {
  const days = new Date(today.getFullYear(), today.getMonth() + 1, 0).getDate();
  return today.getDate() / days;
}

function SpendingWithoutBudgets({ month }: { month: string }) {
  const { view } = useView();
  const cashFlow = useQuery(getCashFlowOptions({ query: { months: 12, view } }));
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

/** The next expense among the confirmed recurring payments. */
export function NextPaymentTile() {
  const upcoming = useQuery(listUpcomingPaymentsOptions({ query: { days: UPCOMING_DAYS } }));
  return (
    <Panel title="Next payment" query={upcoming}>
      {(data) => {
        const next = data.find((payment) => payment.kind === 'expense');
        if (!next) return <Note>No confirmed payment in the next {UPCOMING_DAYS} days.</Note>;
        return (
          <>
            <Figure>
              {next.amount_eur !== null
                ? eur(next.amount_eur)
                : formatMoney(next.amount, next.currency)}
            </Figure>
            <Note>
              {next.name}, {formatDate(next.on)}
            </Note>
          </>
        );
      }}
    </Panel>
  );
}

/** Transactions from this month that no category covers yet, and any AI suggestions to review. */
export function ToCategorize() {
  const from = monthStart(currentMonth());
  const uncategorized = useQuery(
    listTransactionsOptions({
      query: { uncategorized: true, date_from: from, limit: UNCATEGORIZED_LIMIT },
    }),
  );
  const suggested = useQuery(
    listTransactionsOptions({ query: { source: 'ai', limit: UNCATEGORIZED_LIMIT } }),
  );
  const suggestedCount = suggested.data?.items.length ?? 0;
  return (
    <div className="flex flex-wrap items-baseline gap-x-4 gap-y-1 text-sm">
      <QueryView query={uncategorized} skeleton="h-5 w-64">
        {(page) => {
          const count = page.items.length;
          return count === 0 ? (
            <p className="text-muted-foreground">Everything this month has a category.</p>
          ) : (
            <p>
              <span className="font-medium tabular-nums">
                {page.next_cursor ? `Over ${UNCATEGORIZED_LIMIT}` : count}
              </span>{' '}
              uncategorized this month.{' '}
              <Link
                to="/finance/transactions"
                search={{ category: 'uncategorized', from }}
                className="underline underline-offset-4"
              >
                Review
              </Link>
            </p>
          );
        }}
      </QueryView>
      {suggestedCount > 0 && (
        <p>
          <Link
            to="/finance/transactions"
            search={{ category: 'suggested' }}
            className="underline underline-offset-4"
          >
            {suggested.data?.next_cursor ? `Over ${UNCATEGORIZED_LIMIT}` : suggestedCount} suggested
            by AI to review
          </Link>
        </p>
      )}
    </div>
  );
}
