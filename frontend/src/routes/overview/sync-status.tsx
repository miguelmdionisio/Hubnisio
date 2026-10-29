import { Link } from '@tanstack/react-router';
import { Skeleton } from '@/components/ui/skeleton';
import { errorMessage } from '@/lib/errors';
import { cn } from '@/lib/utils';
import { syncState, useConnections } from '../finance/use-connections';

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
    <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-[13px] text-muted-foreground">
      <ul className="contents">
        {linked.map((connection) => {
          const state = syncState(connection);
          return (
            <li
              key={connection.id}
              className={cn('flex items-center gap-1.5', state.attention && 'text-destructive')}
            >
              <span
                aria-hidden
                className={cn(
                  'size-1.5 rounded-full',
                  state.attention ? 'bg-destructive' : 'bg-good',
                )}
              />
              {connection.institution_name} {state.text}
            </li>
          );
        })}
      </ul>
      {needsLook && (
        <Link to="/finance/connections" className="font-semibold text-primary">
          Check bank connections
        </Link>
      )}
    </div>
  );
}
