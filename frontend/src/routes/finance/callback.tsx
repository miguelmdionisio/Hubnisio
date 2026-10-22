import { useQuery } from '@tanstack/react-query';
import { Link, useSearch } from '@tanstack/react-router';
import { CircleCheck, LoaderCircle } from 'lucide-react';
import { type ReactNode, useState } from 'react';
import { completeConnection } from '@/api/sdk.gen';
import { PageHeader } from '@/components/app-shell';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { errorMessage } from '@/lib/errors';
import { describeSyncError, useConnections } from './use-connections';

// How long to keep checking for the first sync before leaving it to the connections page.
const FIRST_SYNC_WAIT_MS = 5 * 60_000;

export type CallbackSearch = {
  code?: string;
  state?: string;
  error?: string;
  error_description?: string;
};

export function validateCallbackSearch(search: Record<string, unknown>): CallbackSearch {
  const text = (value: unknown) => (typeof value === 'string' && value ? value : undefined);
  return {
    code: text(search.code),
    state: text(search.state),
    error: text(search.error),
    error_description: text(search.error_description),
  };
}

export function CallbackPage() {
  const search = useSearch({ from: '/finance/connections/callback' });
  const { code, state } = search;
  const [waitUntil] = useState(() => Date.now() + FIRST_SYNC_WAIT_MS);

  // A query, not a mutation: it runs once per state however often the page renders (React's
  // strict mode mounts twice), and reloading the page shows the same result. No abort signal
  // is passed on purpose: an aborted request may still have redeemed the single-use code.
  const completion = useQuery({
    queryKey: ['completeConnection', state],
    queryFn: async () => {
      const { data } = await completeConnection({
        body: { code: code ?? '', state: state ?? '' },
        throwOnError: true,
      });
      return data;
    },
    enabled: Boolean(code && state),
    staleTime: Number.POSITIVE_INFINITY,
    gcTime: Number.POSITIVE_INFINITY,
    retry: false,
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
  });
  const connections = useConnections(completion.isSuccess ? waitUntil : 0);
  const connection =
    connections.data?.find((item) => item.id === completion.data?.id) ?? completion.data;

  if (search.error || !code || !state) {
    return (
      <Outcome title="The bank didn't link">
        <Alert variant="destructive">
          <AlertTitle>Authorization didn't complete</AlertTitle>
          <AlertDescription>
            {search.error_description ?? search.error ?? 'The bank sent back no authorization.'}
          </AlertDescription>
        </Alert>
      </Outcome>
    );
  }
  if (completion.isPending) {
    return (
      <Outcome title="Linking your bank">
        <p className="flex items-center gap-2 text-muted-foreground">
          <LoaderCircle className="size-4 animate-spin" aria-hidden />
          Finishing the link…
        </p>
      </Outcome>
    );
  }
  if (completion.isError || !connection) {
    return (
      <Outcome title="The bank didn't link">
        <Alert variant="destructive">
          <AlertTitle>Linking failed</AlertTitle>
          <AlertDescription>{errorMessage(completion.error)}</AlertDescription>
        </Alert>
      </Outcome>
    );
  }

  const accounts = connection.account_ids.length;
  return (
    <Outcome title={`${connection.institution_name} is linked`}>
      <p className="flex items-center gap-2">
        <CircleCheck className="size-4 text-emerald-600" aria-hidden />
        The hub can now read {accounts} {accounts === 1 ? 'account' : 'accounts'}.
      </p>
      {connection.last_synced_at ? (
        <p>Your history is in.</p>
      ) : connection.last_error ? (
        <p className="text-destructive">
          The first sync failed: {describeSyncError(connection.last_error)}. You can retry from the
          connections page.
        </p>
      ) : (
        <p className="flex items-center gap-2 text-muted-foreground">
          <LoaderCircle className="size-4 animate-spin" aria-hidden />
          Fetching as much history as the bank allows. This can take a minute.
        </p>
      )}
    </Outcome>
  );
}

function Outcome({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="max-w-xl">
      <PageHeader title={title} />
      <div className="space-y-3 text-sm">{children}</div>
      <div className="mt-6 flex gap-2">
        <Button asChild>
          <Link to="/finance/accounts">See accounts</Link>
        </Button>
        <Button variant="outline" asChild>
          <Link to="/finance/connections">Bank connections</Link>
        </Button>
      </div>
    </div>
  );
}
