import { useQuery } from '@tanstack/react-query';
import {
  Link,
  useCanGoBack,
  useNavigate,
  useParams,
  useRouter,
  useSearch,
} from '@tanstack/react-router';
import { ArrowLeft } from 'lucide-react';
import { listBudgetsOptions, listCounterpartiesOptions } from '@/api/@tanstack/react-query.gen';
import type { BudgetOut, SpendingMonth } from '@/api/types.gen';
import { PageHeader } from '@/components/app-shell';
import { type CategoryStyle, Chip, useCategoryStyles } from '@/components/category-chip';
import { formatMoney, formatWholeMoney } from '@/lib/format';
import { currentMonth, monthStart } from '@/lib/months';
import { cn } from '@/lib/utils';
import { useView } from '@/lib/view';
import { QueryView } from '@/routes/overview/panel';
import { DayBars, RunningTotal } from './charts';
import {
  Change,
  RankList,
  SectionTitle,
  SelectedDay,
  type SetSearch,
  SpendingControls,
  Total,
  TransactionDays,
} from './parts';
import { type SpendingSearch, useSpendingMonth, useSpendingTransactions } from './search';
import { useSetSpendingSearch } from './spending';

const eur = (amount: string | number) => formatMoney(amount, 'EUR');

/** Back to where the user came from, or to Spending when the page was opened directly. */
function BackButton({ search }: { search: SpendingSearch }) {
  const canGoBack = useCanGoBack();
  const router = useRouter();
  const navigate = useNavigate();
  return (
    <button
      type="button"
      aria-label="Back"
      onClick={() =>
        canGoBack
          ? router.history.back()
          : navigate({
              to: '/finance/spending',
              search: { month: search.month, account: search.account },
            })
      }
      className="-ml-1.5 grid size-9 shrink-0 place-items-center rounded-full text-muted-foreground hover:bg-surface hover:text-foreground"
    >
      <ArrowLeft className="size-5" aria-hidden />
    </button>
  );
}

function Leading({ search, chip }: { search: SpendingSearch; chip: React.ReactNode }) {
  return (
    <>
      <BackButton search={search} />
      {chip}
    </>
  );
}

function findBudget(budgets: BudgetOut[], id: string): BudgetOut | undefined {
  for (const budget of budgets) {
    if (budget.category_id === id) return budget;
    const child = findBudget(budget.children, id);
    if (child) return child;
  }
  return undefined;
}

/** The category's budget this month, with where the month's pace should be. */
function CategoryBudget({ id, month, style }: { id: string; month: string; style: CategoryStyle }) {
  const { view } = useView();
  const budgets = useQuery(listBudgetsOptions({ query: { month: monthStart(month), view } }));
  const budget = budgets.data ? findBudget(budgets.data.budgets, id) : undefined;
  if (!budget) return null;
  const spent = Number(budget.spent);
  const available = Number(budget.available);
  const remaining = Number(budget.remaining);
  const over = remaining < 0;
  const ratio = spent <= 0 ? 0 : available > 0 ? Math.min(1, spent / available) : 1;
  const now = new Date();
  const days = new Date(now.getFullYear(), now.getMonth() + 1, 0).getDate();
  const pace = month === currentMonth() ? (now.getDate() / days) * 100 : null;
  return (
    <div className="mt-5">
      <div
        role="progressbar"
        aria-label="Budget spent"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={Math.round(ratio * 100)}
        aria-valuetext={`${eur(spent)} of ${eur(available)}${over ? ', over budget' : ''}`}
        className="relative h-1.5 rounded-full bg-track"
      >
        <div
          className="h-full rounded-full"
          style={{
            width: `${ratio * 100}%`,
            background: over ? 'var(--destructive)' : style.color,
          }}
        />
        {pace !== null && (
          <span
            aria-hidden
            className="absolute -top-[3px] -bottom-[3px] w-0.5 rounded-full bg-foreground/40"
            style={{ left: `${pace}%` }}
          />
        )}
      </div>
      <p className="mt-2 flex justify-between gap-3 text-sm tabular-nums">
        <span className={cn('font-semibold', over && 'text-destructive')}>
          {over ? `${eur(-remaining)} over` : `${eur(remaining)} left`}
        </span>
        <span className="text-muted-foreground">Budget {formatWholeMoney(available, 'EUR')}</span>
      </p>
    </div>
  );
}

