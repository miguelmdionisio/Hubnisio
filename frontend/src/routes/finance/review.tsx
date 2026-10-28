import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Link } from '@tanstack/react-router';
import { Check, CircleCheck, Keyboard, SkipForward, Split } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import { toast } from 'sonner';
import { listTransactionsQueryKey } from '@/api/@tanstack/react-query.gen';
import { listTransactions, updateTransaction } from '@/api/sdk.gen';
import type { ListTransactionsData, TransactionOut } from '@/api/types.gen';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import { Skeleton } from '@/components/ui/skeleton';
import { errorMessage } from '@/lib/errors';
import { formatDate, formatMoney } from '@/lib/format';
import { currentMonth, monthStart } from '@/lib/months';
import { cn } from '@/lib/utils';
import { CategoryPicker, categoryNames, useCategories } from './category-picker';
import { type ReviewGroup, reviewGroups, withSkippedLast } from './review-queue';
import { TransactionSheet } from './transaction-sheet';
import { useAccounts } from './use-accounts';
import { invalidateUserLayer } from './use-transaction-edits';

const PAGE = 200; // the most the API returns at once
const QUEUE_CAP = 1000; // per kind of open transaction; beyond that, the queue says so
const SHOWN = 5; // a group's transactions listed before "Show all"
const UPCOMING = 5;

type Fetched = { items: TransactionOut[]; more: boolean };

async function fetchAll(
  query: NonNullable<ListTransactionsData['query']>,
  signal: AbortSignal,
): Promise<Fetched> {
  const items: TransactionOut[] = [];
  let cursor: string | undefined;
  do {
    const { data } = await listTransactions({
      query: { ...query, limit: PAGE, cursor },
      signal,
      throwOnError: true,
    });
    items.push(...data.items);
    cursor = data.next_cursor ?? undefined;
  } while (cursor && items.length < QUEUE_CAP);
  return { items, more: cursor !== undefined };
}

/** Every open transaction: uncategorized, or with a category an AI suggested. */
export function useReviewQueue() {
  return useQuery({
    // Under listTransactions' key, so every edit to a transaction refreshes it.
    queryKey: [...listTransactionsQueryKey(), 'review'],
    queryFn: async ({ signal }) => {
      const [uncategorized, suggested] = await Promise.all([
        fetchAll({ uncategorized: true }, signal),
        fetchAll({ source: 'ai' }, signal),
      ]);
      return {
        items: [...uncategorized.items, ...suggested.items],
        more: uncategorized.more || suggested.more,
      };
    },
  });
}

/** The category chosen for a group. A rare transfer is marked from the transaction's sheet. */
type Decision = { categoryId: string; name: string };

function describe(decision: Decision, group: ReviewGroup): string {
  const count = group.transactions.length;
  return count === 1
    ? `${decision.name}: ${group.title}`
    : `${decision.name} for ${count} from ${group.title}`;
}

/** Decide a whole group at once; undo puts its transactions back in the queue. */
function useDecide() {
  const queryClient = useQueryClient();
  const send = (ids: string[], categoryId: string | null) =>
    Promise.all(
      ids.map((id) =>
        updateTransaction({
          path: { transaction_id: id },
          body: { category_id: categoryId },
          throwOnError: true,
        }),
      ),
    );
  const decide = useMutation({
    mutationFn: ({ group, decision }: { group: ReviewGroup; decision: Decision }) =>
      send(
        group.transactions.map((transaction) => transaction.id),
        decision.categoryId,
      ),
    onSettled: () => invalidateUserLayer(queryClient),
  });
  const undo = useMutation({
    mutationFn: (group: ReviewGroup) =>
      send(
        group.transactions.map((transaction) => transaction.id),
        null,
      ),
    onSettled: () => invalidateUserLayer(queryClient),
  });
  return { decide, undo };
}

