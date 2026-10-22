import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Link, useNavigate, useSearch } from '@tanstack/react-router';
import { TrendingDown, TrendingUp } from 'lucide-react';
import { type FormEvent, useState } from 'react';
import { toast } from 'sonner';
import {
  listRecurringOptions,
  listRecurringQueryKey,
  listUpcomingPaymentsQueryKey,
  updateRecurringMutation,
} from '@/api/@tanstack/react-query.gen';
import type { Cadence, RecurringOut, RecurringUpdate, Review } from '@/api/types.gen';
import { PageHeader } from '@/components/app-shell';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Skeleton } from '@/components/ui/skeleton';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { errorMessage } from '@/lib/errors';
import { formatDate, formatMoney, formatShortMonth } from '@/lib/format';

const TABS: { value: Review; label: string; description: string; empty: string }[] = [
  {
    value: 'suggested',
    label: 'Suggested',
    description:
      'Found in your transactions. Confirm the ones that are real; only confirmed ones count in upcoming payments.',
    empty: "Nothing to review. New recurring payments show up here when they're found.",
  },
  {
    value: 'confirmed',
    label: 'Confirmed',
    description: 'These count in upcoming payments.',
    empty: 'No confirmed payments yet. Confirm a suggestion to see it in upcoming payments.',
  },
  {
    value: 'dismissed',
    label: 'Dismissed',
    description: 'Hidden from the suggestions. Restore one if it was a mistake.',
    empty: 'Nothing dismissed.',
  },
];

const CADENCES: Record<Cadence, string> = {
  weekly: 'Weekly',
  monthly: 'Monthly',
  quarterly: 'Quarterly',
  yearly: 'Yearly',
};

export type RecurringSearch = { tab?: Review }; // suggested when absent

export function validateRecurringSearch(search: Record<string, unknown>): RecurringSearch {
  return { tab: TABS.find((tab) => tab.value === search.tab)?.value };
}

function useRecurringEdits() {
  const queryClient = useQueryClient();
  return useMutation({
    ...updateRecurringMutation(),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: listRecurringQueryKey() });
      queryClient.invalidateQueries({ queryKey: listUpcomingPaymentsQueryKey() });
    },
    onError: (error) => toast.error(errorMessage(error)),
  });
}

export function RecurringPage() {
  const search = useSearch({ from: '/finance/recurring' });
  const navigate = useNavigate({ from: '/finance/recurring' });
  const tab = search.tab ?? 'suggested';
  const series = useQuery(listRecurringOptions());
  const update = useRecurringEdits();
  const [renaming, setRenaming] = useState<RecurringOut | null>(null);

  const rows = (review: Review) => series.data?.filter((row) => row.review === review) ?? [];
  const change = (row: RecurringOut, body: RecurringUpdate, onDone?: () => void) =>
    update.mutate({ path: { series_id: row.id }, body }, { onSuccess: onDone });

  return (
    <>
      <PageHeader
        title="Recurring payments"
        description={TABS.find((option) => option.value === tab)?.description}
      />
      {series.isPending && <Skeleton className="h-64 w-full" />}
      {series.isError && (
        <Alert variant="destructive">
          <AlertTitle>Couldn't load recurring payments</AlertTitle>
          <AlertDescription>{errorMessage(series.error)}</AlertDescription>
        </Alert>
      )}
      {series.isSuccess && (
        <Tabs
          value={tab}
          onValueChange={(value) => navigate({ search: { tab: value as Review }, replace: true })}
        >
          <TabsList>
            {TABS.map((option) => (
              <TabsTrigger key={option.value} value={option.value}>
                {option.label}
                <span className="text-xs text-muted-foreground tabular-nums">
                  {rows(option.value).length}
                </span>
              </TabsTrigger>
            ))}
          </TabsList>
          {TABS.map((option) => (
            <TabsContent key={option.value} value={option.value}>
              {rows(option.value).length === 0 ? (
                <p className="py-2 text-sm text-muted-foreground">{option.empty}</p>
              ) : (
                <SeriesTable
                  rows={rows(option.value)}
                  disabled={update.isPending}
                  onRename={setRenaming}
                  onChange={change}
                />
              )}
            </TabsContent>
          ))}
        </Tabs>
      )}
      {renaming && (
        <RenameDialog
          series={renaming}
          pending={update.isPending}
          onClose={() => setRenaming(null)}
          onSave={(name) => change(renaming, { name }, () => setRenaming(null))}
        />
      )}
    </>
  );
}

function SeriesTable({
  rows,
  disabled,
  onRename,
  onChange,
}: {
  rows: RecurringOut[];
  disabled: boolean;
  onRename: (series: RecurringOut) => void;
  onChange: (series: RecurringOut, body: RecurringUpdate) => void;
}) {
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Payment</TableHead>
          <TableHead>Repeats</TableHead>
          <TableHead className="text-right">Amount</TableHead>
          <TableHead>Next expected</TableHead>
          <TableHead>Last seen</TableHead>
          <TableHead className="text-right">Times seen</TableHead>
          <TableHead>
            <span className="sr-only">Actions</span>
          </TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {rows.map((row) => (
          <SeriesRow
            key={row.id}
            series={row}
            disabled={disabled}
            onRename={() => onRename(row)}
            onChange={(body) => onChange(row, body)}
          />
        ))}
      </TableBody>
    </Table>
  );
}

