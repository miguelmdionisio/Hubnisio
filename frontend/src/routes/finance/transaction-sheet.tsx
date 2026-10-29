import { Link } from '@tanstack/react-router';
import { ArrowLeftRight, Check } from 'lucide-react';
import { type ReactNode, useEffect, useState } from 'react';
import type { Source, TransactionKind, TransactionOut } from '@/api/types.gen';
import { Chip, useCategoryStyles } from '@/components/category-chip';
import { Pill } from '@/components/pills';
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
import { Sheet, SheetContent, SheetDescription, SheetTitle } from '@/components/ui/sheet';
import { Textarea } from '@/components/ui/textarea';
import { formatDate, formatMoney, LOCALE, parseDate } from '@/lib/format';
import { useIsDesktop } from '@/lib/media';
import { cn } from '@/lib/utils';
import { activeGroups, useCategories } from './category-picker';
import { MerchantPicker } from './merchant-picker';
import { isRepayment, repaymentLabel } from './repayments';
import {
  SOURCE_LABELS,
  useApproveSuggestions,
  useUnlinkTransfer,
  useUpdateTransaction,
} from './use-transaction-edits';

const AUTOMATIC = 'automatic'; // Select items can't have an empty value
const KINDS: { value: TransactionKind; label: string }[] = [
  { value: 'expense', label: 'Spending' },
  { value: 'income', label: 'Income' },
  { value: 'transfer', label: 'Transfer between own accounts' },
];

/** Who set the category, in a word or two. */
const SET_BY: Record<Source, string> = {
  manual: 'You',
  rule: 'Rule',
  counterparty: 'Merchant default',
  ai: 'AI suggestion',
  bank: 'Bank',
  auto: 'Automatic',
};

export function transactionTitle(transaction: TransactionOut): string {
  return (
    transaction.counterparty?.name ??
    transaction.counterparty_name ??
    transaction.description ??
    '—'
  );
}

/** "−€42.17", "+€600.00": a payment's amount with its direction. */
export function signedMoney(transaction: TransactionOut): string {
  const amount = Number(transaction.amount);
  return `${amount > 0 ? '+' : '−'}${formatMoney(Math.abs(amount), transaction.currency)}`;
}

/**
 * One transaction: who and how much, then its category in one click, then the rest. A side
 * panel on desktop, a bottom sheet on the phone.
 */
export function TransactionSheet({
  transaction,
  accountName,
  onOpenChange,
}: {
  transaction: TransactionOut | undefined;
  accountName: string;
  onOpenChange: (open: boolean) => void;
}) {
  const desktop = useIsDesktop();
  return (
    <Sheet open={transaction !== undefined} onOpenChange={onOpenChange}>
      <SheetContent
        side={desktop ? 'right' : 'bottom'}
        className={cn(
          'gap-0 overflow-y-auto bg-background shadow-pop',
          desktop
            ? 'w-full sm:max-w-[400px]'
            : 'max-h-[88dvh] rounded-t-[22px] border-0 pb-[env(safe-area-inset-bottom)]',
        )}
      >
        {transaction && <Details transaction={transaction} accountName={accountName} />}
      </SheetContent>
    </Sheet>
  );
}

