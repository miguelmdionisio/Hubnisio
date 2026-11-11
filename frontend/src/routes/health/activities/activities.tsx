import { useInfiniteQuery } from '@tanstack/react-query';
import { Link, useNavigate, useSearch } from '@tanstack/react-router';
import { CalendarDays, Search } from 'lucide-react';
import { useEffect, useState } from 'react';
import { listActivitiesInfiniteQueryKey } from '@/api/@tanstack/react-query.gen';
import { listActivities } from '@/api/sdk.gen';
import type { ActivityLeg, ActivityRow } from '@/api/types.gen';
import { PageHeader } from '@/components/app-shell';
import { MenuPill, Pill } from '@/components/pills';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Skeleton } from '@/components/ui/skeleton';
import { errorMessage } from '@/lib/errors';
import { formatDistance, formatDuration, formatPace } from '@/lib/format';
import { cn } from '@/lib/utils';
import { dayHeading, ListPanel, rowClass } from '../../finance/transaction-rows';
import { type ActivitiesSearch, PERIODS, type Period, periodRange, SPORT_PILLS } from './search';
import { activityTitle, SPORTS, SportChip } from './sport';

const PAGE_SIZE = 30;
const SEARCH_DELAY_MS = 300;

/** "5:14 /km", "1:52 /100 m", "28.4 km/h": the figure each sport is read by. */
export function keyFigure(activity: Pick<ActivityLeg, 'figure' | 'figure_kind'>): string | null {
  if (activity.figure === null || activity.figure_kind === null) return null;
  switch (activity.figure_kind) {
    case 'pace_km':
      return `${formatPace(activity.figure)} /km`;
    case 'pace_100m':
      return `${formatPace(activity.figure)} /100 m`;
    case 'speed_kmh':
      return `${activity.figure.toLocaleString('en-GB', { maximumFractionDigits: 1 })} km/h`;
  }
}

export function ActivitiesPage() {
  const search = useSearch({ from: '/health/activities' });
  const navigate = useNavigate({ from: '/health/activities' });
  const setSearch = (changes: Partial<ActivitiesSearch>) =>
    navigate({
      search: (previous: ActivitiesSearch) => ({ ...previous, ...changes }),
      replace: true,
    });

  // Typing updates the URL (and the query) once the user pauses.
  const [text, setText] = useState(search.q ?? '');
  useEffect(() => {
    const timer = setTimeout(() => {
      const q = text.trim() || undefined;
      if (q !== search.q) {
        navigate({ search: (previous: ActivitiesSearch) => ({ ...previous, q }), replace: true });
      }
    }, SEARCH_DELAY_MS);
    return () => clearTimeout(timer);
  }, [text, search.q, navigate]);

  const filters = { sport: search.sport, q: search.q, ...periodRange(search.period) };
  const activities = useInfiniteQuery({
    queryKey: listActivitiesInfiniteQueryKey({ query: filters }),
    queryFn: async ({ pageParam, signal }) => {
      const { data } = await listActivities({
        query: { ...filters, limit: PAGE_SIZE, cursor: pageParam ?? undefined },
        signal,
        throwOnError: true,
      });
      return data;
    },
    initialPageParam: null as string | null,
    getNextPageParam: (page) => page.next_cursor,
  });
  const rows = activities.data?.pages.flatMap((page) => page.items) ?? [];

  return (
    <>
      <PageHeader title="Activities" />
      <div className="flex flex-wrap items-center gap-2">
        <label className="flex h-[34px] min-w-[180px] flex-1 items-center gap-2 rounded-full bg-surface px-3.5 focus-within:outline-2 focus-within:outline-ring md:h-9">
          <Search className="size-4 shrink-0 text-muted-foreground" aria-hidden />
          <input
            className="min-w-0 flex-1 bg-transparent text-sm outline-none placeholder:text-faint"
            placeholder="Search"
            aria-label="Search activities"
            value={text}
            onChange={(event) => setText(event.target.value)}
          />
        </label>
        <MenuPill
          icon={CalendarDays}
          ariaLabel="Period"
          on={search.period !== undefined}
          label={PERIODS.find((p) => p.value === (search.period ?? 'all'))?.label}
          value={search.period ?? 'all'}
          onChange={(value) =>
            setSearch({ period: value === 'all' ? undefined : (value as Period) })
          }
          align="end"
          options={PERIODS.map((p) => ({ value: p.value, label: p.label }))}
        />
      </div>
      <div className="-mx-4 mt-2 flex gap-2 overflow-x-auto px-4 pb-1 md:mx-0 md:px-0">
        {SPORT_PILLS.map((pill) => (
          <Pill
            key={pill.label}
            on={search.sport === pill.value}
            aria-pressed={search.sport === pill.value}
            onClick={() => setSearch({ sport: pill.value })}
          >
            {pill.label}
          </Pill>
        ))}
      </div>

      {activities.isError ? (
        <Alert variant="destructive" className="mt-4">
          <AlertTitle>Couldn't load activities</AlertTitle>
          <AlertDescription>{errorMessage(activities.error)}</AlertDescription>
        </Alert>
      ) : activities.isPending ? (
        <Skeleton className="mt-4 h-40 w-full rounded-[18px]" />
      ) : rows.length === 0 ? (
        <p className="py-7 text-center text-muted-foreground">No activities</p>
      ) : (
        <>
          <ActivityDays rows={rows} />
          {activities.hasNextPage && (
            <div className="mt-4 flex justify-center">
              <Pill
                disabled={activities.isFetchingNextPage}
                onClick={() => activities.fetchNextPage()}
              >
                {activities.isFetchingNextPage ? 'Loading…' : 'Load more'}
              </Pill>
            </div>
          )}
        </>
      )}
    </>
  );
}

