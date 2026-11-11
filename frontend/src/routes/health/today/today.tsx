import { useQuery } from '@tanstack/react-query';
import { Link } from '@tanstack/react-router';
import { ArrowDown, ArrowUp, Check, Minus, TriangleAlert } from 'lucide-react';
import type { ReactNode } from 'react';
import { getTodayOptions } from '@/api/@tanstack/react-query.gen';
import type { LastNight, RecentActivity, Signal, Today } from '@/api/types.gen';
import { PageHeader } from '@/components/app-shell';
import { pillClass } from '@/components/pills';
import { Card } from '@/components/ui/card';
import { formatDistance, formatDuration } from '@/lib/format';
import { cn } from '@/lib/utils';
import { QueryView } from '@/routes/overview/panel';
import { rowClass } from '../../finance/transaction-rows';
import { activityTitle, type Group, SportChip } from '../activities/sport';
import { HrvChart } from '../recovery/charts';
import { clock, hm, hmSeconds, STAGE_COLORS, STAGE_NAMES } from '../sleep/units';
import { BAND_NAMES, SPORTS } from '../training/charts';
import { FitnessChart, WeekChart } from './charts';

export function TodayPage() {
  const query = useQuery(getTodayOptions());
  return (
    <>
      <PageHeader title="Today" />
      <QueryView query={query} skeleton="h-96 rounded-[18px]">
        {(data) => <Content data={data} />}
      </QueryView>
    </>
  );
}

const number = (value: number | null | undefined, places = 0) =>
  value === null || value === undefined
    ? '–'
    : value.toLocaleString('en-GB', { maximumFractionDigits: places });

const signed = (value: number) =>
  `${value > 0 ? '+' : value < 0 ? '−' : ''}${number(Math.abs(value))}`;

const weekdayMonth = (isoDate: string) =>
  new Intl.DateTimeFormat('en-GB', { weekday: 'short', day: 'numeric', month: 'short' }).format(
    new Date(`${isoDate}T00:00:00`),
  );