/** Typing in a field, or a menu or dialog open: the review's keys stay out of the way. */
function typing(event: KeyboardEvent): boolean {
  const target = event.target instanceof Element ? event.target : null;
  return Boolean(
    event.metaKey ||
      event.ctrlKey ||
      event.altKey ||
      target?.closest('input, textarea, select, [contenteditable], [role="dialog"]') ||
      document.querySelector('[data-slot="popover-content"], [role="dialog"]'),
  );
}

export function ReviewQueue() {
  const queue = useReviewQueue();
  const { decide, undo } = useDecide();
  const accountNames = useAccounts().names;
  const [hidden, setHidden] = useState<ReadonlySet<string>>(new Set()); // decided, not yet refetched
  const [skipped, setSkipped] = useState<string[]>([]);
  const [split, setSplit] = useState<ReadonlySet<string>>(new Set());
  const [decided, setDecided] = useState(0);
  const [pickerOpen, setPickerOpen] = useState(false);
  const [openId, setOpenId] = useState<string | null>(null);
  const [expanded, setExpanded] = useState(false);
  const [position, setPosition] = useState(0);
  const last = useRef<{ group: ReviewGroup; hadSuggestion: boolean } | null>(null);
  const cardRef = useRef<HTMLElement>(null);

  const items = queue.data?.items ?? [];
  const groups = withSkippedLast(
    reviewGroups(items, monthStart(currentMonth()), split),
    skipped,
  ).filter((group) => !group.transactions.every((transaction) => hidden.has(transaction.id)));
  const index = Math.min(position, Math.max(groups.length - 1, 0));
  const focused = groups[index];
  const left = groups.reduce((sum, group) => sum + group.transactions.length, 0);
  const thisMonth = groups
    .filter((group) => group.section === 'this-month')
    .reduce((sum, group) => sum + group.transactions.length, 0);
  const open = items.find((transaction) => transaction.id === openId);

  const focusKey = focused?.key;
  const arrived = useRef(false);
  // A new card in focus: fold its list, and after the first, take keyboard and screen-reader
  // focus to it.
  useEffect(() => {
    setExpanded(false);
    if (!focusKey) return;
    if (arrived.current) cardRef.current?.focus({ preventScroll: true });
    arrived.current = true;
  }, [focusKey]);

  const hide = (group: ReviewGroup, gone: boolean) =>
    setHidden((current) => {
      const next = new Set(current);
      for (const transaction of group.transactions) {
        if (gone) next.add(transaction.id);
        else next.delete(transaction.id);
      }
      return next;
    });

  const apply = (group: ReviewGroup, decision: Decision) => {
    hide(group, true);
    decide.mutate(
      { group, decision },
      {
        onSuccess: () => {
          setDecided((count) => count + 1);
          const hadSuggestion = group.transactions.some(
            (transaction) => transaction.category?.source === 'ai',
          );
          last.current = { group, hadSuggestion };
          toast.success(describe(decision, group), {
            action: { label: 'Undo', onClick: () => revert(group, hadSuggestion) },
          });
        },
        onError: (error) => {
          hide(group, false);
          toast.error(errorMessage(error));
        },
      },
    );
  };

  const revert = (group: ReviewGroup, hadSuggestion: boolean) =>
    undo.mutate(group, {
      onSuccess: () => {
        hide(group, false);
        setDecided((count) => Math.max(count - 1, 0));
        toast(
          'Back in the queue.',
          hadSuggestion
            ? { description: "The AI's suggestion is gone: it's uncategorized now." }
            : undefined,
        );
      },
      onError: (error) => toast.error(errorMessage(error)),
    });

  const approve = (group: ReviewGroup) => {
    const { suggestion } = group;
    if (suggestion && suggestion !== 'mixed') {
      apply(group, { categoryId: suggestion.id, name: suggestion.name });
    }
  };
  const skip = (group: ReviewGroup) =>
    setSkipped((current) => [...current.filter((key) => key !== group.key), group.key]);
  const splitOut = (transaction: TransactionOut) =>
    setSplit((current) => new Set(current).add(transaction.id));

  // The review's keys, while nothing else has the keyboard.
  const keys = useRef<(event: KeyboardEvent) => void>(() => {});
  keys.current = (event) => {
    if (typing(event) || !focused) return;
    const actions: Record<string, () => void> = {
      j: () => setPosition(Math.min(index + 1, groups.length - 1)),
      k: () => setPosition(Math.max(index - 1, 0)),
      a: () => approve(focused),
      c: () => setPickerOpen(true),
      s: () => skip(focused),
      x: () => {
        const [first] = focused.transactions;
        if (first && focused.transactions.length > 1) splitOut(first);
      },
      enter: () => setOpenId(focused.transactions[0]?.id ?? null),
      u: () => {
        const undoable = last.current;
        last.current = null;
        if (undoable) revert(undoable.group, undoable.hadSuggestion);
      },
    };
    const action = actions[event.key === 'Enter' ? 'enter' : event.key];
    if (action) {
      event.preventDefault();
      action();
    }
  };
  useEffect(() => {
    const listener = (event: KeyboardEvent) => keys.current(event);
    window.addEventListener('keydown', listener);
    return () => window.removeEventListener('keydown', listener);
  }, []);

  if (queue.isPending) return <Skeleton className="h-72 w-full max-w-2xl" />;
  if (queue.isError) {
    return (
      <Alert variant="destructive" className="max-w-2xl">
        <AlertTitle>Couldn't load the review</AlertTitle>
        <AlertDescription>
          {errorMessage(queue.error)}{' '}
          <button
            type="button"
            className="underline underline-offset-4"
            onClick={() => queue.refetch()}
          >
            Try again
          </button>
        </AlertDescription>
      </Alert>
    );
  }
  if (!focused) return <QueueEmpty afterWork={decided > 0} />;

  return (
    <div className="max-w-2xl pb-28 md:pb-0">
      <div className="mb-3 flex items-baseline justify-between gap-4">
        <p className="text-sm" aria-live="polite">
          <span className="font-medium tabular-nums">{left}</span> left
          {thisMonth > 0 && (
            <span className="text-muted-foreground">
              {' '}
              · <span className="tabular-nums">{thisMonth}</span> this month
            </span>
          )}
          {queue.data.more && <span className="text-muted-foreground"> · more after these</span>}
        </p>
        <KeysHelp />
      </div>

      <ReviewCard
        ref={cardRef}
        group={focused}
        expanded={expanded}
        onExpand={() => setExpanded(true)}
        accountNames={accountNames}
        busy={decide.isPending || undo.isPending}
        pickerOpen={pickerOpen}
        onPickerOpenChange={setPickerOpen}
        onApprove={() => approve(focused)}
        onChoose={(categoryId, name) => apply(focused, { categoryId, name })}
        onSkip={() => skip(focused)}
        onOpen={setOpenId}
        onSplit={splitOut}
      />

      {groups.length > index + 1 && (
        <div className="mt-6">
          <h3 className="mb-2 text-sm font-medium text-muted-foreground">Next</h3>
          <ul className="divide-y rounded-lg border">
            {groups.slice(index + 1, index + 1 + UPCOMING).map((group, offset) => (
              <li key={group.key}>
                <button
                  type="button"
                  className="flex w-full items-baseline justify-between gap-3 px-3 py-2.5 text-left text-sm text-muted-foreground hover:bg-muted/50"
                  onClick={() => setPosition(index + 1 + offset)}
                >
                  <span className="truncate">{group.title}</span>
                  <span className="shrink-0 tabular-nums">
                    {group.transactions.length > 1 && `${group.transactions.length} · `}
                    {group.total ? formatMoney(group.total.amount, group.total.currency) : ''}
                  </span>
                </button>
              </li>
            ))}
          </ul>
          {groups.length > index + 1 + UPCOMING && (
            <p className="mt-2 text-xs text-muted-foreground">
              and {groups.length - index - 1 - UPCOMING} more
            </p>
          )}
        </div>
      )}

      <TransactionSheet
        transaction={open}
        accountName={open ? (accountNames.get(open.account_id) ?? '') : ''}
        onOpenChange={(isOpen) => !isOpen && setOpenId(null)}
      />
    </div>
  );
}

