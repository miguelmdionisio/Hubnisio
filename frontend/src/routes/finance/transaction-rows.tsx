import { ArrowLeftRight, Check } from 'lucide-react';
import { type ReactNode, useState } from 'react';
import type { TransactionOut } from '@/api/types.gen';
import { Chip, useCategoryStyles } from '@/components/category-chip';
import { Skeleton } from '@/components/ui/skeleton';
import { formatDay, formatMoney, LOCALE, parseDate } from '@/lib/format';
import { cn } from '@/lib/utils';
import { isRepayment, repaymentLabel } from './repayments';
import { signedMoney, TransactionSheet, transactionTitle } from './transaction-sheet';
import { useAccounts } from './use-accounts';
import { SOURCE_LABELS } from './use-transaction-edits';

export const rowClass =
  'grid w-full grid-cols-[40px_minmax(0,1fr)_auto] items-center gap-3.5 rounded-[14px] px-3 py-2.5 text-left transition-colors hover:bg-surface-2';

/** The soft panel a list's rows sit in. */
export function ListPanel({ children, className }: { children: ReactNode; className?: string }) {
  return <div className={cn('rounded-[18px] bg-surface p-1.5', className)}>{children}</div>;
}

/** "Wed 14 Oct", with the year when it isn't this one. */
export function dayHeading(day: string): string {
  const date = parseDate(day);
  if (date.getFullYear() === new Date().getFullYear()) return formatDay(day);
  return new Intl.DateTimeFormat(LOCALE, {
    weekday: 'short',
    day: 'numeric',
    month: 'short',
    year: 'numeric',
  }).format(date);
}

/** A payment's row: chip, merchant, category and account, amount; it opens the payment. */
function TransactionRow({
  transaction,
  accountName,
  onOpen,
  onApprove,
}: {
  transaction: TransactionOut;
  accountName: string;
  onOpen: () => void;
  onApprove?: () => void;
}) {
  const styleOf = useCategoryStyles();
  const { category, transfer } = transaction;
  const style = styleOf(category?.id);
  const amount = Number(transaction.amount);
  const title = transactionTitle(transaction);
  const isTransfer = transaction.kind === 'transfer' && !category;
  const what = isTransfer
    ? transfer
      ? `${amount < 0 ? 'To' : 'From'} ${transfer.other_account_name}`
      : 'Transfer'
    : category
      ? category.name
      : transaction.kind === 'income'
        ? 'Income'
        : style.name;
  return (
    <div className="flex items-center gap-1">
      <button type="button" onClick={onOpen} className={rowClass}>
        {isTransfer ? (
          <span
            aria-hidden
            className="grid size-10 place-items-center rounded-full bg-surface-2 text-muted-foreground"
          >
            <ArrowLeftRight className="size-[18px]" />
          </span>
        ) : (
          <Chip style={style} letter={category ? title : undefined} />
        )}
        <span className="min-w-0">
          <span className="block truncate text-[15px] font-semibold">{title}</span>
          <span className="block truncate text-[13px] text-muted-foreground">
            <span title={category ? SOURCE_LABELS[category.source] : undefined}>
              {what}
              {category?.source === 'ai' && (
                <span className="ml-1 font-semibold text-primary">AI</span>
              )}
            </span>{' '}
            · {accountName}
            {transaction.status === 'pending' && ' · Pending'}
          </span>
        </span>
        <span className="text-right tabular-nums">
          <span
            className={cn(
              'block text-[15px] font-[650]',
              transaction.kind === 'income' && 'text-good',
              isTransfer && 'text-muted-foreground',
            )}
          >
            {signedMoney(transaction)}
          </span>
          {isRepayment(transaction) && (
            <span className="block text-[13px] text-muted-foreground">
              {repaymentLabel(transaction)}
            </span>
          )}
          {transaction.original_amount && transaction.original_currency && (
            <span className="block text-[13px] text-muted-foreground">
              {formatMoney(transaction.original_amount, transaction.original_currency)}
            </span>
          )}
        </span>
      </button>
      {onApprove && category?.source === 'ai' && (
        <button
          type="button"
          aria-label={`Approve ${category.name}`}
          title="Approve: keep this category"
          onClick={onApprove}
          className="grid size-9 shrink-0 place-items-center rounded-full text-primary hover:bg-surface-2"
        >
          <Check className="size-4" aria-hidden />
        </button>
      )}
    </div>
  );
}

/** Transactions grouped by day, newest first; a row opens the transaction's sheet. */
export function TransactionDays({
  items,
  pending,
  showDays = true,
  onApprove,
  empty = 'No transactions',
  children,
}: {
  items: TransactionOut[] | undefined;
  pending: boolean;
  showDays?: boolean;
  onApprove?: (transaction: TransactionOut) => void;
  empty?: string;
  children?: ReactNode; // after the list: a "Load more"
}) {
  const { names } = useAccounts();
  const [openId, setOpenId] = useState<string | null>(null);
  if (pending) return <Skeleton className="mt-4 h-40 w-full rounded-[18px]" />;
  if (!items?.length) return <p className="py-7 text-center text-muted-foreground">{empty}</p>;
  const days = new Map<string, TransactionOut[]>();
  for (const item of items) {
    days.set(item.occurred_on, [...(days.get(item.occurred_on) ?? []), item]);
  }
  const open = items.find((item) => item.id === openId);
  return (
    <>
      {[...days].map(([day, list]) => (
        <section key={day} aria-label={dayHeading(day)}>
          {showDays && (
            <h3 className="mt-[18px] mb-1.5 text-[13px] font-[650] text-muted-foreground">
              {dayHeading(day)}
            </h3>
          )}
          <ListPanel className={showDays ? undefined : 'mt-4'}>
            <ul>
              {list.map((transaction) => (
                <li key={transaction.id}>
                  <TransactionRow
                    transaction={transaction}
                    accountName={names.get(transaction.account_id) ?? '—'}
                    onOpen={() => setOpenId(transaction.id)}
                    onApprove={onApprove && (() => onApprove(transaction))}
                  />
                </li>
              ))}
            </ul>
          </ListPanel>
        </section>
      ))}
      {children}
      <TransactionSheet
        transaction={open}
        accountName={open ? (names.get(open.account_id) ?? '—') : ''}
        onOpenChange={(isOpen) => !isOpen && setOpenId(null)}
      />
    </>
  );
}
