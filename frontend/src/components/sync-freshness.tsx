import { Link } from '@tanstack/react-router';
import { formatRelative } from '@/lib/format';
import { cn } from '@/lib/utils';
import { syncState, useConnections } from '@/routes/finance/use-connections';

/**
 * The page header's one line on how fresh the figures are: the oldest sync among the linked
 * connections, or which one needs a look. Overview lists each connection (SyncStatus).
 */
export function SyncFreshness({ className }: { className?: string }) {
  const connections = useConnections();
  const linked = (connections.data ?? []).filter((connection) => connection.status !== 'pending');
  if (linked.length === 0) return null;

  const states = linked.map((connection) => ({ connection, ...syncState(connection) }));
  const broken = states.filter(
    ({ connection }) => connection.status !== 'active' || connection.last_error,
  );
  const [firstBroken] = broken;
  if (firstBroken) {
    return (
      <Link
        to="/finance/connections"
        className={cn(
          'flex items-center gap-1.5 text-[12.5px] font-medium text-destructive hover:underline',
          className,
        )}
      >
        <i className="size-[7px] rounded-full bg-destructive" aria-hidden />
        {broken.length === 1
          ? `${firstBroken.connection.institution_name} needs a look`
          : `${broken.length} connections need a look`}
      </Link>
    );
  }

  const syncing = states.some(({ connection }) => connection.syncing);
  const synced = linked
    .map((connection) => connection.last_synced_at)
    .filter((at): at is string => Boolean(at))
    .sort();
  const [oldest] = synced;
  const stale = states.some(({ attention }) => attention);
  const text = syncing ? 'Syncing' : oldest ? `Synced ${formatRelative(oldest)}` : 'Not synced yet';
  return (
    <span
      className={cn('flex items-center gap-1.5 text-[12.5px] text-muted-foreground', className)}
    >
      <i
        className={cn(
          'size-[7px] rounded-full',
          stale ? 'border border-dashed border-muted-foreground' : 'bg-good',
          syncing && 'animate-pulse',
        )}
        aria-hidden
      />
      {text}
    </span>
  );
}