function ReviewCard({
  ref,
  group,
  expanded,
  onExpand,
  accountNames,
  busy,
  pickerOpen,
  onPickerOpenChange,
  onApprove,
  onChoose,
  onSkip,
  onOpen,
  onSplit,
}: {
  ref: React.Ref<HTMLElement>;
  group: ReviewGroup;
  expanded: boolean;
  onExpand: () => void;
  accountNames: Map<string, string>;
  busy: boolean;
  pickerOpen: boolean;
  onPickerOpenChange: (open: boolean) => void;
  onApprove: () => void;
  onChoose: (categoryId: string, name: string) => void;
  onSkip: () => void;
  onOpen: (transactionId: string) => void;
  onSplit: (transaction: TransactionOut) => void;
}) {
  const { transactions, suggestion } = group;
  const count = transactions.length;
  const shown = expanded ? transactions : transactions.slice(0, SHOWN);
  const headingId = `review-${group.key}`;
  const suggested = suggestion && suggestion !== 'mixed' ? suggestion : null;
  const names = categoryNames(useCategories().data);
  return (
    <section
      ref={ref}
      tabIndex={-1}
      aria-labelledby={headingId}
      className="rounded-xl border bg-card p-4 shadow-sm outline-none focus-visible:ring-2 focus-visible:ring-ring md:p-5"
    >
      <h2
        id={headingId}
        className="line-clamp-2 text-lg font-semibold break-words"
        title={group.title}
      >
        {group.title}
      </h2>
      <p className="mt-0.5 text-sm text-muted-foreground">
        {group.section === 'this-month' ? 'This month' : 'Earlier'} ·{' '}
        {count === 1 ? '1 transaction' : `${count} transactions`}
        {group.total && count > 1 && (
          <>
            {' '}
            ·{' '}
            <span className="tabular-nums">
              {formatMoney(group.total.amount, group.total.currency)}
            </span>
          </>
        )}
      </p>
      <p className="mt-3 text-sm">
        {suggested ? (
          <>
            AI suggests <span className="font-medium">{suggested.name}</span>
            {suggested.group_name && suggested.group_name !== suggested.name && (
              <span className="text-muted-foreground"> ({suggested.group_name})</span>
            )}
          </>
        ) : suggestion === 'mixed' ? (
          <span className="text-muted-foreground">
            The AI suggested different categories here: choose one.
          </span>
        ) : (
          <span className="text-muted-foreground">No suggestion: choose a category.</span>
        )}
      </p>

      <ul className="mt-3 divide-y border-y text-sm">
        {shown.map((transaction) => (
          <li key={transaction.id} className="flex items-center gap-2 py-1.5">
            <button
              type="button"
              className="flex min-w-0 flex-1 items-baseline gap-3 rounded-sm py-1 text-left hover:underline"
              onClick={() => onOpen(transaction.id)}
            >
              <span className="shrink-0 text-xs whitespace-nowrap text-muted-foreground tabular-nums">
                {formatDate(transaction.occurred_on)}
              </span>
              <span className="min-w-0 flex-1 truncate">
                {transaction.description && transaction.description !== group.title
                  ? transaction.description
                  : (accountNames.get(transaction.account_id) ?? '')}
              </span>
              <span className="shrink-0 font-medium tabular-nums">
                {formatMoney(transaction.amount, transaction.currency)}
              </span>
            </button>
            {count > 1 && (
              <Button
                variant="ghost"
                size="icon-sm"
                className="size-9 shrink-0 text-muted-foreground md:size-8"
                aria-label={`Split out the one on ${formatDate(transaction.occurred_on)}`}
                title="Split out: decide this one on its own"
                onClick={() => onSplit(transaction)}
              >
                <Split aria-hidden />
              </Button>
            )}
          </li>
        ))}
      </ul>
      {!expanded && count > SHOWN && (
        <button
          type="button"
          className="mt-2 text-sm text-muted-foreground underline underline-offset-4"
          onClick={onExpand}
        >
          Show all {count}
        </button>
      )}

      {/* On a phone the actions sit at the bottom of the screen, in thumb reach. */}
      <div className="fixed inset-x-0 bottom-0 z-30 grid grid-cols-2 gap-2 border-t bg-background/95 p-3 backdrop-blur md:static md:mt-5 md:flex md:flex-wrap md:border-0 md:bg-transparent md:p-0 md:backdrop-blur-none">
        {suggested && (
          <Button className="col-span-2 h-11 md:h-9" disabled={busy} onClick={onApprove}>
            <Check aria-hidden />
            Approve {suggested.name}
          </Button>
        )}
        <CategoryPicker
          value={null}
          noneLabel={null}
          open={pickerOpen}
          onOpenChange={onPickerOpenChange}
          label={`Choose a category for ${group.title}`}
          disabled={busy}
          onChange={(categoryId) => {
            if (categoryId) onChoose(categoryId, names.get(categoryId) ?? 'Category');
          }}
          className={cn(
            'h-11 max-w-none justify-center font-medium md:h-9',
            suggested
              ? 'border border-input bg-background'
              : 'bg-primary text-primary-foreground hover:bg-primary/90 hover:text-primary-foreground',
          )}
        >
          {suggested ? 'Other category' : 'Choose category'}
        </CategoryPicker>
        <Button variant="ghost" className="h-11 md:h-9" onClick={onSkip}>
          <SkipForward aria-hidden />
          Skip
        </Button>
      </div>
    </section>
  );
}

