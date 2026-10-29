import { Link } from '@tanstack/react-router';
import { ArrowDownUp, ChartColumn, ChartPie, ChartSpline, ListFilter, X } from 'lucide-react';
import { type ReactNode, useState } from 'react';
import type { SpendingMonth, SpendingRank, TransactionOut } from '@/api/types.gen';
import { type CategoryStyle, Chip, useCategoryStyles } from '@/components/category-chip';
import { MenuPill, MonthStepper, Pill } from '@/components/pills';
import { Segmented } from '@/components/segmented';
import { Skeleton } from '@/components/ui/skeleton';
import {
  formatDay,
  formatMoney,
  formatMonthName,
  formatShare,
  formatWholeMoney,
  LOCALE,
} from '@/lib/format';
import { currentMonth, monthStart } from '@/lib/months';
import { cn } from '@/lib/utils';
import { TransactionSheet, transactionTitle } from '../transaction-sheet';
import { type SpendingChart, type SpendingSearch, useSpendingAccounts } from './search';

const eur = (amount: string | number, currency = 'EUR') => formatMoney(amount, currency);
const whole = (amount: string | number) => formatWholeMoney(amount, 'EUR');

const CHARTS: { value: SpendingChart; label: string; icon: typeof ChartColumn }[] = [
  { value: 'bars', label: 'Per day', icon: ChartColumn },
  { value: 'line', label: 'Running total', icon: ChartSpline },
  { value: 'donut', label: 'Share', icon: ChartPie },
];

export type SetSearch = (changes: Partial<SpendingSearch>) => void;

/** The pills over the figures: account, month, grouping and chart. */
export function SpendingControls({
  search,
  setSearch,
  grouping = true,
  charts = ['bars', 'line', 'donut'],
}: {
  search: SpendingSearch;
  setSearch: SetSearch;
  grouping?: boolean;
  charts?: SpendingChart[];
}) {
  const { options } = useSpendingAccounts();
  const account = options.find((option) => option.id === search.account);
  const chart = search.chart ?? 'bars';
  return (
    <div className="flex flex-wrap items-center gap-2">
      <MenuPill
        icon={ListFilter}
        ariaLabel="Account"
        on={account !== undefined}
        label={
          <>
            <span className="md:hidden">{account ? account.name.split(' ')[0] : 'All'}</span>
            <span className="hidden md:inline">{account ? account.name : 'All accounts'}</span>
          </>
        }
        value={account?.id ?? ''}
        options={[
          { value: '', label: 'All accounts' },
          ...options.map((option) => ({ value: option.id, label: option.name })),
        ]}
        onChange={(value) => setSearch({ account: value || undefined, day: undefined })}
      />
      <MonthStepper
        month={search.month ?? currentMonth()}
        onChange={(month) =>
          setSearch({ month: month === currentMonth() ? undefined : month, day: undefined })
        }
      />
      {grouping && (
        <Pill
          aria-label={`Group by ${search.group === 'merchant' ? 'merchant' : 'category'}`}
          onClick={() => setSearch({ group: search.group === 'merchant' ? undefined : 'merchant' })}
        >
          <ArrowDownUp aria-hidden />
          {search.group === 'merchant' ? 'Merchant' : 'Category'}
        </Pill>
      )}
      {charts.length > 1 && (
        <Segmented
          label="Chart"
          className="ml-auto"
          value={chart}
          onChange={(value) =>
            setSearch({ chart: value === 'bars' ? undefined : value, day: undefined })
          }
          options={CHARTS.filter((option) => charts.includes(option.value))}
        />
      )}
    </div>
  );
}

/** A short marker for a month whose data starts partway through it. */
export function Partial({ month }: { month: string }) {
  return (
    <span
      title={`Data starts partway through ${formatMonthName(month)}`}
      className="rounded-full bg-surface px-2 py-px text-xs font-semibold text-muted-foreground"
    >
      Partial
    </span>
  );
}

