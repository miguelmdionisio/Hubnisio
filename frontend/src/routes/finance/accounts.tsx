import { useMutation, useQueryClient } from '@tanstack/react-query';
import { Link } from '@tanstack/react-router';
import { ChartLine, ChevronDown, ChevronRight, EyeOff, Landmark, Pencil } from 'lucide-react';
import { useEffect, useState } from 'react';
import { toast } from 'sonner';
import { deleteAccountMutation, updateAccountMutation } from '@/api/@tanstack/react-query.gen';
import { deleteAccount } from '@/api/sdk.gen';
import type { AccountDeleteBlocked, AccountOut, AccountUpdate } from '@/api/types.gen';
import { PageHeader } from '@/components/app-shell';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardDescription, CardFooter, CardHeader, CardTitle } from '@/components/ui/card';
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
import { Switch } from '@/components/ui/switch';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { errorMessage } from '@/lib/errors';
import { formatMoney, formatRelative } from '@/lib/format';
import { CategoryPicker, categoryNames, useCategories } from './category-picker';
import { NetWorth } from './net-worth';
import { ListPanel } from './transaction-rows';
import { useAccounts } from './use-accounts';

const POT_NOTE =
  'An account shared with someone outside the hub. In Mine, what you move into it counts as spending in its category; its own spending and balance count only in Household.';

const BALANCE_LABELS: Record<string, string> = {
  ITAV: 'available',
  CLAV: 'available',
  ITBD: 'booked',
  CLBD: 'booked',
  TVAL: 'value', // a broker's: cash plus holdings at market value
};