function SeriesRow({
  series,
  disabled,
  onRename,
  onChange,
}: {
  series: RecurringOut;
  disabled: boolean;
  onRename: () => void;
  onChange: (body: RecurringUpdate) => void;
}) {
  const stopped = series.status === 'cancelled';
  return (
    <TableRow>
      <TableCell className="max-w-xs">
        <button
          type="button"
          title="Rename"
          className="block max-w-full truncate text-left font-medium hover:underline"
          onClick={onRename}
        >
          {series.name}
        </button>
        <div className="flex flex-wrap items-center gap-1.5 text-xs text-muted-foreground">
          {series.account_name}
          {series.kind === 'income' && <Badge variant="secondary">Income</Badge>}
          {series.status === 'dormant' && (
            <Badge variant="outline" title="Hasn't shown up when it was expected">
              Late
            </Badge>
          )}
          {stopped && <Badge variant="outline">Stopped</Badge>}
        </div>
      </TableCell>
      <TableCell>{CADENCES[series.cadence]}</TableCell>
      <TableCell className="text-right">
        <div className="font-medium tabular-nums">
          {series.amount_varies && '≈ '}
          {formatMoney(series.expected_amount, series.currency)}
        </div>
        <PriceChange series={series} />
      </TableCell>
      <TableCell className="tabular-nums">
        {stopped ? '—' : formatDate(series.next_expected_on)}
      </TableCell>
      <TableCell className="text-muted-foreground tabular-nums">
        {formatDate(series.last_seen_on)}
      </TableCell>
      <TableCell className="text-right tabular-nums">{series.occurrences}</TableCell>
      <TableCell>
        <div className="flex items-center justify-end gap-1">
          {series.counterparty_id && (
            <Button variant="ghost" size="sm" asChild>
              <Link
                to="/finance/transactions"
                search={{ counterparty: series.counterparty_id }}
                aria-label={`Transactions for ${series.name}`}
              >
                Transactions
              </Link>
            </Button>
          )}
          {actionsFor(series).map((action, index) => (
            <Button
              key={action.label}
              variant={index === 0 ? 'outline' : 'ghost'}
              size="sm"
              disabled={disabled}
              aria-label={`${action.label} ${series.name}`}
              onClick={() => onChange(action.body)}
            >
              {action.label}
            </Button>
          ))}
        </div>
      </TableCell>
    </TableRow>
  );
}

function actionsFor(series: RecurringOut): { label: string; body: RecurringUpdate }[] {
  const dismiss = { label: 'Dismiss', body: { review: 'dismissed' } } as const;
  switch (series.review) {
    case 'suggested':
      return [{ label: 'Confirm', body: { review: 'confirmed' } }, dismiss];
    case 'confirmed':
      return [
        series.status === 'cancelled'
          ? { label: 'Undo stopped', body: { cancelled: false } }
          : { label: 'Mark stopped', body: { cancelled: true } },
        dismiss,
      ];
    case 'dismissed':
      return [{ label: 'Restore', body: { review: 'suggested' } }];
  }
}

/** "Up 12% since Mar 2026": how the latest price compares with the one before. */
function PriceChange({ series }: { series: RecurringOut }) {
  if (series.previous_amount === null) return null;
  const before = Math.abs(Number(series.previous_amount));
  const now = Math.abs(Number(series.expected_amount));
  if (before === 0 || before === now) return null;

  const up = now > before;
  const percent = Math.max(1, Math.round((Math.abs(now - before) / before) * 100));
  // Paying more is bad news, getting paid less too.
  const worse = up !== (series.kind === 'income');
  const Icon = up ? TrendingUp : TrendingDown;
  return (
    <Badge
      variant={worse ? 'destructive' : 'secondary'}
      className="mt-1"
      title={`${formatMoney(series.previous_amount, series.currency)} before`}
    >
      <Icon aria-hidden />
      {up ? 'Up' : 'Down'} {percent}%
      {series.amount_changed_on && ` since ${formatShortMonth(series.amount_changed_on)}`}
    </Badge>
  );
}

function RenameDialog({
  series,
  pending,
  onClose,
  onSave,
}: {
  series: RecurringOut;
  pending: boolean;
  onClose: () => void;
  onSave: (name: string) => void;
}) {
  const [name, setName] = useState(series.name);
  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (name.trim() !== series.name) onSave(name.trim());
  };
  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="sm:max-w-sm">
        <form onSubmit={submit} className="space-y-4">
          <DialogHeader>
            <DialogTitle>Rename payment</DialogTitle>
            <DialogDescription>Leave it empty to use the name that was detected.</DialogDescription>
          </DialogHeader>
          <div className="space-y-2">
            <Label htmlFor="recurring-name">Name</Label>
            <Input
              id="recurring-name"
              value={name}
              autoFocus
              onChange={(event) => setName(event.target.value)}
            />
          </div>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={onClose}>
              Cancel
            </Button>
            <Button type="submit" disabled={pending || name.trim() === series.name}>
              Rename
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