/** "▼ €213 vs September so far": this month against the month before to the same day. */
export function Change({ data }: { data: SpendingMonth }) {
  const delta = Number(data.total) - Number(data.previous_to_date);
  const soFar = data.month.slice(0, 7) === currentMonth();
  const name = new Intl.DateTimeFormat(LOCALE, { month: 'long' }).format(
    new Date(`${data.previous.month}T00:00`),
  );
  const more = delta > 0;
  return (
    <>
      <span className={cn('flex items-center gap-0.5', more ? 'text-destructive' : 'text-good')}>
        <span aria-hidden className="text-[11px]">
          {more ? '▲' : '▼'}
        </span>
        {whole(Math.abs(delta))}
        <span className="sr-only">{more ? ' more' : ' less'}</span>
      </span>
      <span className="font-medium text-muted-foreground">
        vs {name}
        {soFar ? ' so far' : ''}
      </span>
      {data.previous.incomplete && <Partial month={data.previous.month} />}
    </>
  );
}

/** The big figure and its one line. */
export function Total({
  amount,
  cents,
  children,
}: {
  amount: string | number;
  cents?: boolean;
  children?: ReactNode;
}) {
  return (
    <div className="mt-5">
      <p className="text-[36px] leading-[1.1] font-[750] tracking-[-0.03em] tabular-nums md:text-[42px]">
        {cents ? eur(amount) : whole(amount)}
      </p>
      {children && (
        <p className="mt-1 flex flex-wrap items-center gap-1.5 text-[14.5px] font-semibold tabular-nums">
          {children}
        </p>
      )}
    </div>
  );
}

export function SelectedDay({
  day,
  amount,
  count,
  onClear,
}: {
  day: string;
  amount: string;
  count: number;
  onClear: () => void;
}) {
  return (
    <Total amount={amount}>
      <span className="font-medium text-muted-foreground">
        {formatDay(day)} · {count} transaction{count === 1 ? '' : 's'}
      </span>
      <Pill className="h-[30px] text-[13px] md:h-[30px] md:text-[13px]" onClick={onClear}>
        <X aria-hidden />
        Show the whole month
      </Pill>
    </Total>
  );
}

const rowClass =
  'grid w-full grid-cols-[40px_minmax(0,1fr)_auto] items-center gap-3.5 rounded-[14px] px-3 py-2.5 text-left transition-colors hover:bg-surface-2';

/** The list panel rows sit in. */
export function ListPanel({ children, className }: { children: ReactNode; className?: string }) {
  return <div className={cn('rounded-[18px] bg-surface p-1.5', className)}>{children}</div>;
}

export function SectionTitle({ children, action }: { children: ReactNode; action?: ReactNode }) {
  return (
    <div className="mt-7 mb-2 flex items-center">
      <h2 className="text-base font-bold">{children}</h2>
      {action && <div className="ml-auto text-[13.5px] font-semibold text-primary">{action}</div>}
    </div>
  );
}

function monthRange(search: SpendingSearch) {
  const month = search.month ?? currentMonth();
  const [year = 1970, number = 1] = month.split('-').map(Number);
  const last = new Date(year, number, 0).getDate();
  return { from: monthStart(month), to: `${month}-${String(last).padStart(2, '0')}` };
}

/** Ranked categories or merchants: chip, name, transactions, amount and share. */
export function RankList({
  ranks,
  by,
  search,
  limit = 6,
}: {
  ranks: SpendingRank[];
  by: 'category' | 'merchant';
  search: SpendingSearch;
  limit?: number;
}) {
  const [all, setAll] = useState(false);
  const styleOf = useCategoryStyles();
  if (ranks.length === 0) {
    return <p className="py-7 text-center text-muted-foreground">Nothing spent</p>;
  }
  const keep = { month: search.month, account: search.account, chart: search.chart };
  const detail = { ...keep, chart: keep.chart === 'line' ? ('line' as const) : undefined };
  return (
    <ListPanel className="mt-4">
      <ul>
        {(all ? ranks : ranks.slice(0, limit)).map((rank) => {
          const style = by === 'category' ? styleOf(rank.id) : undefined;
          const name = by === 'category' ? (rank.id ? rank.name : style?.name) : rank.name;
          const content = (
            <>
              <Chip style={style} letter={by === 'merchant' ? (rank.name ?? '?') : undefined} />
              <div className="min-w-0">
                <p className="truncate text-[15px] font-semibold">{name ?? 'No merchant'}</p>
                <p className="truncate text-[13px] text-muted-foreground">
                  {rank.count} transaction{rank.count === 1 ? '' : 's'}
                </p>
              </div>
              <div className="text-right text-[15px] font-[650] tabular-nums">
                {Number(rank.amount) < 0 ? '+' : '−'}
                {eur(Math.abs(Number(rank.amount)))}
                <p className="text-[13px] font-medium text-muted-foreground">
                  {formatShare(rank.share)}
                </p>
              </div>
            </>
          );
          return (
            <li key={rank.id ?? 'none'}>
              {rank.id === null ? (
                by === 'category' ? (
                  <Link
                    to="/finance/transactions"
                    search={{ category: 'uncategorized', kind: 'expense', ...monthRange(search) }}
                    className={rowClass}
                  >
                    {content}
                  </Link>
                ) : (
                  <div className={cn(rowClass, 'hover:bg-transparent')}>{content}</div>
                )
              ) : by === 'category' ? (
                <Link
                  to="/finance/spending/category/$id"
                  params={{ id: rank.id }}
                  search={detail}
                  className={rowClass}
                >
                  {content}
                </Link>
              ) : (
                <Link
                  to="/finance/spending/merchant/$id"
                  params={{ id: rank.id }}
                  search={detail}
                  className={rowClass}
                >
                  {content}
                </Link>
              )}
            </li>
          );
        })}
      </ul>
      {ranks.length > limit && (
        <button
          type="button"
          onClick={() => setAll(!all)}
          className="block w-full rounded-xl pt-3 pb-2 text-center font-[650] hover:bg-surface-2"
        >
          {all ? 'Show fewer' : `See all ${ranks.length}`}
        </button>
      )}
    </ListPanel>
  );
}

