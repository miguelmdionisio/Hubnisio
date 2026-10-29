import { useNavigate, useSearch } from '@tanstack/react-router';
import { ChartColumn } from 'lucide-react';
import type { SpendingMonth } from '@/api/types.gen';
import { PageHeader } from '@/components/app-shell';
import { useCategoryStyles } from '@/components/category-chip';
import { formatMoney, formatWholeMoney } from '@/lib/format';
import { useIsDesktop } from '@/lib/media';
import { currentMonth } from '@/lib/months';
import { cn } from '@/lib/utils';
import { QueryView } from '@/routes/overview/panel';
import { TransactionDays } from '../transaction-rows';
import { DayBars, Donut, RunningTotal, type Slice } from './charts';
import {
  Change,
  Partial,
  RankList,
  SelectedDay,
  type SetSearch,
  SpendingControls,
  Total,
} from './parts';
import { type SpendingSearch, useSpendingMonth, useSpendingTransactions } from './search';

const whole = (amount: string | number) => formatWholeMoney(amount, 'EUR');
const MERCHANT_COLORS = ['var(--chart-1)', 'var(--chart-2)', 'var(--chart-3)', 'var(--chart-4)'];

export function useSetSpendingSearch(from: string): SetSearch {
  const navigate = useNavigate();
  return (changes) =>
    navigate({
      to: from,
      search: (previous: SpendingSearch) => ({ ...previous, ...changes }),
      replace: true,
    } as never);
}

export function SpendingPage() {
  const search = useSearch({ from: '/finance/spending' });
  const setSearch = useSetSpendingSearch('/finance/spending');
  const month = useSpendingMonth(search);
  return (
    <>
      <PageHeader title="Spending" showsView />
      <SpendingControls search={search} setSearch={setSearch} />
      <QueryView query={month} skeleton="mt-5 h-72 rounded-[18px]">
        {(data) => <Figures data={data} search={search} setSearch={setSearch} />}
      </QueryView>
    </>
  );
}

/** The month's figure, its chart, then what it's made of (or the picked day's payments). */
function Figures({
  data,
  search,
  setSearch,
}: {
  data: SpendingMonth;
  search: SpendingSearch;
  setSearch: SetSearch;
}) {
  const chart = search.chart ?? 'bars';
  const by = search.group === 'merchant' ? 'merchant' : 'category';
  const day = chart === 'bars' ? data.days.find((d) => d.day === search.day) : undefined;
  const thisMonth = data.month.slice(0, 7) === currentMonth();
  return (
    <>
      {chart === 'donut' ? (
        <SpendingDonut data={data} search={search} by={by} />
      ) : day ? (
        <SelectedDay
          day={day.day}
          amount={day.amount}
          count={day.count}
          onClear={() => setSearch({ day: undefined })}
        />
      ) : (
        <Total amount={data.total}>
          {chart === 'line' ? (
            <Change data={data} />
          ) : (
            <>
              <span className="flex items-center gap-1 text-primary">
                <ChartColumn className="size-4" aria-hidden />
                {whole(data.daily_average)} avg. per day
              </span>
              <span className="font-medium text-muted-foreground">
                · {thisMonth ? 'This month' : formatMonthLong(data.month)}
              </span>
              {!thisMonth && data.incomplete && <Partial month={data.month} />}
            </>
          )}
        </Total>
      )}
      {chart === 'bars' && (
        <DayBars
          days={data.days}
          average={data.daily_average}
          selected={day?.day}
          onSelect={(picked) => setSearch({ day: picked })}
        />
      )}
      {chart === 'line' && <RunningTotal days={data.days} previous={data.previous.days} />}
      {day ? (
        <DayTransactions search={search} />
      ) : (
        <RankList
          ranks={by === 'merchant' ? data.merchants : data.categories}
          by={by}
          search={search}
        />
      )}
    </>
  );
}

function formatMonthLong(isoDate: string) {
  return new Intl.DateTimeFormat('en-GB', { month: 'long' }).format(new Date(`${isoDate}T00:00`));
}

function DayTransactions({ search }: { search: SpendingSearch }) {
  const transactions = useSpendingTransactions(search);
  return (
    <TransactionDays items={transactions.items} pending={transactions.isPending} showDays={false} />
  );
}

function SpendingDonut({
  data,
  search,
  by,
}: {
  data: SpendingMonth;
  search: SpendingSearch;
  by: 'category' | 'merchant';
}) {
  const navigate = useNavigate();
  const styleOf = useCategoryStyles();
  const desktop = useIsDesktop();
  const ranks = by === 'merchant' ? data.merchants : data.categories;
  const keep = { month: search.month, account: search.account };
  const top: Slice[] = ranks.slice(0, 4).map((rank, index) => ({
    key: rank.id ?? 'none',
    name:
      (by === 'category' ? (rank.id ? rank.name : styleOf(null).name) : rank.name) ?? 'No merchant',
    amount: Number(rank.amount),
    color:
      by === 'category' ? styleOf(rank.id).color : (MERCHANT_COLORS[index] ?? 'var(--chart-5)'),
    href: rank.id
      ? () =>
          navigate(
            by === 'category'
              ? {
                  to: '/finance/spending/category/$id',
                  params: { id: rank.id ?? '' },
                  search: keep,
                }
              : {
                  to: '/finance/spending/merchant/$id',
                  params: { id: rank.id ?? '' },
                  search: keep,
                },
          )
      : undefined,
  }));
  const rest = ranks.slice(4).reduce((sum, rank) => sum + Number(rank.amount), 0);
  const slices =
    rest > 0
      ? [...top, { key: 'others', name: 'Others', amount: rest, color: 'var(--chart-other)' }]
      : top;
  const delta = Number(data.total) - Number(data.previous_to_date);
  const thisMonth = data.month.slice(0, 7) === currentMonth();
  return (
    <Donut
      size={desktop ? 290 : 250}
      slices={slices}
      center={
        <>
          <p className="text-[32px] font-[750] tracking-[-0.03em] tabular-nums">
            {whole(data.total)}
          </p>
          <p
            className={cn(
              'flex items-center justify-center gap-0.5 font-[650] tabular-nums',
              delta > 0 ? 'text-destructive' : 'text-good',
            )}
            title={`vs ${formatMoney(data.previous_to_date, 'EUR')} the month before`}
          >
            <span aria-hidden className="text-[11px]">
              {delta > 0 ? '▲' : '▼'}
            </span>
            <span className="sr-only">{delta > 0 ? 'up' : 'down'}</span>
            {whole(Math.abs(delta))}
          </p>
          <p className="text-sm text-muted-foreground">
            {thisMonth ? 'This month' : formatMonthLong(data.month)}
          </p>
        </>
      }
    />
  );
}
