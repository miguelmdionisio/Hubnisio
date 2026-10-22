import { useQuery } from '@tanstack/react-query';
import { ArrowLeftRight, Check, ChevronsUpDown } from 'lucide-react';
import { type ReactNode, useEffect, useState } from 'react';
import { listCounterpartiesOptions } from '@/api/@tanstack/react-query.gen';
import type { TransactionKind, TransactionOut } from '@/api/types.gen';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from '@/components/ui/command';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from '@/components/ui/sheet';
import { Textarea } from '@/components/ui/textarea';
import { formatDate, formatMoney } from '@/lib/format';
import { cn } from '@/lib/utils';
import { CategoryPicker } from './category-picker';
import { SOURCE_LABELS, useUnlinkTransfer, useUpdateTransaction } from './use-transaction-edits';

const AUTOMATIC = 'automatic'; // Select items can't have an empty value
const KINDS: { value: TransactionKind; label: string }[] = [
  { value: 'expense', label: 'Spending' },
  { value: 'income', label: 'Income' },
  { value: 'transfer', label: 'Transfer between own accounts' },
];

export function transactionTitle(transaction: TransactionOut): string {
  return (
    transaction.counterparty?.name ??
    transaction.counterparty_name ??
    transaction.description ??
    '—'
  );
}

export function TransactionSheet({
  transaction,
  accountName,
  onOpenChange,
}: {
  transaction: TransactionOut | undefined;
  accountName: string;
  onOpenChange: (open: boolean) => void;
}) {
  return (
    <Sheet open={transaction !== undefined} onOpenChange={onOpenChange}>
      <SheetContent className="w-full overflow-y-auto sm:max-w-md">
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
  const change = (body: Parameters<typeof update.mutate>[0]['body']) =>
    update.mutate({ path: { transaction_id: transaction.id }, body });
  const { category, counterparty, transfer } = transaction;

  return (
    <>
      <SheetHeader>
        <SheetTitle>{transactionTitle(transaction)}</SheetTitle>
        <SheetDescription>
          {formatMoney(transaction.amount, transaction.currency)} ·{' '}
          {formatDate(transaction.occurred_on)} · {accountName}
          {transaction.status === 'pending' && ' · pending'}
        </SheetDescription>
      </SheetHeader>

      <div className="space-y-5 px-4 pb-6 text-sm">
        <Field label="Category" hint={category ? SOURCE_LABELS[category.source] : undefined}>
          {transaction.kind === 'transfer' && !category ? (
            <p className="text-muted-foreground">Transfers have no category.</p>
          ) : (
            <CategoryPicker
              value={category?.source === 'manual' ? category.id : null}
              onChange={(categoryId) => change({ category_id: categoryId })}
              disabled={update.isPending}
              className="w-full max-w-none border"
            >
              {category ? category.name : 'Uncategorized'}
            </CategoryPicker>
          )}
        </Field>

        <Field
          label="What it is"
          hint={
            transaction.kind_source ? SOURCE_LABELS[transaction.kind_source] : 'from the amount'
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

        {transfer && (
          <Field label="Transfer" hint={SOURCE_LABELS[transfer.source]}>
            <div className="flex items-center justify-between gap-2">
              <span className="flex items-center gap-2">
                <ArrowLeftRight className="size-4 text-muted-foreground" aria-hidden />
                {Number(transaction.amount) < 0 ? 'To' : 'From'} {transfer.other_account_name}
              </span>
              <Button
                variant="outline"
                size="sm"
                disabled={unlink.isPending}
                onClick={() => unlink.mutate({ path: { transfer_id: transfer.id } })}
              >
                Unlink
              </Button>
            </div>
          </Field>
        )}

        <Field
          label="Merchant"
          hint={counterparty?.source ? SOURCE_LABELS[counterparty.source] : undefined}
        >
          <MerchantPicker
            value={counterparty?.source === 'manual' ? counterparty.id : null}
            label={counterparty?.name ?? 'None'}
            disabled={update.isPending}
            onChange={(counterpartyId) => change({ counterparty_id: counterpartyId })}
          />
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

        <div className="space-y-1 border-t pt-4">
          <p className="text-xs font-medium tracking-wide text-muted-foreground uppercase">
            From the bank
          </p>
          <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-xs">
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
            {transaction.original_amount && transaction.original_currency && (
              <Row
                term="Original"
                detail={formatMoney(transaction.original_amount, transaction.original_currency)}
              />
            )}
          </dl>
        </div>
      </div>
    </>
  );
}

function Field({ label, hint, children }: { label: string; hint?: string; children: ReactNode }) {
  return (
    <div className="space-y-1.5">
      <div className="flex items-baseline justify-between">
        <Label>{label}</Label>
        {hint && <span className="text-xs text-muted-foreground">{hint}</span>}
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

function MerchantPicker({
  value,
  label,
  disabled,
  onChange,
}: {
  value: string | null;
  label: string;
  disabled: boolean;
  onChange: (counterpartyId: string | null) => void;
}) {
  const [open, setOpen] = useState(false);
  const merchants = useQuery({
    ...listCounterpartiesOptions(),
    enabled: open,
    staleTime: 60_000,
  });
  const choose = (counterpartyId: string | null) => {
    setOpen(false);
    if (counterpartyId !== value) onChange(counterpartyId);
  };
  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button
          variant="outline"
          size="sm"
          disabled={disabled}
          className="w-full justify-between font-normal"
        >
          <span className="truncate">{label}</span>
          <ChevronsUpDown className="size-3 opacity-50" aria-hidden />
        </Button>
      </PopoverTrigger>
      <PopoverContent className="w-72 p-0" align="start">
        <Command>
          <CommandInput placeholder="Search merchants" />
          <CommandList>
            <CommandEmpty>No merchant matches.</CommandEmpty>
            <CommandGroup>
              <CommandItem value="automatic" onSelect={() => choose(null)}>
                <span className="text-muted-foreground">Automatic (bank name or rules)</span>
              </CommandItem>
              {merchants.data?.map((merchant) => (
                <CommandItem
                  key={merchant.id}
                  value={`${merchant.name} ${merchant.id}`}
                  onSelect={() => choose(merchant.id)}
                >
                  <Check
                    className={cn('size-3', value === merchant.id ? 'opacity-100' : 'opacity-0')}
                    aria-hidden
                  />
                  {merchant.name}
                </CommandItem>
              ))}
            </CommandGroup>
          </CommandList>
        </Command>
      </PopoverContent>
    </Popover>
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
