import { useQuery } from '@tanstack/react-query';
import { Link } from '@tanstack/react-router';
import { getHealthConnectionOptions } from '@/api/@tanstack/react-query.gen';
import type { HealthConnection } from '@/api/types.gen';
import { formatRelative, parseDate } from '@/lib/format';
import { cn } from '@/lib/utils';

/**
 * Garmin's data counts as stale once the last successful sync is over 26 hours old: the daily
 * task runs once a day, so a day plus two hours of slack means at least one run was missed.
 */
export const HEALTH_STALE_MS = 26 * 3_600_000;

/** The key needs a look this many days before it lapses (as the Garmin page warns). */
const KEY_WARNING_DAYS = 14;

export type HealthFreshnessState =
  | { kind: 'look' }
  | { kind: 'syncing' }
  | { kind: 'synced'; at: string; stale: boolean }
  | { kind: 'never' };

/** Whole days from today to a calendar date; negative once it has passed. */
function daysUntil(isoDate: string, now: number): number {
  const date = new Date(now);
  const today = new Date(date.getFullYear(), date.getMonth(), date.getDate());
  return Math.round((parseDate(isoDate).getTime() - today.getTime()) / 86_400_000);
}

/**
 * What the Health header says about Garmin: it needs a look (nothing linked, the last sync
 * failed, or the key lapses within 14 days or has lapsed), a sync is running, or when it last
 * synced and whether that is stale.
 */
export function healthFreshness(data: HealthConnection, now = Date.now()): HealthFreshnessState {
  const keyLapsing =
    data.key_expires_soon ||
    (data.key_expires_on ? daysUntil(data.key_expires_on, now) <= KEY_WARNING_DAYS : false);
  if (
    !data.linked ||
    data.status === 'expired' ||
    data.last_run?.status === 'failed' ||
    keyLapsing
  ) {
    return { kind: 'look' };
  }
  if (data.syncing) return { kind: 'syncing' };
  if (!data.last_synced_at) return { kind: 'never' };
  return {
    kind: 'synced',
    at: data.last_synced_at,
    stale: now - Date.parse(data.last_synced_at) > HEALTH_STALE_MS,
  };
}

/** The Health page header's one line on how fresh Garmin's data is, like Finance's. */
export function HealthFreshness({ className }: { className?: string }) {
  const { data } = useQuery(getHealthConnectionOptions());
  if (!data) return null;
  const state = healthFreshness(data);
  if (state.kind === 'look') {
    return (
      <Link
        to="/health/garmin"
        className={cn(
          'flex items-center gap-1.5 text-[12.5px] font-medium text-destructive hover:underline',
          className,
        )}
      >
        <i className="size-[7px] rounded-full bg-destructive" aria-hidden />
        Garmin needs a look
      </Link>
    );
  }
  const stale = state.kind === 'never' || (state.kind === 'synced' && state.stale);
  const text =
    state.kind === 'syncing'
      ? 'Garmin syncing'
      : state.kind === 'synced'
        ? `Garmin synced ${formatRelative(state.at)}`
        : 'Garmin not synced yet';
  return (
    <span
      className={cn('flex items-center gap-1.5 text-[12.5px] text-muted-foreground', className)}
    >
      <i
        className={cn(
          'size-[7px] rounded-full',
          stale ? 'border border-dashed border-muted-foreground' : 'bg-good',
          state.kind === 'syncing' && 'animate-pulse',
        )}
        aria-hidden
      />
      {text}
      {stale && <span className="sr-only"> (stale)</span>}
    </span>
  );
}
