import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Landmark, LoaderCircle, RefreshCw } from 'lucide-react';
import { useState } from 'react';
import {
  deleteConnectionMutation,
  listBanksOptions,
  listConnectionsQueryKey,
  syncConnectionMutation,
} from '@/api/@tanstack/react-query.gen';
import type { ConnectionOut } from '@/api/types.gen';
import { PageHeader } from '@/components/app-shell';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
  Card,
  CardAction,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from '@/components/ui/card';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { Skeleton } from '@/components/ui/skeleton';
import { errorMessage } from '@/lib/errors';
import { formatRelative } from '@/lib/format';
import { describeSyncError, useConnections, useStartConnection } from './use-connections';

// Consent has to be renewed at the bank; warn this many days ahead.
const RENEWAL_WARNING_DAYS = 14;
const COUNTRIES = [
  { code: 'PT', name: 'Portugal' },
  { code: 'LT', name: 'Lithuania' },
];

export function ConnectionsPage() {
  const [pollUntil, setPollUntil] = useState(0);
  const [linking, setLinking] = useState(false);
  const connections = useConnections(pollUntil);

  return (
    <>
      <PageHeader
        title="Bank connections"
        description="Each connection is your consent for the hub to read one bank's accounts. It can't move money."
        actions={<Button onClick={() => setLinking(true)}>Link a bank</Button>}
      />
      {connections.isPending && <Skeleton className="h-36 w-full max-w-xl" />}
      {connections.isError && (
        <Alert variant="destructive">
          <AlertTitle>Couldn't load connections</AlertTitle>
          <AlertDescription>{errorMessage(connections.error)}</AlertDescription>
        </Alert>
      )}
      {connections.data?.length === 0 && (
        <Card className="max-w-xl">
          <CardHeader>
            <CardTitle>No banks linked yet</CardTitle>
            <CardDescription>
              Link a bank to bring in its accounts, balances and transactions. On the first sync the
              hub fetches as much history as the bank allows.
            </CardDescription>
          </CardHeader>
          <CardFooter>
            <Button onClick={() => setLinking(true)}>Link a bank</Button>
          </CardFooter>
        </Card>
      )}
      <div className="grid gap-4 xl:grid-cols-2">
        {connections.data?.map((connection) => (
          <ConnectionCard
            key={connection.id}
            connection={connection}
            onSyncQueued={() => setPollUntil(Date.now() + 60_000)}
          />
        ))}
      </div>
      <LinkBankDialog open={linking} onOpenChange={setLinking} />
    </>
  );
}

