import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Link } from '@tanstack/react-router';
import { Pencil } from 'lucide-react';
import { useState } from 'react';
import {
  listAccountsOptions,
  listAccountsQueryKey,
  updateAccountMutation,
} from '@/api/@tanstack/react-query.gen';
import type { AccountOut, AccountUpdate } from '@/api/types.gen';
import { PageHeader } from '@/components/app-shell';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Card, CardDescription, CardFooter, CardHeader, CardTitle } from '@/components/ui/card';
import {
  Dialog,
  DialogContent,
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
  TableFooter,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { errorMessage } from '@/lib/errors';
import { formatMoney, formatRelative } from '@/lib/format';

const BALANCE_LABELS: Record<string, string> = {
  ITAV: 'available',
  CLAV: 'available',
  ITBD: 'booked',
  CLBD: 'booked',
};

export function AccountsPage() {
  const queryClient = useQueryClient();
  const accounts = useQuery(listAccountsOptions());
  const update = useMutation({
    ...updateAccountMutation(),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: listAccountsQueryKey() }),
  });
  const [renaming, setRenaming] = useState<AccountOut | null>(null);

  const change = (account: AccountOut, body: AccountUpdate) =>
    update.mutate({ path: { account_id: account.id }, body });

  return (
    <>
      <PageHeader
        title="Accounts"
        description="Balances as the banks report them at each sync."
        actions={
          <Button variant="outline" asChild>
            <Link to="/finance/connections">Bank connections</Link>
          </Button>
        }
      />
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
      {accounts.data && accounts.data.length > 0 && (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Account</TableHead>
              <TableHead>IBAN</TableHead>
              <TableHead className="text-right">Balance</TableHead>
              <TableHead>Private</TableHead>
              <TableHead>In net worth</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {accounts.data.map((account) => (
              <TableRow key={account.id}>
                <TableCell>
                  <div className="flex items-center gap-1">
                    <span className="font-medium">{account.name}</span>
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
                  <div className="text-xs text-muted-foreground">{account.institution_name}</div>
                </TableCell>
                <TableCell className="font-mono text-xs">{account.iban_masked ?? '—'}</TableCell>
                <TableCell className="text-right">
                  {account.balance ? (
                    <>
                      <div className="font-medium tabular-nums">
                        {formatMoney(account.balance.amount, account.balance.currency)}
                      </div>
                      <div className="text-xs text-muted-foreground">
                        {BALANCE_LABELS[account.balance.balance_type] ??
                          account.balance.balance_type}
                        {' · '}
                        {formatRelative(account.balance.fetched_at)}
                      </div>
                    </>
                  ) : (
                    <span className="text-muted-foreground">Not synced</span>
                  )}
                </TableCell>
                <TableCell>
                  <Switch
                    aria-label={`${account.name} is private`}
                    checked={account.visibility === 'private'}
                    disabled={!account.is_owner || update.isPending}
                    onCheckedChange={(checked) =>
                      change(account, { visibility: checked ? 'private' : 'shared' })
                    }
                  />
                </TableCell>
                <TableCell>
                  <Switch
                    aria-label={`Count ${account.name} in net worth`}
                    checked={account.include_in_net_worth}
                    disabled={!account.is_owner || update.isPending}
                    onCheckedChange={(checked) =>
                      change(account, { include_in_net_worth: checked })
                    }
                  />
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
          <Totals accounts={accounts.data} />
        </Table>
      )}
      <RenameDialog
        account={renaming}
        onClose={() => setRenaming(null)}
        onSave={(account, name) => {
          change(account, { display_name: name });
          setRenaming(null);
        }}
      />
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
    <TableFooter>
      <TableRow>
        <TableCell colSpan={2}>Total</TableCell>
        <TableCell className="text-right font-medium tabular-nums">
          {[...totals].map(([currency, amount]) => (
            <div key={currency}>{formatMoney(amount, currency)}</div>
          ))}
        </TableCell>
        <TableCell colSpan={2} />
      </TableRow>
    </TableFooter>
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
