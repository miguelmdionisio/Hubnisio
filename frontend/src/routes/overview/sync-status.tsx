import { Link } from '@tanstack/react-router';
import type { ConnectionOut } from '@/api/types.gen';
import { Skeleton } from '@/components/ui/skeleton';
import { errorMessage } from '@/lib/errors';
import { formatRelative } from '@/lib/format';
import { cn } from '@/lib/utils';
import { useConnections } from '../finance/use-connections';

/** Syncs run several times a day; a day and a bit without one means something is off. */
const STALE_MS = 26 * 3_600_000;

/** How fresh the figures below are: when each connection last synced, and which need a look. */
export function SyncStatus() {
  const connections = useConnections();
  if (connections.isPending) return <Skeleton className="h-4 w-48" />;
  if (connections.isError) {
    return <p className="text-xs text-muted-foreground">{errorMessage(connections.error)}</p>;
  }
  const linked = connections.data.filter((connection) => connection.status !== 'pending');
  if (linked.length === 0) {
    return (
      <p className="text-xs text-muted-foreground">
        No bank is linked yet.{' '}
        <Link to="/finance/connections" className="underline underline-offset-4">
          Link a bank
        </Link>
      </p>
    );
  }
  const needsLook = linked.some((connection) => syncState(connection).attention);
  return (
    <div className="text-xs text-muted-foreground sm:text-right">
      <ul>
        {linked.map((connection) => {
          const state = syncState(connection);
          return (
            <li key={connection.id} className={cn(state.attention && 'text-destructive')}>
              {connection.institution_name} {state.text}
            </li>
          );
        })}
      </ul>
      {needsLook && (
        <Link to="/finance/connections" className="underline underline-offset-4">
          Check bank connections
        </Link>
      )}
    </div>
  );
}

function syncState(connection: ConnectionOut): { text: string; attention: boolean } {
  if (connection.status !== 'active') return { text: 'needs reconnecting', attention: true };
  if (connection.syncing) return { text: 'is syncing now', attention: false };
  if (connection.last_error) return { text: 'failed its last sync', attention: true };
  if (!connection.last_synced_at) return { text: "hasn't synced yet", attention: false };
  const stale = Date.now() - Date.parse(connection.last_synced_at) > STALE_MS;
  return {
    text: `synced ${formatRelative(connection.last_synced_at)}`,
    attention: stale,
  };
}