function Content({ data }: { data: Today }) {
  const { figures, night, signals } = data;
  return (
    <div className="flex flex-col gap-5">
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <FormTile data={figures.form} />
        <SleepTile data={figures.sleep} />
        <HrvTile data={figures.hrv} />
        <RestingTile data={figures.resting_hr} />
      </div>

      <SignalsStrip signals={signals} />

      <div className="grid gap-5 lg:grid-cols-2">
        <Card className="min-w-0 px-(--card-spacing)">
          <Heading title="Fitness, 90 days">
            <Key color="var(--primary)">Fitness</Key>
            <Key color="var(--muted-foreground)">Fatigue</Key>
            <Key color="var(--good)">Form</Key>
          </Heading>
          {data.fitness.length > 0 ? (
            <FitnessChart points={data.fitness} />
          ) : (
            <Gap>No activities yet</Gap>
          )}
        </Card>
        <Card className="min-w-0 px-(--card-spacing)">
          <Heading title="Last 7 days">
            <span className="tabular-nums">
              {number(data.week.total_hours, 1)} h · {number(data.week.average_hours, 1)} h a day
            </span>
            {SPORTS.map((sport) => (
              <Key key={sport.key} color={sport.color}>
                {sport.label}
              </Key>
            ))}
          </Heading>
          <WeekChart week={data.week} />
        </Card>
      </div>

      <div className="grid gap-5 lg:grid-cols-2">
        <Card className="min-w-0 px-(--card-spacing)">
          <Heading title={night?.last_night === false ? 'Latest night' : 'Last night'}>
            {night && (
              <span className="tabular-nums">
                {night.last_night ? '' : `${weekdayMonth(night.day)} · `}
                {clock(night.bed_min)} – {clock(night.wake_min)}
              </span>
            )}
          </Heading>
          {night ? <NightSplit night={night} /> : <Gap>No night recorded</Gap>}
        </Card>
        <Card className="min-w-0 px-(--card-spacing)">
          <Heading title="HRV, 30 nights">
            {data.hrv.summary.avg7 !== null && (
              <span className="tabular-nums">7-day {number(data.hrv.summary.avg7)} ms</span>
            )}
            <Key color="var(--good)">Normal range</Key>
            <Key color="var(--primary)">7-day</Key>
          </Heading>
          <HrvChart data={data.hrv} height={190} />
          {data.hrv.summary.nights === 0 && <Gap>No nights with HRV</Gap>}
        </Card>
      </div>

      <section aria-labelledby="recent">
        <div className="mb-2 flex items-center">
          <h2 id="recent" className="text-[15px] font-semibold">
            Recent activities
          </h2>
          <Link to="/health/activities" className={cn(pillClass, 'ml-auto')}>
            All activities
          </Link>
        </div>
        {data.activities.length === 0 ? (
          <Gap>No activities yet</Gap>
        ) : (
          <ul className="rounded-[18px] bg-surface p-1.5">
            {data.activities.map((activity) => (
              <li key={activity.id}>
                <ActivityLink activity={activity} />
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}

function Heading({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
      <h2 className="text-[15px] font-semibold">{title}</h2>
      <div className="ml-auto flex flex-wrap items-center gap-x-3.5 gap-y-1 text-xs text-muted-foreground">
        {children}
      </div>
    </div>
  );
}

function Key({ color, children }: { color: string; children: ReactNode }) {
  return (
    <span className="inline-flex items-center gap-1.5">
      <i aria-hidden className="inline-block size-2 rounded-full" style={{ background: color }} />
      {children}
    </span>
  );
}

function Gap({ children }: { children: ReactNode }) {
  return <p className="py-6 text-[13px] text-muted-foreground">{children}</p>;
}

type TileProps = {
  to: '/health/training' | '/health/sleep' | '/health/recovery';
  label: string;
  value: string;
  unit?: string;
  children?: ReactNode;
};

function Tile({ to, label, value, unit, children }: TileProps) {
  return (
    <Link
      to={to}
      className="block min-w-0 rounded-[18px] bg-surface p-3.5 transition-colors hover:bg-surface-2 md:p-4"
    >
      <span className="block text-[13px] text-muted-foreground">{label}</span>
      <span className="mt-1 block text-[28px] leading-tight font-bold tracking-tight tabular-nums">
        {value}
        {unit && value !== '–' && (
          <small className="ml-1 text-base font-semibold text-muted-foreground">{unit}</small>
        )}
      </span>
      <span className="block min-h-5 text-[13px] text-muted-foreground">
        {children || (value === '–' ? 'No data' : null)}
      </span>
    </Link>
  );
}

function FormTile({ data }: { data: Today['figures']['form'] }) {
  return (
    <Tile to="/health/training" label="Form" value={data.form === null ? '–' : signed(data.form)}>
      {data.band && (
        <>
          {BAND_NAMES[data.band]}
          {data.fitness !== null && ` · fitness ${number(data.fitness)}`}
        </>
      )}
    </Tile>
  );
}

function SleepTile({ data }: { data: Today['figures']['sleep'] }) {
  const need = data?.need_minutes ?? null;
  return (
    <Tile
      to="/health/sleep"
      label={data && !data.last_night ? `Night of ${weekdayMonth(data.day)}` : 'Last night'}
      value={data?.slept_s ? hmSeconds(data.slept_s) : '–'}
    >
      {data?.slept_s
        ? [data.score !== null && `Score ${data.score}`, need !== null && `need ${hm(need)}`]
            .filter(Boolean)
            .join(' · ')
        : null}
    </Tile>
  );
}

function HrvTile({ data }: { data: Today['figures']['hrv'] }) {
  return (
    <Tile to="/health/recovery" label="HRV, 7-day" value={number(data.avg7)} unit="ms">
      {data.position && (
        <span
          className={cn(
            'inline-flex items-center gap-1',
            data.position === 'in' ? 'text-good' : 'text-destructive',
          )}
        >
          {data.position === 'below' && <ArrowDown className="size-3.5" aria-hidden />}
          {data.position === 'above' && <ArrowUp className="size-3.5" aria-hidden />}
          {data.position === 'in' ? 'In range' : data.position === 'below' ? 'Below' : 'Above'}
        </span>
      )}
    </Tile>
  );
}

function RestingTile({ data }: { data: Today['figures']['resting_hr'] }) {
  const change = data.change;
  return (
    <Tile to="/health/recovery" label="Resting HR" value={number(data.latest)} unit="bpm">
      {change !== null && (
        <span
          className={cn(
            'inline-flex items-center gap-1',
            change <= 0 ? 'text-good' : change > 3 ? 'text-destructive' : undefined,
          )}
        >
          {change < 0 && <ArrowDown className="size-3.5" aria-hidden />}
          {change > 0 && <ArrowUp className="size-3.5" aria-hidden />}
          {change === 0 ? 'Same as 7-day' : `${number(Math.abs(change), 1)} vs 7-day`}
        </span>
      )}
    </Tile>
  );
}

const STATES = {
  ok: { label: 'OK', icon: Check, bar: 'bg-good h-1.5' },
  watch: { label: 'Watch', icon: TriangleAlert, bar: 'bg-chart-3 h-2.5' },
  no_data: { label: 'No data', icon: Minus, bar: 'h-1.5 border border-dashed border-faint' },
} as const;

const SIGNAL_NAMES: Record<Signal['key'], string> = {
  hrv: 'HRV',
  resting_hr: 'Resting HR',
  sleep: 'Sleep',
  body_battery: 'Body Battery',
  form: 'Form',
};

/** The phone's strip: one segment per signal, told apart by height, outline and icon as well as
 * colour, with the list a screen reader gets. */
function SignalsStrip({ signals }: { signals: Today['signals'] }) {
  return (
    <Card className="min-w-0 gap-3 px-(--card-spacing) md:hidden">
      <Link to="/health/recovery" className="flex items-baseline gap-2">
        <h2 className="text-[15px] font-semibold">Signals today</h2>
        <span className="ml-auto text-[13px] text-muted-foreground tabular-nums">
          {signals.ok} of {signals.total} OK
        </span>
      </Link>
      <div className="flex items-end gap-1.5" aria-hidden>
        {signals.items.map((signal) => (
          <span key={signal.key} className={cn('flex-1 rounded-full', STATES[signal.state].bar)} />
        ))}
      </div>
      <ul className="flex flex-wrap gap-x-3.5 gap-y-1 text-[13px] text-muted-foreground">
        {signals.items.map((signal) => {
          const state = STATES[signal.state];
          const Icon = state.icon;
          return (
            <li key={signal.key} className="inline-flex items-center gap-1">
              <Icon className="size-3.5" strokeWidth={3} aria-hidden />
              {SIGNAL_NAMES[signal.key]}
              <span className="sr-only">: {state.label}</span>
            </li>
          );
        })}
      </ul>
    </Card>
  );
}

function NightSplit({ night }: { night: LastNight }) {
  const total = night.stages.reduce((sum, stage) => sum + stage.seconds, 0);
  return (
    <div className="mt-3 flex flex-col gap-3">
      <div
        className="flex h-3 gap-0.5 overflow-hidden rounded-full"
        role="img"
        aria-label={`Stages: ${night.stages.map((s) => `${STAGE_NAMES[s.stage as keyof typeof STAGE_NAMES]} ${hmSeconds(s.seconds)}`).join(', ')}`}
      >
        {night.stages
          .filter((stage) => stage.seconds > 0)
          .map((stage) => (
            <span
              key={stage.stage}
              style={{
                flex: stage.seconds / (total || 1),
                background: STAGE_COLORS[stage.stage as keyof typeof STAGE_COLORS],
              }}
            />
          ))}
      </div>
      <ul className="flex flex-wrap gap-x-4 gap-y-1 text-[13px] text-muted-foreground tabular-nums">
        {night.stages.map((stage) => (
          <li key={stage.stage} className="inline-flex items-center gap-1.5">
            <i
              aria-hidden
              className="size-2 rounded-full"
              style={{ background: STAGE_COLORS[stage.stage as keyof typeof STAGE_COLORS] }}
            />
            {STAGE_NAMES[stage.stage as keyof typeof STAGE_NAMES]} {hmSeconds(stage.seconds)}
          </li>
        ))}
      </ul>
      <p className="text-[13px] text-muted-foreground tabular-nums">
        {night.score !== null && `Score ${night.score} · `}
        In bed {clock(night.bed_min)}, awake {clock(night.wake_min)}
      </p>
    </div>
  );
}

function ActivityLink({ activity }: { activity: RecentActivity }) {
  return (
    <Link
      to="/health/activities/$id"
      params={{ id: String(activity.id) }}
      className={cn(rowClass, 'grid-cols-[40px_minmax(0,1fr)_auto]')}
    >
      <SportChip group={activity.group as Group} />
      <span className="min-w-0">
        <span className="block truncate text-[15px] font-semibold">
          {activityTitle({ name: activity.name, group: activity.group as Group })}
        </span>
        <span className="block truncate text-[13px] text-muted-foreground tabular-nums">
          {weekdayMonth(activity.start.slice(0, 10))} · {activity.start.slice(11, 16)}
        </span>
      </span>
      <span className="text-right tabular-nums">
        <span className="block text-[15px] font-[650]">
          {activity.distance_m ? formatDistance(activity.distance_m) : '–'}
        </span>
        <span className="block text-[13px] text-muted-foreground">
          {activity.duration_s ? formatDuration(activity.duration_s) : '–'}
          {activity.load !== null && <> · load {Math.round(activity.load)}</>}
        </span>
      </span>
    </Link>
  );
}