/** A payment's row: chip, merchant, category and account, amount. */
export function TransactionRow({
  transaction,
  styleOf,
  accountName,
  onOpen,
}: {
  transaction: TransactionOut;
  styleOf: (id: string | null | undefined) => CategoryStyle;
  accountName: string;
  onOpen: () => void;
}) {
  const style = styleOf(transaction.category?.id);
  const amount = Number(transaction.amount);
  const title = transactionTitle(transaction);
  return (
    <button type="button" onClick={onOpen} className={rowClass}>
      <Chip style={style} letter={transaction.category ? title : undefined} />
      <div className="min-w-0">
        <p className="truncate text-[15px] font-semibold">{title}</p>
        <p className="truncate text-[13px] text-muted-foreground">
          {transaction.category ? style.name : amount > 0 ? 'Income' : style.name} · {accountName}
        </p>
      </div>
      <p
        className={cn('text-right text-[15px] font-[650] tabular-nums', amount > 0 && 'text-good')}
      >
        {amount > 0 ? '+' : '−'}
        {eur(Math.abs(amount), transaction.currency)}
      </p>
    </button>
  );
}

/** Transactions grouped by day, newest first; a row opens the transaction. */
export function TransactionDays({
  items,
  pending,
  showDays = true,
  more,
}: {
  items: TransactionOut[] | undefined;
  pending: boolean;
  showDays?: boolean;
  more?: ReactNode;
}) {
  const styleOf = useCategoryStyles();
  const { names } = useSpendingAccounts();
  const [openId, setOpenId] = useState<string | null>(null);
  if (pending) return <Skeleton className="mt-4 h-40 w-full rounded-[18px]" />;
  if (!items?.length) {
    return <p className="py-7 text-center text-muted-foreground">No transactions</p>;
  }
  const days = new Map<string, TransactionOut[]>();
  for (const item of items)
    days.set(item.occurred_on, [...(days.get(item.occurred_on) ?? []), item]);
  const open = items.find((item) => item.id === openId);
  return (
    <>
      {[...days].map(([day, list]) => (
        <section key={day} aria-label={formatDay(day)}>
          {showDays && (
            <h3 className="mt-[18px] mb-1.5 text-[13px] font-[650] text-muted-foreground">
              {formatDay(day)}
            </h3>
          )}
          <ListPanel className={showDays ? undefined : 'mt-4'}>
            <ul>
              {list.map((transaction) => (
                <li key={transaction.id}>
                  <TransactionRow
                    transaction={transaction}
                    styleOf={styleOf}
                    accountName={names.get(transaction.account_id) ?? '—'}
                    onOpen={() => setOpenId(transaction.id)}
                  />
                </li>
              ))}
            </ul>
          </ListPanel>
        </section>
      ))}
      {more}
      <TransactionSheet
        transaction={open}
        accountName={open ? (names.get(open.account_id) ?? '—') : ''}
        onOpenChange={(isOpen) => !isOpen && setOpenId(null)}
      />
    </>
  );
}