export function AccountsPage() {
  const queryClient = useQueryClient();
  const accounts = useAccounts();
  const names = categoryNames(useCategories().data);
  const update = useMutation({
    ...updateAccountMutation(),
    // An account's settings show everywhere: net worth, upcoming payments, filters.
    onSuccess: () => queryClient.invalidateQueries(),
  });
  const [renaming, setRenaming] = useState<AccountOut | null>(null);
  const [hiding, setHiding] = useState<AccountOut | null>(null);
  const [deleting, setDeleting] = useState<AccountOut | null>(null);

  const change = (account: AccountOut, body: AccountUpdate) =>
    update.mutate({ path: { account_id: account.id }, body });

  return (
    <>
      <PageHeader
        title="Accounts"
        showsView
        actions={
          <Button variant="outline" asChild>
            <Link to="/finance/connections">Bank connections</Link>
          </Button>
        }
      />
      <NetWorth />
      {accounts.isPending && <Skeleton className="h-48 w-full" />}
      {accounts.isError && (
        <Alert variant="destructive">
          <AlertTitle>Couldn't load accounts</AlertTitle>
          <AlertDescription>{errorMessage(accounts.error)}</AlertDescription>
        </Alert>
      )}
      {update.isError && (
        <Alert variant="destructive" className="mb-4">
          <AlertTitle>Couldn't save the change</AlertTitle>
          <AlertDescription>{errorMessage(update.error)}</AlertDescription>
        </Alert>
      )}
      {accounts.data?.length === 0 && (
        <Card className="max-w-xl">
          <CardHeader>
            <CardTitle>No accounts yet</CardTitle>
            <CardDescription>Accounts appear here once you link a bank.</CardDescription>
          </CardHeader>
          <CardFooter>
            <Button asChild>
              <Link to="/finance/connections">Link a bank</Link>
            </Button>
          </CardFooter>
        </Card>
      )}
      {accounts.listed.length > 0 && (
        <ListPanel>
          <ul>
            {accounts.listed.map((account) => (
              <li key={account.id} className="rounded-[14px] px-3 py-3 hover:bg-surface-2/60">
                <div className="grid grid-cols-[40px_minmax(0,1fr)_auto] items-center gap-3.5">
                  <span
                    aria-hidden
                    className="grid size-10 place-items-center rounded-full bg-surface-2 text-muted-foreground"
                  >
                    {account.is_investment ? (
                      <ChartLine className="size-[18px]" />
                    ) : (
                      <Landmark className="size-[18px]" />
                    )}
                  </span>
                  <div className="min-w-0">
                    <div className="flex items-center gap-1">
                      <span className="truncate text-[15px] font-semibold">{account.name}</span>
                      {account.is_owner && (
                        <Button
                          variant="ghost"
                          size="icon-xs"
                          aria-label={`Rename ${account.name}`}
                          onClick={() => setRenaming(account)}
                        >
                          <Pencil />
                        </Button>
                      )}
                    </div>
                    <p className="truncate text-[13px] text-muted-foreground">
                      {account.institution_name}
                      {account.is_investment && ' · investments'}
                      {account.iban_masked && (
                        <span className="font-mono"> · {account.iban_masked}</span>
                      )}
                    </p>
                  </div>
                  <div className="text-right">
                    {account.balance ? (
                      <>
                        <p className="text-[15px] font-[650] tabular-nums">
                          {formatMoney(account.balance.amount, account.balance.currency)}
                        </p>
                        <p className="text-[13px] text-muted-foreground">
                          {BALANCE_LABELS[account.balance.balance_type] ??
                            account.balance.balance_type}
                          {' · '}
                          {formatRelative(account.balance.fetched_at)}
                        </p>
                      </>
                    ) : (
                      <span className="text-[13px] text-muted-foreground">Not synced</span>
                    )}
                  </div>
                </div>
                <div className="mt-2.5 flex flex-wrap items-center gap-x-5 gap-y-2 pl-[54px] text-[13px] text-muted-foreground">
                  <Toggle
                    label="Private"
                    aria-label={`${account.name} is private`}
                    checked={account.visibility === 'private'}
                    disabled={!account.is_owner || update.isPending}
                    onChange={(checked) =>
                      change(account, { visibility: checked ? 'private' : 'shared' })
                    }
                  />
                  <Toggle
                    label="In net worth"
                    aria-label={`Count ${account.name} in net worth`}
                    checked={account.include_in_net_worth}
                    disabled={!account.is_owner || update.isPending}
                    onChange={(checked) => change(account, { include_in_net_worth: checked })}
                  />
                  <Toggle
                    label="Shared pot"
                    title={POT_NOTE}
                    aria-label={`${account.name} is a shared pot`}
                    checked={account.is_pot}
                    disabled={!account.is_owner || update.isPending}
                    onChange={(checked) => change(account, { is_pot: checked })}
                  />
                  {account.is_pot && (
                    <span className="flex items-center gap-1">
                      <Badge variant="outline">Not in Mine</Badge>
                      <CategoryPicker
                        kind="expense"
                        noneLabel="Uncategorized"
                        value={account.pot_category_id}
                        disabled={!account.is_owner || update.isPending}
                        onChange={(categoryId) => change(account, { pot_category_id: categoryId })}
                        className="h-7 text-xs"
                      >
                        {account.pot_category_id
                          ? (names.get(account.pot_category_id) ?? 'Unknown category')
                          : 'Uncategorized'}
                      </CategoryPicker>
                    </span>
                  )}
                  {account.is_owner && (
                    <Button
                      variant="ghost"
                      size="xs"
                      className="ml-auto"
                      aria-label={`Hide ${account.name}`}
                      onClick={() => setHiding(account)}
                    >
                      <EyeOff />
                      Hide
                    </Button>
                  )}
                </div>
              </li>
            ))}
          </ul>
          <Totals accounts={accounts.listed} />
        </ListPanel>
      )}
      <HiddenAccounts
        accounts={accounts.hidden}
        disabled={update.isPending}
        onUnhide={(account) => change(account, { hidden: false })}
        onDelete={setDeleting}
      />
      <RenameDialog
        account={renaming}
        onClose={() => setRenaming(null)}
        onSave={(account, name) => {
          change(account, { display_name: name });
          setRenaming(null);
        }}
      />
      <HideDialog
        account={hiding}
        onClose={() => setHiding(null)}
        onHide={(account) => {
          change(account, { hidden: true });
          setHiding(null);
        }}
      />
      <DeleteDialog key={deleting?.id} account={deleting} onClose={() => setDeleting(null)} />
    </>
  );
}