function Details({
  transaction,
  accountName,
}: {
  transaction: TransactionOut;
  accountName: string;
}) {
  const update = useUpdateTransaction();
  const unlink = useUnlinkTransfer();
  const approve = useApproveSuggestions();
  const styleOf = useCategoryStyles();
  const change = (body: Parameters<typeof update.mutate>[0]['body']) =>
    update.mutate({ path: { transaction_id: transaction.id }, body });
  const { category, counterparty, transfer } = transaction;
  const title = transactionTitle(transaction);
  const style = styleOf(category?.id);
  const amount = Number(transaction.amount);
  const busy = update.isPending || approve.isPending;
  const approveIt = () => approve.mutate({ body: { transaction_ids: [transaction.id] } });

  return (
    <div className="px-[22px] pt-6 pb-6 text-sm">
      <header className="mb-5 flex flex-col items-center gap-2 text-center">
        <Chip style={style} letter={category ? title : undefined} size="lg" />
        <SheetTitle className="text-[17px] font-[650]">{title}</SheetTitle>
        <p
          className={cn(
            'text-[34px] leading-tight font-[750] tracking-[-0.02em] tabular-nums',
            amount > 0 && !isRepayment(transaction) && 'text-good',
          )}
        >
          {signedMoney(transaction)}
        </p>
        <SheetDescription className="sr-only">
          {formatDate(transaction.occurred_on)} · {accountName}
        </SheetDescription>
        {transaction.original_amount && transaction.original_currency && (
          <p className="text-muted-foreground tabular-nums">
            {formatMoney(transaction.original_amount, transaction.original_currency)}
          </p>
        )}
        {transaction.status === 'pending' && <Badge variant="outline">Pending</Badge>}
      </header>

      <dl className="rounded-2xl bg-surface px-3.5 py-1">
        <Fact term="Date">
          {new Intl.DateTimeFormat(LOCALE, {
            weekday: 'long',
            day: 'numeric',
            month: 'long',
            year: 'numeric',
          }).format(parseDate(transaction.occurred_on))}
        </Fact>
        <Fact term="Account">{accountName}</Fact>
        {transfer && (
          <Fact term="Transfer">
            <span className="flex items-center justify-end gap-1.5">
              <ArrowLeftRight className="size-4 text-muted-foreground" aria-hidden />
              {amount < 0 ? 'To' : 'From'} {transfer.other_account_name}
              <Button
                variant="ghost"
                size="xs"
                disabled={unlink.isPending}
                onClick={() => unlink.mutate({ path: { transfer_id: transfer.id } })}
                title={SOURCE_LABELS[transfer.source]}
              >
                Unlink
              </Button>
            </span>
          </Fact>
        )}
        <Fact term="Category set by">{category ? SET_BY[category.source] : '—'}</Fact>
        {category && isRepayment(transaction) && (
          <Fact term={repaymentLabel(transaction)}>
            {`Lowers ${category.name} by ${formatMoney(transaction.amount, transaction.currency)}`}
          </Fact>
        )}
      </dl>

      {(transaction.kind !== 'transfer' || category) && (
        <CategoryGrid
          current={category?.id ?? null}
          income={amount > 0 && transaction.kind === 'income'}
          disabled={busy}
          onPick={(id) =>
            category?.source === 'ai' && category.id === id
              ? approveIt()
              : change({ category_id: id })
          }
          action={
            category?.source === 'ai' ? (
              <Pill
                className="h-7 px-2.5 text-[13px] md:h-7 md:text-[13px]"
                disabled={busy}
                onClick={approveIt}
              >
                <Check aria-hidden />
                Approve
              </Pill>
            ) : category?.source === 'manual' ? (
              <button
                type="button"
                disabled={busy}
                onClick={() => change({ category_id: null })}
                className="text-[13px] font-semibold text-primary"
              >
                Automatic
              </button>
            ) : null
          }
        />
      )}

      {counterparty && (
        <Link
          to="/finance/spending/merchant/$id"
          params={{ id: counterparty.id }}
          className="mt-3 block rounded-xl py-2.5 text-center font-[650] text-primary hover:bg-surface"
        >
          All from {counterparty.name}
        </Link>
      )}

      <div className="mt-6 space-y-5">
        <Field
          label="What it is"
          hint={
            transaction.kind_source
              ? SOURCE_LABELS[transaction.kind_source]
              : category
                ? 'from the category'
                : 'from the amount'
          }
        >
          <Select
            value={transaction.kind_source === 'manual' ? transaction.kind : AUTOMATIC}
            onValueChange={(value) =>
              change({ kind: value === AUTOMATIC ? null : (value as TransactionKind) })
            }
            disabled={update.isPending}
          >
            <SelectTrigger className="w-full" aria-label="What it is">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={AUTOMATIC}>
                Automatic ({KINDS.find((kind) => kind.value === transaction.kind)?.label})
              </SelectItem>
              {KINDS.map((kind) => (
                <SelectItem key={kind.value} value={kind.value}>
                  {kind.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </Field>

        <Field
          label="Merchant"
          hint={counterparty?.source ? SOURCE_LABELS[counterparty.source] : undefined}
        >
          <MerchantPicker
            value={counterparty?.source === 'manual' ? counterparty.id : null}
            automatic="Automatic (bank name or rules)"
            creatable
            disabled={update.isPending}
            className="w-full max-w-none"
            onChange={(counterpartyId) => change({ counterparty_id: counterpartyId })}
          >
            {counterparty?.name ?? 'None'}
          </MerchantPicker>
        </Field>

        <NoteField
          key={`note-${transaction.id}`}
          initial={transaction.note ?? ''}
          disabled={update.isPending}
          onSave={(note) => change({ note: note || null })}
        />

        <TagsField
          key={`tags-${transaction.id}`}
          initial={transaction.tags}
          ruleTags={transaction.rule_tags}
          disabled={update.isPending}
          onSave={(tags) => change({ tags })}
        />

        <section aria-label="From the bank">
          <h3 className="mb-1.5 text-[13px] font-[650] text-muted-foreground">From the bank</h3>
          <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 rounded-2xl bg-surface px-3.5 py-3 text-xs">
            <Row term="Description" detail={transaction.description} />
            <Row term="Name" detail={transaction.counterparty_name} />
            <Row term="Type" detail={transaction.bank_code} />
            <Row term="Reference" detail={transaction.reference} />
            <Row
              term="Booked"
              detail={transaction.booking_date ? formatDate(transaction.booking_date) : null}
            />
            <Row
              term="Value date"
              detail={transaction.value_date ? formatDate(transaction.value_date) : null}
            />
          </dl>
        </section>
      </div>
    </div>
  );
}

function Fact({ term, children }: { term: string; children: ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-3 border-b py-[11px] last:border-0">
      <dt className="text-muted-foreground">{term}</dt>
      <dd className="text-right">{children}</dd>
    </div>
  );
}

/** Every active category of the right kind, by group: one click sets it. */
function CategoryGrid({
  current,
  income,
  disabled,
  onPick,
  action,
}: {
  current: string | null;
  income: boolean;
  disabled: boolean;
  onPick: (id: string) => void;
  action: ReactNode;
}) {
  const styleOf = useCategoryStyles();
  const groups = activeGroups(useCategories().data).filter(
    (group) => (group.kind === 'income') === income && group.children.length > 0,
  );
  return (
    <section aria-label="Category" className="mt-5">
      <div className="mb-2 flex items-center">
        <h3 className="text-base font-bold">Category</h3>
        <div className="ml-auto">{action}</div>
      </div>
      {groups.map((group) => (
        <div key={group.id} className="mt-3">
          <p className="mb-1.5 text-[11.5px] font-semibold text-faint">{group.name}</p>
          <div className="grid grid-cols-2 gap-1.5">
            {group.children.map((child) => (
              <button
                key={child.id}
                type="button"
                aria-pressed={child.id === current}
                disabled={disabled}
                onClick={() => onPick(child.id)}
                className={cn(
                  'flex min-w-0 items-center gap-2 rounded-xl bg-surface p-2 text-left text-[13.5px] font-medium transition-colors hover:bg-surface-2 disabled:opacity-60',
                  child.id === current && 'shadow-[inset_0_0_0_2px_var(--primary)]',
                )}
              >
                <Chip style={styleOf(child.id)} size="sm" className="size-7 [&>svg]:size-3.5" />
                <span className="truncate">{child.name}</span>
              </button>
            ))}
          </div>
        </div>
      ))}
    </section>
  );
}

function Field({ label, hint, children }: { label: string; hint?: string; children: ReactNode }) {
  return (
    <div className="space-y-1.5">
      <div className="flex items-baseline justify-between">
        <span className="text-[13px] font-[650] text-muted-foreground">{label}</span>
        {hint && <span className="text-xs text-faint">{hint}</span>}
      </div>
      {children}
    </div>
  );
}

function Row({ term, detail }: { term: string; detail: string | null }) {
  if (!detail) return null;
  return (
    <>
      <dt className="text-muted-foreground">{term}</dt>
      <dd className="break-words">{detail}</dd>
    </>
  );
}

function NoteField({
  initial,
  disabled,
  onSave,
}: {
  initial: string;
  disabled: boolean;
  onSave: (note: string) => void;
}) {
  const [note, setNote] = useState(initial);
  useEffect(() => setNote(initial), [initial]);
  const changed = note.trim() !== initial;
  return (
    <Field label="Note">
      <Textarea
        aria-label="Note"
        value={note}
        rows={2}
        onChange={(event) => setNote(event.target.value)}
      />
      {changed && (
        <Button size="sm" disabled={disabled} onClick={() => onSave(note.trim())}>
          Save note
        </Button>
      )}
    </Field>
  );
}

function TagsField({
  initial,
  ruleTags,
  disabled,
  onSave,
}: {
  initial: string[];
  ruleTags: string[];
  disabled: boolean;
  onSave: (tags: string[]) => void;
}) {
  const [text, setText] = useState(initial.join(', '));
  useEffect(() => setText(initial.join(', ')), [initial]);
  const tags = text
    .split(',')
    .map((tag) => tag.trim())
    .filter(Boolean);
  const changed = tags.join(',') !== initial.join(',');
  return (
    <Field label="Tags" hint="separate with commas">
      <Input
        aria-label="Tags"
        value={text}
        onChange={(event) => setText(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === 'Enter' && changed) onSave(tags);
        }}
      />
      {ruleTags.length > 0 && (
        <div className="flex flex-wrap items-center gap-1">
          <span className="text-xs text-muted-foreground">From rules:</span>
          {ruleTags.map((tag) => (
            <Badge key={tag} variant="secondary">
              {tag}
            </Badge>
          ))}
        </div>
      )}
      {changed && (
        <Button size="sm" disabled={disabled} onClick={() => onSave(tags)}>
          Save tags
        </Button>
      )}
    </Field>
  );
}
