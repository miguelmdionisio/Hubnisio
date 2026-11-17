import { useInfiniteQuery } from '@tanstack/react-query';
import { useNavigate, useSearch } from '@tanstack/react-router';
import { ArrowLeftRight, Check, ListFilter, Search, Tag, X } from 'lucide-react';
import { useEffect, useState } from 'react';
import { listTransactionsInfiniteQueryKey } from '@/api/@tanstack/react-query.gen';
import { listTransactions } from '@/api/sdk.gen';
import type { TransactionKind, TransactionStatus } from '@/api/types.gen';
import { PageHeader } from '@/components/app-shell';
import { useCategoryStyles } from '@/components/category-chip';
import { MenuPill, Pill } from '@/components/pills';
import { Segmented } from '@/components/segmented';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { errorMessage } from '@/lib/errors';
import { formatDate, parseDate } from '@/lib/format';
import { activeGroups, categoryNames, useCategories } from './category-picker';
import { ReviewQueue, useReviewQueue } from './review';
import { TransactionDays } from './transaction-rows';
import { useAccounts } from './use-accounts';
import { useApproveSuggestions } from './use-transaction-edits';

const PAGE_SIZE = 50;
const SEARCH_DELAY_MS = 300;
const ALL = 'all'; // Select items can't have an empty value
const UNCATEGORIZED = 'uncategorized';
const SUGGESTED = 'suggested'; // categories an AI suggested, to review
const MAX_APPROVALS = 500; // per request, as the API takes them
const KINDS: { value: TransactionKind; label: string }[] = [
  { value: 'expense', label: 'Spending' },
  { value: 'income', label: 'Income' },
  { value: 'transfer', label: 'Transfers' },
];

export type TransactionSearch = {
  account?: string;
  q?: string;
  status?: TransactionStatus;
  kind?: TransactionKind;
  category?: string; // a category or group ID, "uncategorized" or "suggested"
  counterparty?: string;
  from?: string; // "YYYY-MM-DD": the first day shown
  to?: string; // "YYYY-MM-DD": the last day shown
  view?: 'review'; // the review queue instead of the table
};

