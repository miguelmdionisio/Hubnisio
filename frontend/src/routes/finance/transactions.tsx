import { useInfiniteQuery, useQuery } from '@tanstack/react-query';
import { useNavigate, useSearch } from '@tanstack/react-router';
import { ArrowLeftRight } from 'lucide-react';
import { useEffect, useState } from 'react';
import {
  listAccountsOptions,
  listTransactionsInfiniteQueryKey,
} from '@/api/@tanstack/react-query.gen';
import { listTransactions } from '@/api/sdk.gen';
import type { TransactionKind, TransactionOut, TransactionStatus } from '@/api/types.gen';
import { PageHeader } from '@/components/app-shell';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectLabel,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { Skeleton } from '@/components/ui/skeleton';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { errorMessage } from '@/lib/errors';
import { formatDate, formatMoney, parseDate } from '@/lib/format';
import { cn } from '@/lib/utils';
import { activeGroups, CategoryPicker, useCategories } from './category-picker';
import { TransactionSheet, transactionTitle } from './transaction-sheet';
import { SOURCE_LABELS, useUpdateTransaction } from './use-transaction-edits';

const PAGE_SIZE = 50;
const SEARCH_DELAY_MS = 300;
const ALL = 'all'; // Select items can't have an empty value
const UNCATEGORIZED = 'uncategorized';
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
  category?: string; // a category or group ID, or "uncategorized"
  counterparty?: string;
  from?: string; // "YYYY-MM-DD": the first day shown
  to?: string; // "YYYY-MM-DD": the last day shown
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

  // Typing updates the URL (and the query) once the user pauses.
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

  const accounts = useQuery(listAccountsOptions());
  const accountNames = new Map(accounts.data?.map((account) => [account.id, account.name]));
  const groups = activeGroups(useCategories().data);
  const update = useUpdateTransaction();
  const [openId, setOpenId] = useState<string | null>(null);

  const filters = {
    account_id: search.account,
    q: search.q,
    status: search.status,
    kind: search.kind,
    category_id: search.category === UNCATEGORIZED ? undefined : search.category,
    uncategorized: search.category === UNCATEGORIZED ? true : undefined,
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
  const open = rows.find((row) => row.id === openId);

  return (
    <>
      <PageHeader title="Transactions" description="Newest first, as the banks report them." />
      <div className="mb-4 flex flex-wrap gap-2">
        <Input
          className="w-72"
          placeholder="Search description, merchant or note"
          aria-label="Search transactions"
          value={text}
          onChange={(event) => setText(event.target.value)}
        />
        <Select
          value={search.account ?? ALL}
          onValueChange={(value) => setSearch({ account: value === ALL ? undefined : value })}
        >
          <SelectTrigger className="w-48" aria-label="Account">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={ALL}>All accounts</SelectItem>
            {accounts.data?.map((account) => (
              <SelectItem key={account.id} value={account.id}>
                {account.name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Select
          value={search.kind ?? ALL}
          onValueChange={(value) =>
            setSearch({ kind: value === ALL ? undefined : (value as TransactionKind) })
          }
        >
          <SelectTrigger className="w-36" aria-label="Kind">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={ALL}>All kinds</SelectItem>
            {KINDS.map((kind) => (
              <SelectItem key={kind.value} value={kind.value}>
                {kind.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Select
          value={search.category ?? ALL}
          onValueChange={(value) => setSearch({ category: value === ALL ? undefined : value })}
        >
          <SelectTrigger className="w-52" aria-label="Category">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={ALL}>All categories</SelectItem>
            <SelectItem value={UNCATEGORIZED}>Uncategorized</SelectItem>
            {groups.map((group) => (
              <SelectGroup key={group.id}>
                <SelectLabel>{group.name}</SelectLabel>
                <SelectItem value={group.id}>All of {group.name}</SelectItem>
                {group.children.map((child) => (
                  <SelectItem key={child.id} value={child.id}>
                    {child.name}
                  </SelectItem>
                ))}
              </SelectGroup>
            ))}
          </SelectContent>
        </Select>
        <Select
          value={search.status ?? ALL}
          onValueChange={(value) =>
            setSearch({ status: value === ALL ? undefined : (value as TransactionStatus) })
          }
        >
          <SelectTrigger className="w-32" aria-label="Status">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={ALL}>Any status</SelectItem>
            <SelectItem value="booked">Booked</SelectItem>
            <SelectItem value="pending">Pending</SelectItem>
          </SelectContent>
        </Select>
        {search.counterparty && (
          <Button variant="ghost" onClick={() => setSearch({ counterparty: undefined })}>
            Clear merchant filter
          </Button>
        )}
        {(search.from || search.to) && (
          <Button variant="ghost" onClick={() => setSearch({ from: undefined, to: undefined })}>
            Clear dates ({dateRange(search.from, search.to)})
          </Button>
        )}
      </div>

      {transactions.isPending && <Skeleton className="h-64 w-full" />}
      {transactions.isError && (
        <Alert variant="destructive">
          <AlertTitle>Couldn't load transactions</AlertTitle>
          <AlertDescription>{errorMessage(transactions.error)}</AlertDescription>
        </Alert>
      )}
      {transactions.isSuccess && rows.length === 0 && (
        <p className="text-sm text-muted-foreground">No transactions match.</p>
      )}
      {rows.length > 0 && (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="w-28">Date</TableHead>
              <TableHead>Description</TableHead>
              <TableHead className="w-52">Category</TableHead>
              <TableHead>Account</TableHead>
              <TableHead className="text-right">Amount</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map((row) => (
              <TableRow key={row.id}>
                <TableCell className="text-muted-foreground tabular-nums">
                  {formatDate(row.occurred_on)}
                </TableCell>
                <TableCell className="max-w-sm">
                  <button
                    type="button"
                    className="block w-full text-left"
                    onClick={() => setOpenId(row.id)}
                  >
                    <div className="truncate font-medium hover:underline">
                      {transactionTitle(row)}
                    </div>
                    {row.description && row.description !== transactionTitle(row) && (
                      <div className="truncate text-xs text-muted-foreground">
                        {row.description}
                      </div>
                    )}
                  </button>
                </TableCell>
                <TableCell>
                  <CategoryCell
                    row={row}
                    disabled={update.isPending}
                    onChange={(categoryId) =>
                      update.mutate({
                        path: { transaction_id: row.id },
                        body: { category_id: categoryId },
                      })
                    }
                  />
                </TableCell>
                <TableCell className="text-sm text-muted-foreground">
                  {accountNames.get(row.account_id) ?? ''}
                </TableCell>
                <TableCell className="text-right">
                  <div className="flex items-center justify-end gap-2">
                    {row.status === 'pending' && <Badge variant="outline">Pending</Badge>}
                    <span
                      className={cn(
                        'font-medium tabular-nums',
                        row.kind === 'income' && 'text-emerald-700 dark:text-emerald-400',
                        row.kind === 'transfer' && 'text-muted-foreground',
                      )}
                    >
                      {formatMoney(row.amount, row.currency)}
                    </span>
                  </div>
                  {row.original_amount && row.original_currency && (
                    <div className="text-xs text-muted-foreground tabular-nums">
                      {formatMoney(row.original_amount, row.original_currency)}
                    </div>
                  )}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
      {transactions.hasNextPage && (
        <div className="mt-4 flex justify-center">
          <Button
            variant="outline"
            disabled={transactions.isFetchingNextPage}
            onClick={() => transactions.fetchNextPage()}
          >
            {transactions.isFetchingNextPage ? 'Loading…' : 'Load more'}
          </Button>
        </div>
      )}
      <TransactionSheet
        transaction={open}
        accountName={open ? (accountNames.get(open.account_id) ?? '') : ''}
        onOpenChange={(isOpen) => !isOpen && setOpenId(null)}
      />
    </>
  );
}

function CategoryCell({
  row,
  disabled,
  onChange,
}: {
  row: TransactionOut;
  disabled: boolean;
  onChange: (categoryId: string | null) => void;
}) {
  if (row.kind === 'transfer' && !row.category) {
    return (
      <span className="flex items-center gap-1.5 px-2 text-sm text-muted-foreground">
        <ArrowLeftRight className="size-3.5 shrink-0" aria-hidden />
        <span className="truncate">
          {row.transfer
            ? `${Number(row.amount) < 0 ? 'To' : 'From'} ${row.transfer.other_account_name}`
            : 'Transfer'}
        </span>
      </span>
    );
  }
  const { category } = row;
  return (
    <CategoryPicker
      value={category?.source === 'manual' ? category.id : null}
      onChange={onChange}
      disabled={disabled}
    >
      {category ? (
        <span
          title={SOURCE_LABELS[category.source]}
          className={cn(category.source !== 'manual' && 'text-muted-foreground')}
        >
          {category.name}
        </span>
      ) : (
        <span className="text-muted-foreground italic">Uncategorized</span>
      )}
    </CategoryPicker>
  );
}
