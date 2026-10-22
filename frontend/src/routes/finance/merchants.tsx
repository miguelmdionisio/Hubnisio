import { useMutation, useQueryClient } from '@tanstack/react-query';
import { Link } from '@tanstack/react-router';
import { Merge, Pencil } from 'lucide-react';
import { type FormEvent, useState } from 'react';
import { toast } from 'sonner';
import {
  mergeCounterpartyMutation,
  updateCounterpartyMutation,
} from '@/api/@tanstack/react-query.gen';
import type { CounterpartyOut } from '@/api/types.gen';
import { PageHeader } from '@/components/app-shell';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Card, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
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
import { errorMessage } from '@/lib/errors';
import { CategoryPicker, categoryNames, useCategories } from './category-picker';
import { MerchantPicker, useMerchants } from './merchant-picker';
import { invalidateUserLayer } from './use-transaction-edits';

const SHOWN_ALIASES = 3;

type Editing =
  | { type: 'rename'; merchant: CounterpartyOut }
  | { type: 'merge'; merchant: CounterpartyOut };

export function MerchantsPage() {
  const queryClient = useQueryClient();
  const merchants = useMerchants();
  const names = categoryNames(useCategories().data);
  const [search, setSearch] = useState('');
  const [editing, setEditing] = useState<Editing | null>(null);
  const done = () => {
    invalidateUserLayer(queryClient);
    setEditing(null);
  };
  const onError = (error: unknown) => toast.error(errorMessage(error));
  const update = useMutation({ ...updateCounterpartyMutation(), onSuccess: done, onError });
  const merge = useMutation({
    ...mergeCounterpartyMutation(),
    onSuccess: (target) => {
      done();
      toast.success(`Merged into ${target.name}.`);
    },
    onError,
  });

  const needle = search.trim().toLowerCase();
  const shown = merchants.data?.filter(
    (merchant) =>
      !needle ||
      merchant.name.toLowerCase().includes(needle) ||
      merchant.aliases.some((alias) => alias.includes(needle)),
  );

  return (
    <>
      <PageHeader
        title="Merchants"
        description="Who the money went to or came from. A merchant's default category covers all its transactions, past and future, unless a rule or a choice of yours says otherwise."
      />
      <Input
        type="search"
        aria-label="Search merchants"
        placeholder="Search merchants"
        className="mb-4 max-w-sm"
        value={search}
        onChange={(event) => setSearch(event.target.value)}
      />
      {merchants.isPending && <Skeleton className="h-64 w-full" />}
      {merchants.isError && (
        <Alert variant="destructive">
          <AlertTitle>Couldn't load merchants</AlertTitle>
          <AlertDescription>{errorMessage(merchants.error)}</AlertDescription>
        </Alert>
      )}
      {merchants.data?.length === 0 && (
        <Card className="max-w-xl">
          <CardHeader>
            <CardTitle>No merchants yet</CardTitle>
            <CardDescription>
              Merchants appear when the bank names who a transaction was with, or when you name one
              on a transaction.
            </CardDescription>
          </CardHeader>
        </Card>
      )}
      {shown && shown.length > 0 && (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Merchant</TableHead>
              <TableHead>Default category</TableHead>
              <TableHead className="text-right">Transactions</TableHead>
              <TableHead className="w-24" />
            </TableRow>
          </TableHeader>
          <TableBody>
            {shown.map((merchant) => (
              <TableRow key={merchant.id}>
                <TableCell>
                  <div className="font-medium">{merchant.name}</div>
                  {merchant.aliases.length > 0 && (
                    <div className="max-w-md truncate text-xs text-muted-foreground">
                      Bank names: {merchant.aliases.slice(0, SHOWN_ALIASES).join(', ')}
                      {merchant.aliases.length > SHOWN_ALIASES &&
                        ` +${merchant.aliases.length - SHOWN_ALIASES}`}
                    </div>
                  )}
                </TableCell>
                <TableCell>
                  <CategoryPicker
                    value={merchant.default_category_id}
                    noneLabel="No default"
                    disabled={update.isPending}
                    onChange={(categoryId) =>
                      update.mutate({
                        path: { counterparty_id: merchant.id },
                        body: { default_category_id: categoryId },
                      })
                    }
                  >
                    {merchant.default_category_id ? (
                      (names.get(merchant.default_category_id) ?? 'Unknown')
                    ) : (
                      <span className="text-muted-foreground">No default</span>
                    )}
                  </CategoryPicker>
                </TableCell>
                <TableCell className="text-right tabular-nums">
                  <Link
                    to="/finance/transactions"
                    search={{ counterparty: merchant.id }}
                    className="underline-offset-4 hover:underline"
                    aria-label={`${merchant.transactions} transactions with ${merchant.name}`}
                  >
                    {merchant.transactions}
                  </Link>
                </TableCell>
                <TableCell className="text-right">
                  <Button
                    variant="ghost"
                    size="icon-sm"
                    aria-label={`Rename ${merchant.name}`}
                    title={`Rename ${merchant.name}`}
                    onClick={() => setEditing({ type: 'rename', merchant })}
                  >
                    <Pencil aria-hidden />
                  </Button>
                  <Button
                    variant="ghost"
                    size="icon-sm"
                    aria-label={`Merge ${merchant.name}`}
                    title={`Merge ${merchant.name} into another`}
                    onClick={() => setEditing({ type: 'merge', merchant })}
                  >
                    <Merge aria-hidden />
                  </Button>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
      {shown?.length === 0 && !!merchants.data?.length && (
        <p className="text-sm text-muted-foreground">No merchant matches “{search.trim()}”.</p>
      )}

      {editing?.type === 'rename' && (
        <RenameDialog
          merchant={editing.merchant}
          pending={update.isPending}
          onClose={() => setEditing(null)}
          onRename={(name) =>
            update.mutate({ path: { counterparty_id: editing.merchant.id }, body: { name } })
          }
        />
      )}
      {editing?.type === 'merge' && (
        <MergeDialog
          merchant={editing.merchant}
          others={merchants.data ?? []}
          pending={merge.isPending}
          onClose={() => setEditing(null)}
          onMerge={(intoId) =>
            merge.mutate({
              path: { counterparty_id: editing.merchant.id },
              body: { into_id: intoId },
            })
          }
        />
      )}
    </>
  );
}

function RenameDialog({
  merchant,
  pending,
  onClose,
  onRename,
}: {
  merchant: CounterpartyOut;
  pending: boolean;
  onClose: () => void;
  onRename: (name: string) => void;
}) {
  const [name, setName] = useState(merchant.name);
  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (name.trim()) onRename(name.trim());
  };
  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="sm:max-w-sm">
        <form onSubmit={submit} className="space-y-4">
          <DialogHeader>
            <DialogTitle>Rename {merchant.name}</DialogTitle>
            <DialogDescription>
              The bank's own spelling stays on the transaction; this is the name you see.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-2">
            <Label htmlFor="merchant-name">Name</Label>
            <Input
              id="merchant-name"
              value={name}
              maxLength={120}
              autoFocus
              onChange={(event) => setName(event.target.value)}
            />
          </div>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={onClose}>
              Cancel
            </Button>
            <Button type="submit" disabled={pending || !name.trim()}>
              Rename
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function MergeDialog({
  merchant,
  others,
  pending,
  onClose,
  onMerge,
}: {
  merchant: CounterpartyOut;
  others: CounterpartyOut[];
  pending: boolean;
  onClose: () => void;
  onMerge: (intoId: string) => void;
}) {
  const [intoId, setIntoId] = useState<string | null>(null);
  const target = others.find((other) => other.id === intoId);
  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Merge {merchant.name}</DialogTitle>
          <DialogDescription>
            Its {merchant.transactions} transactions, bank spellings and rules move to the merchant
            you pick, and {merchant.name} goes away. This can't be undone.
          </DialogDescription>
        </DialogHeader>
        <MerchantPicker exclude={merchant.id} onChange={setIntoId} className="w-full">
          {target?.name ?? 'Merge into…'}
        </MerchantPicker>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>
            Cancel
          </Button>
          <Button disabled={pending || !target} onClick={() => intoId && onMerge(intoId)}>
            {target ? `Merge into ${target.name}` : 'Merge'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
