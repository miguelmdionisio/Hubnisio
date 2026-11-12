import { useQuery } from '@tanstack/react-query';
import { useNavigate, useSearch } from '@tanstack/react-router';
import { ArrowUp, Check, TriangleAlert } from 'lucide-react';
import type { ReactNode } from 'react';
import { getTrainingOptions } from '@/api/@tanstack/react-query.gen';
import type { Training, TrainingIntensity } from '@/api/types.gen';
import { PageHeader } from '@/components/app-shell';
import { NoData } from '@/components/no-data';
import { Segmented } from '@/components/segmented';
import { Card } from '@/components/ui/card';
import { formatMonth } from '@/lib/format';
import { cn } from '@/lib/utils';
import { QueryView } from '@/routes/overview/panel';
import { BAND_NAMES, LoadChart, SPORTS, WeeksChart } from './charts';
import { type Period, periodOf, type TrainingSearch } from './search';

const PERIODS: { value: Period; label: string }[] = [
  { value: '90', label: '90 days' },
  { value: '180', label: '6 months' },
  { value: '365', label: '1 year' },
  { value: 'all', label: 'All' },
];

export function TrainingPage() {
  const search = useSearch({ from: '/health/training' });
  const navigate = useNavigate();
  const period = periodOf(search);
  const query = useQuery(getTrainingOptions({ query: { days: period } }));
  const setPeriod = (value: Period) =>
    navigate({
      to: '/health/training',
      search: { days: value === '90' ? undefined : (value as TrainingSearch['days']) },
      replace: true,
    });
  return (
    <>
      <PageHeader
        title="Training"
        actions={<Segmented label="Period" value={period} onChange={setPeriod} options={PERIODS} />}
      />
      <QueryView query={query} skeleton="h-96 rounded-[18px]">
        {(data) => (data.first_day === null ? <NoData /> : <Content data={data} />)}
      </QueryView>
    </>
  );
}

const number = (value: number | null | undefined, places = 0) =>
  value === null || value === undefined
    ? '–'
    : value.toLocaleString('en-GB', { maximumFractionDigits: places });

const signed = (value: number, places = 0) =>
  `${value > 0 ? '+' : value < 0 ? '−' : ''}${Math.abs(value).toLocaleString('en-GB', {
    maximumFractionDigits: places,
  })}`;

function hoursMinutes(hours: number): string {
  const total = Math.round(hours * 60);
  return `${Math.floor(total / 60)}h ${String(total % 60).padStart(2, '0')}`;
}

const km = (metres: number) =>
  metres === 0
    ? '–'
    : `${(metres / 1000).toLocaleString('en-GB', { maximumFractionDigits: 1 })} km`;