function ConnectionCard({
  connection,
  onSyncQueued,
}: {
  connection: ConnectionOut;
  onSyncQueued: () => void;
}) {
  const queryClient = useQueryClient();
  const [confirming, setConfirming] = useState(false);
  const sync = useMutation({ ...syncConnectionMutation(), onSuccess: onSyncQueued });
  const relink = useStartConnection();
  const disconnect = useMutation({
    ...deleteConnectionMutation(),
    onSuccess: () => {
      setConfirming(false);
      queryClient.invalidateQueries({ queryKey: listConnectionsQueryKey() });
    },
  });

  const expired = connection.status === 'expired';
  const expiresSoon =
    !expired && connection.days_left !== null && connection.days_left <= RENEWAL_WARNING_DAYS;
  const accounts = connection.account_ids.length;

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Landmark className="size-4 text-muted-foreground" aria-hidden />
          {connection.institution_name}
        </CardTitle>
        <CardDescription>
          {accounts} {accounts === 1 ? 'account' : 'accounts'}
          {connection.days_left !== null &&
            !expired &&
            ` · consent valid for ${connection.days_left} more days`}
        </CardDescription>
        <CardAction>
          {expired ? (
            <Badge variant="destructive">Needs linking again</Badge>
          ) : connection.syncing ? (
            <Badge variant="secondary">
              <LoaderCircle className="animate-spin" aria-hidden />
              Syncing
            </Badge>
          ) : (
            <Badge variant="outline">Active</Badge>
          )}
        </CardAction>
      </CardHeader>
      <CardContent className="space-y-1 text-sm">
        <p className="text-muted-foreground">
          {connection.last_synced_at
            ? `Last synced ${formatRelative(connection.last_synced_at)}.`
            : 'Not synced yet.'}
        </p>
        {connection.last_error && (
          <p className="text-destructive">
            The last sync failed: {describeSyncError(connection.last_error)}.
          </p>
        )}
        {expired && <p>The bank ended this consent. Link again to keep syncing.</p>}
        {expiresSoon && (
          <p className="text-amber-700 dark:text-amber-400">
            The consent ends in {connection.days_left} days. Link again to renew it.
          </p>
        )}
        {sync.data?.queued === false && <p>A sync is already waiting to run.</p>}
        {(sync.isError || relink.isError || disconnect.isError) && (
          <p className="text-destructive">
            {errorMessage(sync.error ?? relink.error ?? disconnect.error)}
          </p>
        )}
      </CardContent>
      <CardFooter className="gap-2">
        {(expired || expiresSoon) && (
          <Button
            disabled={relink.isPending}
            onClick={() =>
              relink.mutate({
                body: {
                  institution_name: connection.institution_name,
                  country: connection.institution_country,
                },
              })
            }
          >
            Link again
          </Button>
        )}
        {!expired && (
          <Button
            variant="outline"
            disabled={connection.syncing || sync.isPending}
            onClick={() => sync.mutate({ path: { connection_id: connection.id } })}
          >
            <RefreshCw aria-hidden />
            Sync now
          </Button>
        )}
        <Button variant="ghost" onClick={() => setConfirming(true)}>
          Disconnect
        </Button>
      </CardFooter>

      <Dialog open={confirming} onOpenChange={setConfirming}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Disconnect {connection.institution_name}?</DialogTitle>
            <DialogDescription>
              The hub stops syncing and asks the bank to end the consent. The accounts and the
              history already fetched stay.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setConfirming(false)}>
              Cancel
            </Button>
            <Button
              variant="destructive"
              disabled={disconnect.isPending}
              onClick={() => disconnect.mutate({ path: { connection_id: connection.id } })}
            >
              Disconnect
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </Card>
  );
}

function LinkBankDialog({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const [country, setCountry] = useState('PT');
  const [filter, setFilter] = useState('');
  const banks = useQuery({
    ...listBanksOptions({ query: { country } }),
    enabled: open,
    staleTime: 60 * 60_000,
  });
  const start = useStartConnection();
  const needle = filter.trim().toLowerCase();
  const shown = banks.data?.filter((bank) => bank.name.toLowerCase().includes(needle));

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Link a bank</DialogTitle>
          <DialogDescription>
            You'll approve access in your bank's app, then come back here.
          </DialogDescription>
        </DialogHeader>
        <div className="flex gap-2">
          <Select value={country} onValueChange={setCountry}>
            <SelectTrigger className="w-36" aria-label="Country">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {COUNTRIES.map((option) => (
                <SelectItem key={option.code} value={option.code}>
                  {option.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Input
            placeholder="Search banks"
            aria-label="Search banks"
            value={filter}
            onChange={(event) => setFilter(event.target.value)}
          />
        </div>
        <div className="max-h-80 space-y-1 overflow-y-auto">
          {banks.isPending && <Skeleton className="h-24 w-full" />}
          {banks.isError && <p className="text-sm text-destructive">{errorMessage(banks.error)}</p>}
          {shown?.length === 0 && (
            <p className="text-sm text-muted-foreground">No bank matches “{filter}”.</p>
          )}
          {shown?.map((bank) => (
            <button
              key={bank.name}
              type="button"
              disabled={start.isPending}
              onClick={() => start.mutate({ body: { institution_name: bank.name, country } })}
              className="flex w-full items-center gap-3 rounded-md px-2 py-2 text-left text-sm hover:bg-muted disabled:opacity-50"
            >
              {bank.logo ? (
                <img src={bank.logo} alt="" className="size-6 rounded object-contain" />
              ) : (
                <Landmark className="size-6 text-muted-foreground" aria-hidden />
              )}
              <span className="flex-1">{bank.name}</span>
              {bank.beta && <Badge variant="outline">Beta</Badge>}
            </button>
          ))}
        </div>
        {start.isPending && (
          <p className="text-sm text-muted-foreground">Opening your bank's authorization page…</p>
        )}
        {start.isError && <p className="text-sm text-destructive">{errorMessage(start.error)}</p>}
      </DialogContent>
    </Dialog>
  );
}