/** The day an activity started, as "2026-11-08" (the watch's wall clock). */
const dayOf = (row: ActivityRow) => row.start.slice(0, 10);

function ActivityDays({ rows }: { rows: ActivityRow[] }) {
  const days = new Map<string, ActivityRow[]>();
  for (const row of rows) days.set(dayOf(row), [...(days.get(dayOf(row)) ?? []), row]);
  return (
    <>
      {[...days].map(([day, list]) => (
        <section key={day} aria-label={dayHeading(day)}>
          <h3 className="mt-[18px] mb-1.5 text-[13px] font-[650] text-muted-foreground">
            {dayHeading(day)}
          </h3>
          <ListPanel>
            <ul>
              {list.map((row) => (
                <li key={row.id}>
                  <ActivityRowLink row={row} />
                </li>
              ))}
            </ul>
          </ListPanel>
        </section>
      ))}
    </>
  );
}

function ActivityRowLink({ row }: { row: ActivityRow }) {
  const multi = row.legs.length > 0;
  const figure = keyFigure(row);
  return (
    <Link
      to="/health/activities/$id"
      params={{ id: String(row.id) }}
      className={cn(rowClass, 'grid-cols-[40px_minmax(0,1fr)_auto]')}
    >
      <SportChip group={row.group} multi={multi} />
      <span className="min-w-0">
        <span className="block truncate text-[15px] font-semibold">{activityTitle(row)}</span>
        <span className="flex items-center gap-1.5 truncate text-[13px] text-muted-foreground tabular-nums">
          {row.start.slice(11, 16)}
          {figure && <> · {figure}</>}
          {multi && (
            <span className="ml-1 flex gap-1" role="img" aria-label={legsLabel(row.legs)}>
              {row.legs.map((leg) => (
                <SportChip key={leg.id} group={leg.group} size="xs" />
              ))}
            </span>
          )}
        </span>
      </span>
      <span className="text-right tabular-nums">
        <span className="block text-[15px] font-[650]">
          {row.distance_m ? formatDistance(row.distance_m) : '–'}
        </span>
        <span className="block text-[13px] text-muted-foreground">
          {row.duration_s ? formatDuration(row.duration_s) : '–'}
          {row.load !== null && <> · load {Math.round(row.load)}</>}
        </span>
      </span>
    </Link>
  );
}

const legsLabel = (legs: ActivityLeg[]) =>
  `Legs: ${legs.map((l) => SPORTS[l.group].label).join(', ')}`;