/** One total per currency, over the accounts counted in net worth. */
function Totals({ accounts }: { accounts: AccountOut[] }) {
  const totals = new Map<string, number>();
  for (const account of accounts) {
    if (!account.include_in_net_worth || !account.balance) continue;
    const { currency, amount } = account.balance;
    totals.set(currency, (totals.get(currency) ?? 0) + Number(amount));
  }
  if (totals.size === 0) return null;
  return (
    <p className="flex justify-between gap-3 px-3 pt-2 pb-2.5 text-[15px] font-semibold">
      <span>Total</span>
      <span className="text-right tabular-nums">
        {[...totals].map(([currency, amount]) => (
          <span key={currency} className="block">
            {formatMoney(amount, currency)}
          </span>
        ))}
      </span>
    </p>
  );
}

/** Retired accounts, collapsed: owners can bring one back or delete it for good. */
function HiddenAccounts({
  accounts,
  disabled,
  onUnhide,
  onDelete,
}: {
  accounts: AccountOut[];
  disabled: boolean;
  onUnhide: (account: AccountOut) => void;
  onDelete: (account: AccountOut) => void;
}) {
  const [open, setOpen] = useState(false);
  if (accounts.length === 0) return null;
  return (
    <section className="mt-8 space-y-2">
      <Button variant="ghost" aria-expanded={open} onClick={() => setOpen(!open)}>
        {open ? <ChevronDown /> : <ChevronRight />}
        Hidden accounts ({accounts.length})
      </Button>
      {open && (
        <>
          <p className="text-sm text-muted-foreground">
            Left out of account lists, net worth and the sync. Their past transactions still count
            in spending and budgets.
          </p>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Account</TableHead>
                <TableHead className="text-right">Transactions</TableHead>
                <TableHead>Hidden</TableHead>
                <TableHead>
                  <span className="sr-only">Actions</span>
                </TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {accounts.map((account) => (
                <TableRow key={account.id}>
                  <TableCell>
                    <div className="font-medium">{account.name}</div>
                    <div className="text-xs text-muted-foreground">{account.institution_name}</div>
                  </TableCell>
                  <TableCell className="text-right tabular-nums">
                    {account.transaction_count}
                  </TableCell>
                  <TableCell className="text-muted-foreground">
                    {account.hidden_at && formatRelative(account.hidden_at)}
                  </TableCell>
                  <TableCell>
                    {account.is_owner && (
                      <div className="flex justify-end gap-2">
                        <Button
                          variant="outline"
                          size="sm"
                          aria-label={`Unhide ${account.name}`}
                          disabled={disabled}
                          onClick={() => onUnhide(account)}
                        >
                          Unhide
                        </Button>
                        <Button
                          variant="outline"
                          size="sm"
                          className="text-destructive"
                          aria-label={`Delete ${account.name}`}
                          onClick={() => onDelete(account)}
                        >
                          Delete
                        </Button>
                      </div>
                    )}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </>
      )}
    </section>
  );
}

function RenameDialog({
  account,
  onClose,
  onSave,
}: {
  account: AccountOut | null;
  onClose: () => void;
  onSave: (account: AccountOut, name: string) => void;
}) {
  return (
    <Dialog open={account !== null} onOpenChange={(open) => !open && onClose()}>
      <DialogContent>
        {account && (
          <form
            className="space-y-4"
            onSubmit={(event) => {
              event.preventDefault();
              const name = new FormData(event.currentTarget).get('name');
              onSave(account, typeof name === 'string' ? name : '');
            }}
          >
            <DialogHeader>
              <DialogTitle>Rename account</DialogTitle>
            </DialogHeader>
            <div className="space-y-2">
              <Label htmlFor="account-name">Name</Label>
              <Input id="account-name" name="name" defaultValue={account.name} maxLength={100} />
              <p className="text-xs text-muted-foreground">Leave empty to use the bank's name.</p>
            </div>
            <DialogFooter>
              <Button type="button" variant="outline" onClick={onClose}>
                Cancel
              </Button>
              <Button type="submit">Save</Button>
            </DialogFooter>
          </form>
        )}
      </DialogContent>
    </Dialog>
  );
}

function HideDialog({
  account,
  onClose,
  onHide,
}: {
  account: AccountOut | null;
  onClose: () => void;
  onHide: (account: AccountOut) => void;
}) {
  return (
    <Dialog open={account !== null} onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Hide {account?.name}?</DialogTitle>
          <DialogDescription>
            It leaves account lists, net worth and the sync, for everyone in the household. Its past
            transactions still count in spending and budgets. You can unhide it later.
          </DialogDescription>
        </DialogHeader>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>
            Cancel
          </Button>
          <Button onClick={() => account && onHide(account)}>Hide account</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

/**
 * Deleting takes the account's history with it. With transactions, the dialog states what
 * goes (the API answers a delete without confirmation with the counts) and asks for the
 * account's name.
 */
function DeleteDialog({ account, onClose }: { account: AccountOut | null; onClose: () => void }) {
  const queryClient = useQueryClient();
  const [typed, setTyped] = useState('');
  const [blocked, setBlocked] = useState<AccountDeleteBlocked | null>(null);
  const remove = useMutation({
    ...deleteAccountMutation(),
    onSuccess: () => {
      queryClient.invalidateQueries();
      toast.success(`Deleted ${account?.name}.`);
      onClose();
    },
  });
  const count = account?.transaction_count ?? 0;

  useEffect(() => {
    if (!account || account.transaction_count === 0) return;
    let current = true;
    deleteAccount({ path: { account_id: account.id } }).then(({ error }) => {
      if (current && error && 'transfer_count' in error) setBlocked(error);
    });
    return () => {
      current = false;
    };
  }, [account]);

  const ready = count === 0 || typed.trim() === account?.name;
  return (
    <Dialog open={account !== null} onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="sm:max-w-md">
        {account && (
          <form
            className="space-y-4"
            onSubmit={(event) => {
              event.preventDefault();
              if (ready)
                remove.mutate({ path: { account_id: account.id }, query: { confirm: true } });
            }}
          >
            <DialogHeader>
              <DialogTitle>Delete {account.name}?</DialogTitle>
              <DialogDescription>
                {count === 0
                  ? 'It has no transactions.'
                  : `Its ${count} ${count === 1 ? 'transaction goes' : 'transactions go'} with it, with their categories, notes and tags.`}
              </DialogDescription>
            </DialogHeader>
            {count > 0 && <TransfersLine blocked={blocked} />}
            <p className="text-sm text-muted-foreground">
              If the bank still offers this account, linking the bank again brings it back. To keep
              it out for good, leave it hidden instead.
            </p>
            {count > 0 && (
              <div className="space-y-2">
                <Label htmlFor="delete-account-name">Type “{account.name}” to confirm</Label>
                <Input
                  id="delete-account-name"
                  autoComplete="off"
                  value={typed}
                  onChange={(event) => setTyped(event.target.value)}
                />
              </div>
            )}
            {remove.isError && (
              <Alert variant="destructive">
                <AlertDescription>{errorMessage(remove.error)}</AlertDescription>
              </Alert>
            )}
            <DialogFooter>
              <Button type="button" variant="outline" onClick={onClose}>
                Cancel
              </Button>
              <Button type="submit" variant="destructive" disabled={!ready || remove.isPending}>
                Delete account
              </Button>
            </DialogFooter>
          </form>
        )}
      </DialogContent>
    </Dialog>
  );
}

function TransfersLine({ blocked }: { blocked: AccountDeleteBlocked | null }) {
  if (blocked === null) {
    return <p className="text-sm text-muted-foreground">Counting its transfers…</p>;
  }
  const transfers = blocked.transfer_count;
  if (transfers === 0) return null;
  return (
    <p className="text-sm">
      {transfers === 1
        ? '1 transfer with your other accounts stays marked as a transfer on their side'
        : `${transfers} transfers with your other accounts stay marked as transfers on their side`}
      , so spending and income don't change.
    </p>
  );
}

/** A labelled switch in an account's settings line. */
function Toggle({
  label,
  title,
  checked,
  disabled,
  onChange,
  'aria-label': ariaLabel,
}: {
  label: string;
  title?: string;
  checked: boolean;
  disabled: boolean;
  onChange: (checked: boolean) => void;
  'aria-label': string;
}) {
  return (
    <span className="flex items-center gap-2" title={title}>
      <Switch
        aria-label={ariaLabel}
        checked={checked}
        disabled={disabled}
        onCheckedChange={onChange}
      />
      {label}
    </span>
  );
}
