import { type UseQueryResult, useQuery } from '@tanstack/react-query';
import { Link } from '@tanstack/react-router';
import { ChevronRight } from 'lucide-react';
import type { ReactNode } from 'react';
import {
  getNetWorthOptions,
  getSpendingMonthOptions,
  listBudgetsOptions,
  listTransactionsOptions,
  listUpcomingPaymentsOptions,
} from '@/api/@tanstack/react-query.gen';
import type { BudgetOut, BudgetsOut, UpcomingPayment } from '@/api/types.gen';
import { PageHeader } from '@/components/app-shell';
import { BudgetBar, monthPace } from '@/components/budget-bar';
import { Chip, useCategoryStyles } from '@/components/category-chip';
import { pillClass } from '@/components/pills';
import { Skeleton } from '@/components/ui/skeleton';
import { errorMessage } from '@/lib/errors';
import { formatMoney, formatMonthName, formatWholeMoney, parseDate } from '@/lib/format';
import { currentMonth, monthStart } from '@/lib/months';
import { cn } from '@/lib/utils';
import { useView } from '@/lib/view';
import { DayBars } from './finance/spending/charts';
import { netWorthChange } from './overview/chart-data';
import { QueryView } from './overview/panel';
import { SyncStatus } from './overview/sync-status';

const eur = (amount: string | number) => formatMoney(amount, 'EUR');
const whole = (amount: string | number) => formatWholeMoney(amount, 'EUR');
const DUE_DAYS = 7;
const COMING_UP_DAYS = 30;
const REVIEW_LIMIT = 200;

/** The glance: four figures that open their pages, budgets, what's coming up, spent per day. */
export function HomePage() {
  const { view } = useView();
  const month = currentMonth();
  const spending = useQuery(getSpendingMonthOptions({ query: { month: monthStart(month), view } }));
  const budgets = useQuery(listBudgetsOptions({ query: { month: monthStart(month), view } }));
  const upcoming = useQuery(listUpcomingPaymentsOptions({ query: { days: COMING_UP_DAYS } }));
  const netWorth = useQuery(getNetWorthOptions({ query: { view } }));
  const payments = upcoming.data?.filter((payment) => payment.kind === 'expense');
  return (
    <>
      <PageHeader title="Overview" showsView actions={<ToReview />} />
      <SyncStatus />
      <h2 className="sr-only">At a glance</h2>
      <div className="mt-4 grid grid-cols-2 gap-2.5 tabular-nums md:grid-cols-4 md:gap-3">
        <Tile to="/finance/spending" label="Spent this month" query={spending}>
          {(data) => (
            <>
              <strong>{whole(data.total)}</strong>
              <Delta
                amount={Number(data.total) - Number(data.previous_to_date)}
                against={formatMonthName(data.previous.month)}
              />
            </>
          )}
        </Tile>
        <Tile to="/finance/budgets" label="Left to spend" query={budgets}>
          {(data) => <LeftToSpend data={data} />}
        </Tile>
        <Tile to="/finance/recurring" label={`Due in ${DUE_DAYS} days`} query={upcoming}>
          {() => <DueSoon payments={payments ?? []} />}
        </Tile>
        <Tile to="/finance/accounts" label="Net worth" query={netWorth}>
          {(data) => (
            <>
              <strong>{whole(data.total)}</strong>
              <NetWorthDelta points={data.points} />
            </>
          )}
        </Tile>
      </div>

      <div className="grid gap-x-10 md:grid-cols-[1.2fr_1fr]">
        <section aria-labelledby="budgets">
          <SectionTitle id="budgets" to="/finance/budgets" link="See all">
            Budgets
          </SectionTitle>
          <QueryView query={budgets} skeleton="h-[112px]">
            {(data) => <BudgetRows data={data} />}
          </QueryView>
        </section>
        <section aria-labelledby="coming-up">
          <SectionTitle id="coming-up" to="/finance/recurring" link="See all">
            Coming up
          </SectionTitle>
          <QueryView query={upcoming} skeleton="h-40">
            {() => <ComingUp payments={payments ?? []} />}
          </QueryView>
        </section>
      </div>

      <section aria-labelledby="per-day">
        <SectionTitle id="per-day" to="/finance/spending" link="Spending">
          Spent per day
        </SectionTitle>
        <QueryView query={spending} skeleton="h-[150px]">
          {(data) => <DayBars days={data.days} average={data.daily_average} height={150} />}
        </QueryView>
      </section>
    </>
  );
}