function Content({ data }: { data: Training }) {
  const { summary } = data;
  return (
    <div className="flex flex-col gap-5">
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Figure label="Fitness" value={number(summary.fitness)}>
          {summary.fitness_change !== null && (
            <span
              className={cn(
                'inline-flex items-center gap-1',
                summary.fitness_change > 0 && 'text-good',
              )}
            >
              {summary.fitness_change > 0 && <ArrowUp className="size-3.5" aria-hidden />}
              {signed(summary.fitness_change)} in 6 weeks
            </span>
          )}
        </Figure>
        <Figure label="Fatigue" value={number(summary.fatigue)}>
          7-day load
        </Figure>
        <Figure label="Form" value={summary.form === null ? '–' : signed(summary.form)}>
          {summary.band && BAND_NAMES[summary.band]}
        </Figure>
        <Figure
          label="Ramp"
          value={summary.ramp_per_week === null ? '–' : signed(summary.ramp_per_week, 1)}
          unit="/ week"
        >
          {summary.ramp_safe !== null && (
            <span
              className={cn(
                'inline-flex items-center gap-1',
                summary.ramp_safe ? 'text-good' : 'text-destructive',
              )}
            >
              {summary.ramp_safe ? (
                <Check className="size-3.5" aria-hidden />
              ) : (
                <TriangleAlert className="size-3.5" aria-hidden />
              )}
              {summary.ramp_safe ? 'Safe under 6' : 'Steep, over 6'}
            </span>
          )}
        </Figure>
      </div>

      <Card className="min-w-0 px-(--card-spacing)">
        <Heading title="Fitness, fatigue and form">
          <Legend color="var(--primary)">Fitness (42-day)</Legend>
          <Legend color="var(--muted-foreground)">Fatigue (7-day)</Legend>
          <Legend color="var(--foreground)">Form</Legend>
          <Legend color="var(--surface-2)">Load</Legend>
        </Heading>
        <LoadChart data={data} />
        <div className="flex flex-wrap gap-x-3.5 gap-y-1 text-xs text-muted-foreground">
          <Legend color="color-mix(in oklab, var(--sport-swim) 35%, transparent)">
            Fresh above +5
          </Legend>
          <Legend color="var(--border)">Neutral −10 to +5</Legend>
          <Legend color="color-mix(in oklab, var(--good) 40%, transparent)">
            Optimal −30 to −10
          </Legend>
          <Legend color="color-mix(in oklab, var(--destructive) 40%, transparent)">
            High risk below −30
          </Legend>
        </div>
      </Card>

      <div className="grid gap-5 lg:grid-cols-2">
        <Card className="min-w-0 px-(--card-spacing)">
          <Heading title="Hours per week">
            {data.average_week_hours !== null && (
              <span className="text-[13px]">Average {hoursMinutes(data.average_week_hours)}</span>
            )}
            {SPORTS.filter((s) => data.weeks.some((w) => w[s.key] > 0)).map((s) => (
              <Legend key={s.key} color={s.color}>
                {s.label}
              </Legend>
            ))}
          </Heading>
          {data.weeks.length > 0 ? (
            <WeeksChart data={data} />
          ) : (
            <p className="text-[13px] text-muted-foreground">No whole week yet</p>
          )}
        </Card>
        <Card className="min-w-0 px-(--card-spacing)">
          <Heading title="Intensity">
            {ZONE_GROUPS.map((group) => (
              <Legend key={group.label} color={group.color}>
                {group.label}
              </Legend>
            ))}
          </Heading>
          {data.intensity.length === 0 ? (
            <p className="text-[13px] text-muted-foreground">No heart-rate zones yet</p>
          ) : (
            <ul>
              {data.intensity.map((row) => (
                <IntensityRow key={row.sport} row={row} />
              ))}
            </ul>
          )}
        </Card>
      </div>

      <Card className="min-w-0 px-(--card-spacing)">
        <Heading title="Months" />
        <div className="overflow-x-auto">
          <table className="w-full min-w-[560px] text-[13.5px] tabular-nums">
            <thead>
              <tr className="text-xs text-faint">
                {['Month', 'Swim', 'Bike', 'Run', 'Hours', 'Load', 'Climb', 'Sessions'].map(
                  (head, index) => (
                    <th
                      key={head}
                      scope="col"
                      className={cn(
                        'px-2.5 py-1.5 font-medium',
                        index === 0 ? 'text-left' : 'text-right',
                      )}
                    >
                      {head}
                    </th>
                  ),
                )}
              </tr>
            </thead>
            <tbody>
              {data.months.map((m) => (
                <tr key={m.month} className={cn('border-t', m.partial && 'text-muted-foreground')}>
                  <th scope="row" className="px-2.5 py-2 text-left font-normal">
                    {formatMonth(m.month)}
                    {m.partial && ' (so far)'}
                  </th>
                  <td className="px-2.5 py-2 text-right">{km(m.swim_m)}</td>
                  <td className="px-2.5 py-2 text-right">{km(m.bike_m)}</td>
                  <td className="px-2.5 py-2 text-right">{km(m.run_m)}</td>
                  <td className="px-2.5 py-2 text-right">{hoursMinutes(m.hours)}</td>
                  <td className="px-2.5 py-2 text-right">{number(m.load)}</td>
                  <td className="px-2.5 py-2 text-right">{number(m.climb_m)} m</td>
                  <td className="px-2.5 py-2 text-right">{m.sessions}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  );
}

const SPORT_NAMES: Record<TrainingIntensity['sport'], string> = {
  swim: 'Swim',
  bike: 'Bike',
  run: 'Run',
  strength: 'Strength',
  other: 'Other',
  all: 'All',
};

/** The intensity bars' three groups, on the zone ramp (`--zone-*`), never good or bad. */
const ZONE_GROUPS = [
  { label: 'Z1–2', color: 'var(--zone-2)' },
  { label: 'Z3', color: 'var(--zone-3)' },
  { label: 'Z4–5', color: 'var(--zone-5)' },
] as const;

function IntensityRow({ row }: { row: TrainingIntensity }) {
  const shares = [row.z12_share, row.z3_share, row.z45_share].map((s) => (s ?? 0) * 100);
  const text = shares.map((s) => Math.round(s)).join(' / ');
  const colors = ZONE_GROUPS.map((group) => group.color);
  return (
    <li className="grid grid-cols-[64px_minmax(0,1fr)_88px] items-center gap-3 py-2 text-[13.5px]">
      <span className="font-semibold">{SPORT_NAMES[row.sport]}</span>
      <span className="flex h-3 gap-0.5 overflow-hidden rounded-full" aria-hidden>
        {shares.map((share, index) => (
          <span
            // biome-ignore lint/suspicious/noArrayIndexKey: three fixed zone groups
            key={index}
            style={{ flex: share, background: colors[index] }}
          />
        ))}
      </span>
      <span className="text-right text-muted-foreground tabular-nums">
        <span className="sr-only">Z1–2, Z3, Z4–5 percent: </span>
        {text}
      </span>
    </li>
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

function Legend({ color, children }: { color: string; children: ReactNode }) {
  return (
    <span className="inline-flex items-center gap-1.5">
      <i aria-hidden className="inline-block size-2 rounded-sm" style={{ background: color }} />
      {children}
    </span>
  );
}

function Figure({
  label,
  value,
  unit,
  children,
}: {
  label: string;
  value: string;
  unit?: string;
  children?: ReactNode;
}) {
  return (
    <Card size="sm" className="min-w-0 gap-1 px-(--card-spacing)">
      <p className="text-[13px] text-muted-foreground">{label}</p>
      <p className="text-3xl font-bold tracking-tight tabular-nums">
        {value}
        {unit && value !== '–' && (
          <small className="ml-1 text-base font-semibold text-muted-foreground">{unit}</small>
        )}
      </p>
      <p className="min-h-5 text-[13px] text-muted-foreground">
        {children || (value === '–' ? 'Not enough history' : null)}
      </p>
    </Card>
  );
}