function QueueEmpty({ afterWork }: { afterWork: boolean }) {
  return (
    <div className="flex max-w-2xl flex-col items-start gap-2 rounded-xl border bg-card p-6">
      <CircleCheck className="size-6 text-emerald-700 dark:text-emerald-400" aria-hidden />
      <h2 className="text-lg font-semibold">{afterWork ? 'Queue empty' : 'Nothing to review'}</h2>
      <p className="text-sm text-muted-foreground">
        {afterWork
          ? 'Everything has a category, and every AI suggestion has an answer.'
          : 'Every transaction has a category. New ones show up here after the next sync.'}
      </p>
      <Link to="/finance/transactions" search={{}} className="text-sm underline underline-offset-4">
        See all transactions
      </Link>
    </div>
  );
}

const KEYS: [string, string][] = [
  ['a', 'Approve the suggestion'],
  ['c', 'Choose a category'],
  ['s', 'Skip for now'],
  ['x', 'Split out the newest'],
  ['Enter', 'Open the newest'],
  ['u', 'Undo the last one'],
  ['j / k', 'Next / previous'],
];

function KeysHelp() {
  return (
    <Popover>
      <PopoverTrigger asChild>
        <Button variant="ghost" size="sm" className="hidden text-muted-foreground md:inline-flex">
          <Keyboard aria-hidden />
          Keys
        </Button>
      </PopoverTrigger>
      <PopoverContent align="end" className="w-64">
        <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1.5 text-sm">
          {KEYS.map(([key, action]) => (
            <div key={key} className="contents">
              <dt>
                <kbd className="rounded border bg-muted px-1.5 font-mono text-xs">{key}</kbd>
              </dt>
              <dd className="text-muted-foreground">{action}</dd>
            </div>
          ))}
        </dl>
      </PopoverContent>
    </Popover>
  );
}