function SectionTitle({
  id,
  to,
  link,
  children,
}: {
  id: string;
  to: '/finance/budgets' | '/finance/recurring' | '/finance/spending';
  link: string;
  children: ReactNode;
}) {
  return (
    <div className="mt-7 mb-2 flex items-center">
      <h2 id={id} className="text-base font-bold">
        {children}
      </h2>
      <Link
        to={to}
        className="tap-area ml-auto flex items-center gap-0.5 text-[13.5px] font-semibold text-primary [--tap-y:12px]"
      >
        {link}
        <ChevronRight className="size-4" aria-hidden />
      </Link>
    </div>
  );
}

function Tile<T>({
  to,
  label,
  query,
  children,
}: {
  to: '/finance/spending' | '/finance/budgets' | '/finance/recurring' | '/finance/accounts';
  label: string;
  query: UseQueryResult<T, unknown>;
  children: (data: T) => ReactNode;
}) {
  return (
    <Link
      to={to}
      className="block rounded-[18px] bg-surface p-3.5 transition-colors hover:bg-surface-2 md:p-4 [&_strong]:mt-1 [&_strong]:block [&_strong]:text-xl [&_strong]:font-[750] [&_strong]:tracking-[-0.02em] md:[&_strong]:text-2xl"
    >
      <span className="flex items-center justify-between text-[13px] text-muted-foreground">
        {label}
        <ChevronRight className="size-4 text-faint" aria-hidden />
      </span>
      {query.isPending ? (
        <Skeleton className="mt-2 h-[43px] w-24 md:h-12" />
      ) : query.isError ? (
        <strong title={errorMessage(query.error)}>—</strong>
      ) : (
        children(query.data)
      )}
    </Link>
  );
}

function Sub({ className, children }: { className?: string; children: ReactNode }) {
  return (
    <span className={cn('block text-[13px] font-semibold text-muted-foreground', className)}>
      {children}
    </span>
  );
}

function Delta({ amount, against }: { amount: number; against: string }) {
  return (
    <Sub className={amount > 0 ? 'text-destructive' : 'text-good'}>
      {amount > 0 ? '+' : '−'}
      {whole(Math.abs(amount))} vs {against}
    </Sub>
  );
}

function daysLeft(today = new Date()): number {
  return new Date(today.getFullYear(), today.getMonth() + 1, 0).getDate() - today.getDate();
}

/** What's left of the overall budget, else of the category budgets. */
function LeftToSpend({ data }: { data: BudgetsOut }) {
  const figures = data.overall
    ? { spent: data.overall.spent, available: data.overall.available }
    : data.budgets.length > 0
      ? { spent: data.total_spent, available: data.total_available }
      : null;
  if (!figures) {
    return (
      <>
        <strong>—</strong>
        <Sub>No budget</Sub>
      </>
    );
  }
  const left = Number(figures.available) - Number(figures.spent);
  const days = daysLeft();
  return (
    <>
      <strong className={cn(left < 0 && 'text-destructive')}>
        {left < 0 ? `${whole(-left)} over` : whole(left)}
      </strong>
      <Sub>
        {days} day{days === 1 ? '' : 's'} left
      </Sub>
    </>
  );
}

function paymentEur(payment: UpcomingPayment): number {
  return Number(payment.amount_eur ?? 0);
}

function DueSoon({ payments }: { payments: UpcomingPayment[] }) {
  const limit = new Date();
  limit.setDate(limit.getDate() + DUE_DAYS);
  const due = payments.filter((payment) => parseDate(payment.on) <= limit);
  const total = due.reduce((sum, payment) => sum + Math.abs(paymentEur(payment)), 0);
  return (
    <>
      <strong>{eur(total)}</strong>
      <Sub>
        {due.length === 0 ? 'Nothing due' : `${due.length} bill${due.length === 1 ? '' : 's'}`}
      </Sub>
    </>
  );
}

function NetWorthDelta({ points }: { points: Parameters<typeof netWorthChange>[0] }) {
  const change = netWorthChange(points);
  if (!change) return null;
  return (
    <Sub className={cn(change.amount > 0 && 'text-good', change.amount < 0 && 'text-destructive')}>
      <span title={`${change.days} days`}>
        {change.amount > 0 ? '+' : change.amount < 0 ? '−' : ''}
        {whole(Math.abs(change.amount))}
      </span>
    </Sub>
  );
}

