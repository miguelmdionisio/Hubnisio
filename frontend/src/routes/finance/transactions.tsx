import { useInfiniteQuery, useQuery } from '@tanstack/react-query';
import { useNavigate, useSearch } from '@tanstack/react-router';
import { useEffect, useState } from 'react';
import {
  listAccountsOptions,
  listTransactionsInfiniteQueryKey,
} from '@/api/@tanstack/react-query.gen';
import { listTransactions } from '@/api/sdk.gen';
import type { TransactionStatus } from '@/api/types.gen';
import { PageHeader } from '@/components/app-shell';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import {
  Select,
  SelectContent,
  SelectItem,
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
import { formatDate, formatMoney } from '@/lib/format';
import { cn } from '@/lib/utils';

const PAGE_SIZE = 50;
const SEARCH_DELAY_MS = 300;
const ALL = 'all'; // Select items can't have an empty value

export type TransactionSearch = {
  account?: string;
  q?: string;
  status?: TransactionStatus;
};

export function validateTransactionSearch(search: Record<string, unknown>): TransactionSearch {
  const text = (value: unknown) => (typeof value === 'string' && value ? value : undefined);
  const status =
    search.status === 'booked' || search.status === 'pending' ? search.status : undefined;
  return { account: text(search.account), q: text(search.q), status };
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

  const filters = { account_id: search.account, q: search.q, status: search.status };
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

  return (
    <>
      <PageHeader title="Transactions" description="Newest first, as the banks report them." />
      <div className="mb-4 flex flex-wrap gap-2">
        <Input
          className="w-72"
          placeholder="Search description or counterparty"
          aria-label="Search transactions"
          value={text}
          onChange={(event) => setText(event.target.value)}
        />
        <Select
          value={search.account ?? ALL}
          onValueChange={(value) => setSearch({ account: value === ALL ? undefined : value })}
        >
          <SelectTrigger className="w-56" aria-label="Account">
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
          value={search.status ?? ALL}
          onValueChange={(value) =>
            setSearch({ status: value === ALL ? undefined : (value as TransactionStatus) })
          }
        >
          <SelectTrigger className="w-36" aria-label="Status">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={ALL}>Any status</SelectItem>
            <SelectItem value="booked">Booked</SelectItem>
            <SelectItem value="pending">Pending</SelectItem>
          </SelectContent>
        </Select>
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
              <TableHead className="w-32">Date</TableHead>
              <TableHead>Description</TableHead>
              <TableHead>Account</TableHead>
              <TableHead className="text-right">Amount</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map((row) => {
              const income = Number(row.amount) > 0;
              return (
                <TableRow key={row.id}>
                  <TableCell className="text-muted-foreground tabular-nums">
                    {formatDate(row.occurred_on)}
                  </TableCell>
                  <TableCell className="max-w-md">
                    <div className="truncate font-medium">
                      {row.counterparty_name ?? row.description ?? '—'}
                    </div>
                    {row.counterparty_name && row.description && (
                      <div className="truncate text-xs text-muted-foreground">
                        {row.description}
                      </div>
                    )}
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
                          income && 'text-emerald-700 dark:text-emerald-400',
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
              );
            })}
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
    </>
  );
}