/** What a category's and a merchant's page share: figure, chart, then the payments. */
function DetailFigures({
  data,
  search,
  setSearch,
  color,
  between,
  narrowed,
}: {
  data: SpendingMonth;
  search: SpendingSearch;
  setSearch: SetSearch;
  color: string;
  between?: React.ReactNode;
  narrowed: { category_id?: string; counterparty_id?: string };
}) {
  const line = search.chart === 'line';
  const day = line ? undefined : data.days.find((d) => d.day === search.day);
  const transactions = useSpendingTransactions(
    day ? search : { ...search, day: undefined },
    narrowed,
  );
  const month = search.month ?? currentMonth();
  const [year = 1970, number = 1] = month.split('-').map(Number);
  const last = new Date(year, number, 0).getDate();
  return (
    <>
      {day ? (
        <SelectedDay
          day={day.day}
          amount={day.amount}
          count={day.count}
          onClear={() => setSearch({ day: undefined })}
        />
      ) : (
        <Total amount={data.total} cents>
          <Change data={data} />
        </Total>
      )}
      {line ? (
        <RunningTotal days={data.days} previous={data.previous.days} color={color} />
      ) : (
        <DayBars
          days={data.days}
          average={data.daily_average}
          color={color}
          selected={day?.day}
          onSelect={(picked) => setSearch({ day: picked })}
        />
      )}
      {!day && between}
      <SectionTitle
        action={
          transactions.more && (
            <Link
              to="/finance/transactions"
              search={{
                category: narrowed.category_id,
                counterparty: narrowed.counterparty_id,
                account: search.account,
                from: day ? day.day : monthStart(month),
                to: day ? day.day : `${month}-${String(last).padStart(2, '0')}`,
              }}
            >
              See all
            </Link>
          )
        }
      >
        Transactions
      </SectionTitle>
      <TransactionDays items={transactions.items} pending={transactions.isPending} />
    </>
  );
}

export function CategorySpendingPage() {
  const { id } = useParams({ from: '/finance/spending/category/$id' });
  const search = useSearch({ from: '/finance/spending/category/$id' });
  const setSearch = useSetSpendingSearch('/finance/spending/category/$id');
  const style = useCategoryStyles()(id);
  const month = useSpendingMonth(search, { category_id: id });
  return (
    <>
      <PageHeader
        title={style.name}
        leading={<Leading search={search} chip={<Chip style={style} size="sm" />} />}
        showsView
      />
      <SpendingControls
        search={search}
        setSearch={setSearch}
        grouping={false}
        charts={['bars', 'line']}
      />
      <QueryView query={month} skeleton="mt-5 h-72 rounded-[18px]">
        {(data) => (
          <DetailFigures
            data={data}
            search={search}
            setSearch={setSearch}
            color={style.color}
            narrowed={{ category_id: id }}
            between={
              <>
                <CategoryBudget id={id} month={search.month ?? currentMonth()} style={style} />
                {data.merchants.length > 0 && (
                  <>
                    <SectionTitle>Merchants</SectionTitle>
                    <RankList ranks={data.merchants} by="merchant" search={search} limit={5} />
                  </>
                )}
              </>
            }
          />
        )}
      </QueryView>
    </>
  );
}

export function MerchantSpendingPage() {
  const { id } = useParams({ from: '/finance/spending/merchant/$id' });
  const search = useSearch({ from: '/finance/spending/merchant/$id' });
  const setSearch = useSetSpendingSearch('/finance/spending/merchant/$id');
  const styleOf = useCategoryStyles();
  const month = useSpendingMonth(search, { merchant: id });
  const merchants = useQuery({ ...listCounterpartiesOptions(), staleTime: 5 * 60_000 });
  const name =
    merchants.data?.find((merchant) => merchant.id === id)?.name ??
    month.data?.merchants.find((rank) => rank.id === id)?.name ??
    '…';
  const top = month.data?.categories[0];
  const style = top ? styleOf(top.id) : undefined;
  return (
    <>
      <PageHeader
        title={name}
        leading={<Leading search={search} chip={<Chip style={style} letter={name} size="sm" />} />}
        showsView
      />
      <SpendingControls
        search={search}
        setSearch={setSearch}
        grouping={false}
        charts={['bars', 'line']}
      />
      <QueryView query={month} skeleton="mt-5 h-72 rounded-[18px]">
        {(data) => (
          <DetailFigures
            data={data}
            search={search}
            setSearch={setSearch}
            color={style?.color ?? 'var(--foreground)'}
            narrowed={{ counterparty_id: id }}
            between={
              data.categories.length > 1 && (
                <>
                  <SectionTitle>Categories</SectionTitle>
                  <RankList ranks={data.categories} by="category" search={search} limit={5} />
                </>
              )
            }
          />
        )}
      </QueryView>
    </>
  );
}