/** The overall budget, then each budget, with a tick where the month has got to. */
function BudgetRows({ data }: { data: BudgetsOut }) {
  const styleOf = useCategoryStyles();
  if (!data.overall && data.budgets.length === 0) {
    return (
      <Link to="/finance/budgets" className={cn(pillClass, 'mt-2')}>
        Set a budget
      </Link>
    );
  }
  const pace = monthPace();
  const row = (
    name: string,
    budget: BudgetOut | NonNullable<BudgetsOut['overall']>,
    color?: string,
  ) => {
    const remaining = Number(budget.remaining);
    const over = remaining < 0;
    return (
      <>
        <span className="mb-2 flex justify-between gap-2.5 text-sm tabular-nums">
          <b className="truncate font-semibold">{name}</b>
          <span
            className={cn(
              'shrink-0 text-muted-foreground',
              over && 'font-semibold text-destructive',
            )}
          >
            {over ? `${whole(-remaining)} over` : `${whole(remaining)} left`}
          </span>
        </span>
        <BudgetBar
          label={name}
          spent={budget.spent}
          available={budget.available}
          over={over}
          color={color}
          pace={pace}
        />
      </>
    );
  };
  const rowClass = '-mx-3 block rounded-xl px-3 py-[11px] hover:bg-surface';
  return (
    <ul>
      {data.overall && (
        <li>
          <Link to="/finance/budgets" className={rowClass}>
            {row('All spending', data.overall)}
          </Link>
        </li>
      )}
      {data.budgets.slice(0, 6).map((budget) => (
        <li key={budget.category_id}>
          <Link
            to="/finance/spending/category/$id"
            params={{ id: budget.category_id }}
            className={rowClass}
          >
            {row(budget.name, budget, styleOf(budget.category_id).color)}
          </Link>
        </li>
      ))}
    </ul>
  );
}

const shortDate = (isoDate: string) =>
  new Intl.DateTimeFormat('en-GB', { day: 'numeric', month: 'short' }).format(parseDate(isoDate));

/** The next confirmed payments. */
function ComingUp({ payments }: { payments: UpcomingPayment[] }) {
  if (payments.length === 0) {
    return (
      <Link to="/finance/recurring" className={cn(pillClass, 'mt-2')}>
        Confirm recurring payments
      </Link>
    );
  }
  return (
    <ul>
      {payments.slice(0, 4).map((payment) => (
        <li
          key={`${payment.series_id}-${payment.on}`}
          className="grid grid-cols-[auto_minmax(0,1fr)_auto] items-center gap-3.5 border-b py-2.5 tabular-nums last:border-0"
        >
          <Chip letter={payment.name} size="sm" />
          <span className="min-w-0">
            <span className="block truncate font-semibold">{payment.name}</span>
            <span className="block text-[13px] text-muted-foreground">{shortDate(payment.on)}</span>
          </span>
          <span className="font-[650]">
            {payment.amount_eur !== null
              ? `−${eur(Math.abs(Number(payment.amount_eur)))}`
              : formatMoney(payment.amount, payment.currency)}
          </span>
        </li>
      ))}
    </ul>
  );
}

/** What still needs a look: uncategorized this month, and AI suggestions. */
function ToReview() {
  const from = monthStart(currentMonth());
  const uncategorized = useQuery(
    listTransactionsOptions({
      query: { uncategorized: true, date_from: from, limit: REVIEW_LIMIT },
    }),
  );
  const suggested = useQuery(
    listTransactionsOptions({ query: { source: 'ai', limit: REVIEW_LIMIT } }),
  );
  const count = (page: typeof uncategorized.data) =>
    page ? (page.next_cursor ? `${REVIEW_LIMIT}+` : String(page.items.length)) : '0';
  const open = uncategorized.data?.items.length ?? 0;
  const ai = suggested.data?.items.length ?? 0;
  // Its room is kept while it loads, so the header doesn't wrap under the page later (M9 P5).
  if (uncategorized.isPending || suggested.isPending) {
    return <Skeleton className="h-[34px] w-44 rounded-full md:h-9" />;
  }
  if (open === 0 && ai === 0) return null;
  return (
    <Link
      to="/finance/transactions"
      search={{ view: 'review' }}
      className={cn(pillClass, 'bg-primary-soft text-primary hover:bg-primary-soft')}
      title={`${count(uncategorized.data)} uncategorized this month · ${count(suggested.data)} suggested by AI`}
    >
      {open > 0 && `${count(uncategorized.data)} uncategorized`}
      {open > 0 && ai > 0 && ' · '}
      {ai > 0 && `${count(suggested.data)} suggested`}
    </Link>
  );
}