/** A real calendar date written "YYYY-MM-DD". */
function isoDate(value: unknown): string | undefined {
  if (typeof value !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return undefined;
  const date = parseDate(value);
  const [year, month, day] = value.split('-').map(Number);
  const real =
    date.getFullYear() === year && date.getMonth() + 1 === month && date.getDate() === day;
  return real ? value : undefined;
}

export function validateTransactionSearch(search: Record<string, unknown>): TransactionSearch {
  const text = (value: unknown) => (typeof value === 'string' && value ? value : undefined);
  const status =
    search.status === 'booked' || search.status === 'pending' ? search.status : undefined;
  const kind = KINDS.find((option) => option.value === search.kind)?.value;
  return {
    account: text(search.account),
    q: text(search.q),
    status,
    kind,
    category: text(search.category),
    counterparty: text(search.counterparty),
    from: isoDate(search.from),
    to: isoDate(search.to),
    view: search.view === 'review' ? 'review' : undefined,
  };
}

function dateRange(from?: string, to?: string): string {
  if (from && to) return `${formatDate(from)} to ${formatDate(to)}`;
  return from ? `from ${formatDate(from)}` : `until ${formatDate(to as string)}`;
}

export function TransactionsPage() {
  const search = useSearch({ from: '/finance/transactions' });
  const navigate = useNavigate({ from: '/finance/transactions' });
  const setSearch = (changes: Partial<TransactionSearch>) =>
    navigate({
      search: (previous: TransactionSearch) => ({ ...previous, ...changes }),
      replace: true,
    });
  const queue = useReviewQueue();
  const toReview = new Set(queue.data?.items.map((item) => item.id)).size;

  return (
    <>
      <PageHeader
        title="Transactions"
        actions={
          <Segmented
            label="Show"
            value={search.view ?? ALL}
            onChange={(value) => setSearch({ view: value === 'review' ? 'review' : undefined })}
            options={[
              { value: ALL, label: 'All' },
              { value: 'review', label: queue.isSuccess ? `Review ${toReview}` : 'Review' },
            ]}
          />
        }
      />
      {search.view === 'review' ? (
        <ReviewQueue />
      ) : (
        <AllTransactions search={search} setSearch={setSearch} />
      )}
    </>
  );
}

function AllTransactions({
  search,
  setSearch,
}: {
  search: TransactionSearch;
  setSearch: (changes: Partial<TransactionSearch>) => void;
}) {
  // Typing updates the URL (and the query) once the user pauses.
  const navigate = useNavigate({ from: '/finance/transactions' });
  const [text, setText] = useState(search.q ?? '');
  useEffect(() => {
    const timer = setTimeout(() => {
      const q = text.trim() || undefined;
      if (q !== search.q) {
        navigate({ search: (previous: TransactionSearch) => ({ ...previous, q }), replace: true });
      }
    }, SEARCH_DELAY_MS);
    return () => clearTimeout(timer);
  }, [text, search.q, navigate]);

  const accounts = useAccounts();
  const categories = useCategories();
  const names = categoryNames(categories.data);
  const groups = activeGroups(categories.data);
  const styleOf = useCategoryStyles();
  const approve = useApproveSuggestions();

  const filters = {
    account_id: search.account,
    q: search.q,
    status: search.status,
    kind: search.kind,
    category_id:
      search.category === UNCATEGORIZED || search.category === SUGGESTED
        ? undefined
        : search.category,
    uncategorized: search.category === UNCATEGORIZED ? true : undefined,
    source: search.category === SUGGESTED ? ('ai' as const) : undefined,
    counterparty_id: search.counterparty,
    date_from: search.from,
    date_to: search.to,
  };
  const transactions = useInfiniteQuery({
    queryKey: listTransactionsInfiniteQueryKey({ query: filters }),
    queryFn: async ({ pageParam, signal }) => {
      const { data } = await listTransactions({
        query: { ...filters, limit: PAGE_SIZE, cursor: pageParam ?? undefined },
        signal,
        throwOnError: true,
      });
      return data;
    },
    initialPageParam: null as string | null,
    getNextPageParam: (page) => page.next_cursor,
  });
  const rows = transactions.data?.pages.flatMap((page) => page.items) ?? [];
  const suggestions = rows
    .filter((row) => row.category?.source === 'ai')
    .slice(0, MAX_APPROVALS)
    .map((row) => row.id);
  const merchant = search.counterparty
    ? (rows.find((row) => row.counterparty?.id === search.counterparty)?.counterparty?.name ??
      'Merchant')
    : undefined;
  const dot = (id: string) => (
    <span className="size-2.5 shrink-0 rounded-full" style={{ background: styleOf(id).color }} />
  );

  return (
    <>
      <div className="flex flex-wrap items-center gap-2">
        <label className="tap-area flex h-[34px] min-w-[180px] flex-1 items-center [--tap-x:0px] [--tap-y:5px] gap-2 rounded-full bg-surface px-3.5 focus-within:outline-2 focus-within:outline-ring md:h-9">
          <Search className="size-4 shrink-0 text-muted-foreground" aria-hidden />
          <input
            className="relative z-[1] min-w-0 flex-1 bg-transparent text-base outline-none placeholder:text-faint md:text-sm"
            placeholder="Search"
            aria-label="Search transactions"
            value={text}
            onChange={(event) => setText(event.target.value)}
          />
        </label>
        <MenuPill
          icon={Tag}
          ariaLabel="Category"
          on={search.category !== undefined}
          label={
            search.category === UNCATEGORIZED
              ? 'Uncategorized'
              : search.category === SUGGESTED
                ? 'Suggested by AI'
                : search.category
                  ? (names.get(search.category) ?? 'Category')
                  : 'Any category'
          }
          value={search.category ?? ''}
          onChange={(value) => setSearch({ category: value || undefined })}
          align="end"
          options={[
            { value: '', label: 'Any category' },
            { value: UNCATEGORIZED, label: 'Uncategorized' },
            { value: SUGGESTED, label: 'Suggested by AI' },
            ...groups.flatMap((group) => [
              { value: group.id, label: `All of ${group.name}`, leading: dot(group.id) },
              ...group.children.map((child) => ({
                value: child.id,
                label: child.name,
                leading: <span className="w-2.5" />,
              })),
            ]),
          ]}
        />
        <MenuPill
          icon={ListFilter}
          ariaLabel="Account"
          on={search.account !== undefined}
          label={accounts.names.get(search.account ?? '') ?? 'All accounts'}
          value={search.account ?? ''}
          onChange={(value) => setSearch({ account: value || undefined })}
          align="end"
          options={[
            { value: '', label: 'All accounts' },
            ...accounts.listed.map((account) => ({ value: account.id, label: account.name })),
          ]}
        />
        <MenuPill
          icon={ArrowLeftRight}
          ariaLabel="Kind"
          on={search.kind !== undefined}
          label={KINDS.find((kind) => kind.value === search.kind)?.label ?? 'All kinds'}
          value={search.kind ?? ''}
          onChange={(value) =>
            setSearch({ kind: (value || undefined) as TransactionKind | undefined })
          }
          align="end"
          options={[{ value: '', label: 'All kinds' }, ...KINDS]}
        />
      </div>

      {(merchant || search.from || search.to || search.status) && (
        <div className="mt-2 flex flex-wrap gap-2">
          {merchant && (
            <Pill
              on
              aria-label="Clear merchant filter"
              onClick={() => setSearch({ counterparty: undefined })}
            >
              {merchant}
              <X aria-hidden />
            </Pill>
          )}
          {(search.from || search.to) && (
            <Pill
              on
              aria-label={`Clear dates (${dateRange(search.from, search.to)})`}
              onClick={() => setSearch({ from: undefined, to: undefined })}
            >
              {dateRange(search.from, search.to)}
              <X aria-hidden />
            </Pill>
          )}
          {search.status && (
            <Pill on aria-label="Clear status" onClick={() => setSearch({ status: undefined })}>
              {search.status === 'pending' ? 'Pending' : 'Booked'}
              <X aria-hidden />
            </Pill>
          )}
        </div>
      )}

      {search.category === SUGGESTED && suggestions.length > 0 && (
        <div className="mt-4 flex flex-wrap items-center justify-between gap-2 text-sm text-muted-foreground">
          <span className="tabular-nums">{suggestions.length} to check</span>
          <Button
            size="sm"
            className="rounded-full"
            disabled={approve.isPending}
            onClick={() => approve.mutate({ body: { transaction_ids: suggestions } })}
          >
            <Check aria-hidden />
            Approve the {suggestions.length} shown
          </Button>
        </div>
      )}

      {transactions.isError ? (
        <Alert variant="destructive" className="mt-4">
          <AlertTitle>Couldn't load transactions</AlertTitle>
          <AlertDescription>{errorMessage(transactions.error)}</AlertDescription>
        </Alert>
      ) : (
        <TransactionDays
          items={rows}
          pending={transactions.isPending}
          empty="No transactions match"
          onApprove={(row) => approve.mutate({ body: { transaction_ids: [row.id] } })}
        >
          {transactions.hasNextPage && (
            <div className="mt-4 flex justify-center">
              <Pill
                disabled={transactions.isFetchingNextPage}
                onClick={() => transactions.fetchNextPage()}
              >
                {transactions.isFetchingNextPage ? 'Loading…' : 'Load more'}
              </Pill>
            </div>
          )}
        </TransactionDays>
      )}
    </>
  );
}
