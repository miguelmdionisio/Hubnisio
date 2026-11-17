import { useQuery } from '@tanstack/react-query';
import { Link, useCanGoBack, useParams, useRouter } from '@tanstack/react-router';
import { ArrowLeft, Download } from 'lucide-react';
import { getActivityOptions } from '@/api/@tanstack/react-query.gen';
import type { ActivityDetail } from '@/api/types.gen';
import { PageHeader } from '@/components/app-shell';
import { pillClass } from '@/components/pills';
import { formatDay } from '@/lib/format';
import { cn } from '@/lib/utils';
import { QueryView } from '@/routes/overview/panel';
import { StreamLanes } from './charts';
import { Section } from './parts';
import { RouteMap } from './route-map';
import {
  Climbs,
  Durability,
  Figures,
  Legs,
  PoolSets,
  RunningForm,
  Splits,
  Zones,
} from './sections';
import { activityTitle, SportChip } from './sport';

function BackButton() {
  const canGoBack = useCanGoBack();
  const router = useRouter();
  const className =
    'tap-area -ml-1.5 grid size-9 shrink-0 place-items-center rounded-full text-muted-foreground hover:bg-surface hover:text-foreground';
  if (canGoBack) {
    return (
      <button
        type="button"
        aria-label="Back to activities"
        onClick={() => router.history.back()}
        className={className}
      >
        <ArrowLeft className="size-5" aria-hidden />
      </button>
    );
  }
  return (
    <Link to="/health/activities" aria-label="Back to activities" className={className}>
      <ArrowLeft className="size-5" aria-hidden />
    </Link>
  );
}

export function ActivityPage() {
  const { id } = useParams({ from: '/health/activities/$id' });
  const query = useQuery(getActivityOptions({ path: { activity_id: Number(id) } }));
  const activity = query.data;
  return (
    <>
      <PageHeader
        title={activity ? activityTitle(activity) : 'Activity'}
        leading={
          <>
            <BackButton />
            {activity && <SportChip group={activity.group} multi={activity.legs.length > 0} />}
          </>
        }
        actions={
          activity?.has_file && (
            <a
              href={`/api/health/activities/${activity.id}/file`}
              download
              className={cn(pillClass, 'no-underline')}
            >
              <Download aria-hidden />
              Download .FIT
            </a>
          )
        }
      />
      <QueryView query={query} skeleton="h-96 rounded-[18px]">
        {(data) => <Content activity={data} />}
      </QueryView>
    </>
  );
}

/** "Sun 8 Nov · 08:12": the day and the time the watch started it. */
function started(activity: ActivityDetail): string {
  return `${formatDay(activity.start.slice(0, 10))} · ${activity.start.slice(11, 16)}`;
}

function Content({ activity }: { activity: ActivityDetail }) {
  const { streams, splits, route, zones, durability, form, pool_sets: pool } = activity;
  const climbing = activity.family === 'ride' && activity.climbs.length > 0;
  const through = { run: 'Through the run', bike: 'Through the ride', swim: 'Through the swim' };
  return (
    <div className="flex flex-col gap-5">
      <p className="text-[13px] text-muted-foreground tabular-nums">{started(activity)}</p>
      <Figures activity={activity} />
      {activity.legs.length > 0 && <Legs legs={activity.legs} />}
      {streams && (
        <Section
          title={
            activity.group === 'run' || activity.group === 'bike' || activity.group === 'swim'
              ? through[activity.group]
              : 'Over time'
          }
          aside={streams.axis === 'distance' ? 'by distance' : 'by time'}
        >
          <StreamLanes group={activity.group} streams={streams} />
        </Section>
      )}
      {(splits || route) && (
        <div className={cn('grid gap-5', splits && route && 'lg:grid-cols-2')}>
          {splits && <Splits splits={splits} group={activity.group} />}
          {route && (
            <Section
              title="Route"
              aside={
                activity.summary.elevation_gain_m !== null &&
                `+${Math.round(activity.summary.elevation_gain_m)} m${
                  activity.summary.elevation_loss_m === null
                    ? ''
                    : ` · −${Math.round(activity.summary.elevation_loss_m)} m`
                }`
              }
            >
              <RouteMap route={route} />
            </Section>
          )}
        </div>
      )}
      {pool && <PoolSets pool={pool} poolLength={activity.summary.pool_length_m} />}
      {climbing && <Climbs climbs={activity.climbs} bestVam={activity.best_vam} />}
      {(durability || zones) && (
        <div className={cn('grid gap-5', durability && zones && 'lg:grid-cols-2')}>
          {durability && <Durability durability={durability} group={activity.group} />}
          {zones && <Zones zones={zones} />}
        </div>
      )}
      {form && <RunningForm form={form} />}
    </div>
  );
}
