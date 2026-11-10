import { useQuery } from '@tanstack/react-query';
import { useNavigate, useSearch } from '@tanstack/react-router';
import { ArrowDown, ArrowUp } from 'lucide-react';
import type { ReactNode } from 'react';
import { getPerformanceOptions } from '@/api/@tanstack/react-query.gen';
import type { Performance } from '@/api/types.gen';
import { PageHeader } from '@/components/app-shell';
import { Segmented } from '@/components/segmented';
import { Card } from '@/components/ui/card';
import { cn } from '@/lib/utils';
import { dayMonth } from '@/routes/health/recovery/charts';
import { QueryView } from '@/routes/overview/panel';
import { CurveChart, DotsChart } from './charts';
import { type PerformancePeriod, periodOf } from './search';
import { clockTime, DISTANCE_NAMES, number, pace, secondsPerKm } from './units';

const PERIODS: { value: PerformancePeriod; label: string }[] = [
  { value: 'season', label: 'This season' },
  { value: '90d', label: 'Last 90 days' },
  { value: 'all', label: 'All time' },
];

export function PerformancePage() {
  const search = useSearch({ from: '/health/performance' });
  const navigate = useNavigate();
  const period = periodOf(search);
  const query = useQuery(getPerformanceOptions({ query: { period } }));
  const setPeriod = (value: PerformancePeriod) =>
    navigate({
      to: '/health/performance',
      search: { period: value === 'season' ? undefined : value },
      replace: true,
    });
  return (
    <>
      <PageHeader
        title="Performance"
        actions={<Segmented label="Period" value={period} onChange={setPeriod} options={PERIODS} />}
      />
      <QueryView query={query} skeleton="h-96 rounded-[18px]">
        {(data) => <Content data={data} />}
      </QueryView>
    </>
  );
}

const RUN = 'var(--sport-run)';
const BIKE = 'var(--sport-bike)';
const PERIOD_NAMES: Record<PerformancePeriod, string> = {
  season: 'This season',
  '90d': 'Last 90 days',
  all: 'All time',
};

function Content({ data }: { data: Performance }) {
  const power = data.run_power.model;
  const speed = data.run_pace.model;
  const swim = data.swim_threshold;
  const vo2 = data.vo2max;
  const hasPower = data.run_power.current.some((p) => p.value !== null);
  const hasPace = data.run_pace.current.some((p) => p.value !== null);
  const periodName = PERIOD_NAMES[data.period];
  return (
    <div className="flex flex-col gap-5">
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Figure
          label="Run critical power"
          value={number(power?.cp)}
          unit="W"
          missing="Too few efforts"
        >
          {power &&
            `W′ ${number(power.w_prime / 1000, 1)} kJ${
              power.cp_per_kg !== null ? ` · ${number(power.cp_per_kg, 1)} W/kg` : ''
            }`}
        </Figure>
        <Figure label="Run VO2max" value={number(vo2.latest, 1)} missing="No recent runs">
          {vo2.change_90d !== null && <Change value={vo2.change_90d} unit="in 90 days" />}
        </Figure>
        <Figure
          label="Threshold run pace"
          value={speed ? pace(speed.pace_per_km_s) : '–'}
          unit="/km"
          missing="Too few efforts"
        >
          {speed && 'Critical speed'}
        </Figure>
        <Figure
          label="Swim threshold"
          value={swim ? pace(swim.pace_per_100_s) : '–'}
          unit="/100 m"
          missing="No 200 m and 400 m"
        >
          {swim && 'From 400 m and 200 m'}
        </Figure>
      </div>

      <div className="grid gap-5 lg:grid-cols-2">
        <Card className="min-w-0 px-(--card-spacing)">
          <Heading title="Run power curve">
            <Legend color={RUN}>{periodName}</Legend>
            <Legend dashed>Last season</Legend>
            {power && <Legend dotted>CP model</Legend>}
          </Heading>
          {hasPower ? (
            <CurveChart
              caption="Best run power per duration"
              current={data.run_power.current}
              lastSeason={data.run_power.last_season}
              model={power?.line}
              format={(v) => `${Math.round(v)} W`}
              color={RUN}
            />
          ) : (
            <Empty>No run power</Empty>
          )}
        </Card>
        <Card className="min-w-0 px-(--card-spacing)">
          <Heading title="Run pace curve">
            <Legend color={RUN}>{periodName}</Legend>
            <Legend dashed>Last season</Legend>
            {speed && <Legend dotted>CS model</Legend>}
          </Heading>
          {hasPace ? (
            <CurveChart
              caption="Best run pace per duration, per km"
              current={data.run_pace.current}
              lastSeason={data.run_pace.last_season}
              model={speed?.line}
              show={secondsPerKm}
              format={pace}
              color={RUN}
              reversed
              from={30}
            />
          ) : (
            <Empty>No runs</Empty>
          )}
        </Card>
      </div>

      <div className="grid gap-5 lg:grid-cols-3">
        <Card className="min-w-0 px-(--card-spacing)">
          <Heading title="Run VO2max">
            <Legend color={RUN}>Per run</Legend>
            <Legend line>42-day best half</Legend>
          </Heading>
          {vo2.points.length ? (
            <DotsChart
              caption="Estimated VO2max per run"
              points={vo2.points.map((p) => ({
                key: `${p.activity_id}`,
                day: p.day,
                value: p.value,
                line: p.line,
              }))}
              format={(v) => number(v, 1)}
              color={RUN}
            />
          ) : (
            <Empty>No runs</Empty>
          )}
        </Card>
        <PredictionsCard data={data.predictions} />
        <EfficiencyCard data={data.efficiency} />
      </div>

      <BikeCard data={data.bike} periodName={periodName} />
      <RecordsCard data={data.records} compare={data.period !== 'all'} />
    </div>
  );
}

function Change({ value, unit }: { value: number; unit: string }) {
  return (
    <span
      className={cn(
        'inline-flex items-center gap-1',
        value > 0 ? 'text-good' : value < 0 ? 'text-destructive' : undefined,
      )}
    >
      {value > 0 && <ArrowUp className="size-3.5" aria-hidden />}
      {value < 0 && <ArrowDown className="size-3.5" aria-hidden />}
      {value === 0 ? 'Same' : number(Math.abs(value), 1)} {unit}
    </span>
  );
}

function PredictionsCard({ data }: { data: Performance['predictions'] }) {
  const shape = data.shape;
  const half = data.items.find((i) => i.distance_m === 21097);
  const source = data.riegel_from;
  const any = data.items.some((i) => i.vdot_s !== null || i.riegel_s !== null);
  return (
    <Card className="min-w-0 px-(--card-spacing)">
      <Heading title="Race predictions">
        <span className="rounded-full bg-surface-2 px-2 py-0.5 font-semibold">Estimate</span>
      </Heading>
      {any ? (
        <>
          <table className="w-full text-[13.5px] tabular-nums">
            <thead className="text-xs text-muted-foreground">
              <tr>
                <th className="py-1 text-left font-medium">
                  <span className="sr-only">Distance</span>
                </th>
                <th className="py-1 text-right font-medium">VO2max</th>
                <th className="py-1 text-right font-medium">Riegel</th>
              </tr>
            </thead>
            <tbody>
              {data.items.map((item) => (
                <tr key={item.distance_m}>
                  <th scope="row" className="py-1.5 text-left font-normal text-muted-foreground">
                    {DISTANCE_NAMES[String(item.distance_m)]}
                  </th>
                  <td className="py-1.5 text-right">
                    {item.vdot_s === null ? (
                      '–'
                    ) : (
                      <>
                        <b className="font-semibold">{clockTime(item.vdot_s)}</b>
                        <span className="ml-1.5 text-xs text-muted-foreground">
                          {pace(item.vdot_s / (item.distance_m / 1000))}
                        </span>
                        {item.slowed && <span className="sr-only">, slowed by shape</span>}
                      </>
                    )}
                  </td>
                  <td className="py-1.5 text-right">
                    {item.riegel_s === null ? '–' : clockTime(item.riegel_s)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {source && (
            <p className="text-xs text-muted-foreground">
              Riegel from {DISTANCE_NAMES[String(source.distance_m)]} {clockTime(source.seconds)},{' '}
              {dayMonth(source.day)}
            </p>
          )}
          {shape && (
            <div className="mt-1">
              <div className="flex items-baseline justify-between text-[13.5px]">
                <span className="text-muted-foreground">Marathon shape</span>
                <b className="font-semibold tabular-nums">{number(shape.score * 100)}%</b>
              </div>
              <div className="my-1.5 h-2.5 overflow-hidden rounded-full bg-surface-2" aria-hidden>
                <div
                  className="h-full rounded-full bg-primary"
                  style={{ width: `${Math.min(shape.score, 1) * 100}%` }}
                />
              </div>
              <p className="text-xs text-muted-foreground">
                {half && `Half needs ${number(half.needs * 100)}%`} · weekly{' '}
                {number(shape.weekly_km)} of {number(shape.weekly_target_km)} km · long runs{' '}
                {shape.long_runs}
              </p>
            </div>
          )}
        </>
      ) : (
        <Empty>No runs</Empty>
      )}
    </Card>
  );
}

function EfficiencyCard({ data }: { data: Performance['efficiency'] }) {
  const trend = data.trend;
  const first = data.points[0];
  const last = data.points.at(-1);
  return (
    <Card className="min-w-0 px-(--card-spacing)">
      <Heading title="Easy-run efficiency">
        <span>m/min per bpm</span>
      </Heading>
      {data.points.length ? (
        <DotsChart
          caption="Efficiency factor per easy run, with its trend"
          points={data.points.map((p) => ({
            key: `${p.activity_id}`,
            day: p.day,
            value: p.value,
            line: trend && p === first ? trend.start : trend && p === last ? trend.end : null,
          }))}
          format={(v) => number(v, 2)}
          color={RUN}
        />
      ) : (
        <Empty>No easy runs</Empty>
      )}
      {data.change_6m_pct !== null && (
        <p className="text-[13px]">
          <Change value={data.change_6m_pct} unit="% in 6 months" />
        </p>
      )}
    </Card>
  );
}

function BikeCard({ data, periodName }: { data: Performance['bike']; periodName: string }) {
  const hasHr = data.hr_curve.current.some((p) => p.value !== null);
  const power = data.power_curve;
  return (
    <Card className="min-w-0 px-(--card-spacing)">
      <Heading title="Bike">
        <Legend color={BIKE}>{periodName}</Legend>
        <Legend dashed>Last season</Legend>
      </Heading>
      <div className="grid gap-5 lg:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
        <div className="min-w-0">
          <h3 className="text-[13px] text-muted-foreground">Heart-rate curve</h3>
          {hasHr ? (
            <CurveChart
              caption="Best ride heart rate per duration"
              current={data.hr_curve.current}
              lastSeason={data.hr_curve.last_season}
              format={(v) => `${Math.round(v)} bpm`}
              color={BIKE}
              height={200}
            />
          ) : (
            <Empty>No rides with heart rate</Empty>
          )}
          {power && (
            <>
              <h3 className="mt-3 text-[13px] text-muted-foreground">Power curve</h3>
              <CurveChart
                caption="Best ride power per duration"
                current={power.current}
                lastSeason={power.last_season}
                format={(v) => `${Math.round(v)} W`}
                color={BIKE}
                height={200}
              />
            </>
          )}
        </div>
        <div className="min-w-0">
          <h3 className="text-[13px] text-muted-foreground">Best climbs</h3>
          {data.climbs.length ? (
            <ul className="divide-y">
              {data.climbs.map((climb) => (
                <li
                  key={`${climb.activity_id}-${climb.vam}`}
                  className="flex items-baseline gap-3 py-2 text-[13.5px] tabular-nums"
                >
                  <b className="font-semibold">{number(climb.vam)} m/h</b>
                  <span className="flex-1 text-muted-foreground">
                    {number(climb.distance_m / 1000, 1)} km · {number(climb.gain_m)} m ·{' '}
                    {number(climb.grade * 100, 1)}%
                  </span>
                  <span className="text-muted-foreground">{dayMonth(climb.day)}</span>
                </li>
              ))}
            </ul>
          ) : (
            <Empty>No climbs</Empty>
          )}
        </div>
      </div>
    </Card>
  );
}

type RecordRow = Performance['records']['run'][number];

const BIKE_NAMES: Record<string, string> = {
  longest: 'Longest ride',
  climbing: 'Most climbing',
  speed_1200: '20 min',
  speed_3600: '60 min',
};

function bikeValue(key: string, value: number): string {
  if (key === 'longest') return `${number(value / 1000, 1)} km`;
  if (key === 'climbing') return `${number(value)} m`;
  return `${number(value * 3.6, 1)} km/h`;
}

function RecordsCard({ data, compare }: { data: Performance['records']; compare: boolean }) {
  const time = (_key: string, value: number) => clockTime(value);
  return (
    <Card className="min-w-0 px-(--card-spacing)">
      <Heading title="Records">{compare && <span>All-time in brackets</span>}</Heading>
      <div className="grid gap-5 md:grid-cols-3">
        <RecordColumn
          title="Run"
          rows={data.run}
          name={(key) => DISTANCE_NAMES[key] ?? key}
          show={time}
        />
        <RecordColumn
          title="Bike"
          rows={data.bike}
          name={(key) => BIKE_NAMES[key] ?? key}
          show={bikeValue}
        />
        <div className="min-w-0">
          <RecordColumn
            title="Swim"
            rows={data.swim}
            name={(key) => DISTANCE_NAMES[key] ?? key}
            show={time}
          />
          <h3 className="mt-3 text-[13px] font-semibold">Triathlon</h3>
          {data.triathlon.length ? (
            <ul>
              {data.triathlon.map((tri) => (
                <li
                  key={tri.activity_id}
                  className="flex items-baseline gap-2.5 py-1.5 text-[13.5px] tabular-nums"
                >
                  <span className="min-w-0 flex-1 truncate text-muted-foreground">
                    {tri.name ?? 'Multisport'}
                  </span>
                  <b className="font-semibold">
                    {tri.duration_s === null ? '–' : clockTime(tri.duration_s)}
                  </b>
                  <span className="text-xs text-muted-foreground">{dayMonth(tri.day)}</span>
                </li>
              ))}
            </ul>
          ) : (
            <p className="py-1.5 text-[13.5px] text-muted-foreground">–</p>
          )}
        </div>
      </div>
    </Card>
  );
}

function RecordColumn({
  title,
  rows,
  name,
  show,
}: {
  title: string;
  rows: RecordRow[];
  name: (key: string) => string;
  show: (key: string, value: number) => string;
}) {
  return (
    <div className="min-w-0">
      <h3 className="text-[13px] font-semibold">{title}</h3>
      <ul>
        {rows.map((row) => (
          <li
            key={row.key}
            className="flex items-baseline gap-2.5 py-1.5 text-[13.5px] tabular-nums"
          >
            <span className="min-w-0 flex-1 truncate text-muted-foreground">
              {name(row.key)}
              {row.venue && (
                <span className="ml-1.5 text-xs">
                  {row.venue === 'pool' ? 'pool' : 'open water'}
                </span>
              )}
            </span>
            <b className="font-semibold">{row.value === null ? '–' : show(row.key, row.value)}</b>
            {typeof row.all_time === 'number' ? (
              <span className="text-xs text-muted-foreground">({show(row.key, row.all_time)})</span>
            ) : (
              row.day && <span className="text-xs text-muted-foreground">{dayMonth(row.day)}</span>
            )}
          </li>
        ))}
      </ul>
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

function Legend({
  color,
  dashed,
  dotted,
  line,
  children,
}: {
  color?: string;
  dashed?: boolean;
  dotted?: boolean;
  line?: boolean;
  children: ReactNode;
}) {
  return (
    <span className="inline-flex items-center gap-1.5">
      <i
        aria-hidden
        className={cn(
          'inline-block',
          dashed
            ? 'w-3 border-t-[1.5px] border-dashed border-faint'
            : dotted
              ? 'w-3 border-t-[1.5px] border-dotted border-muted-foreground'
              : line
                ? 'h-[3px] w-3 rounded-full bg-foreground'
                : 'size-2 rounded-full',
        )}
        style={color ? { background: color } : undefined}
      />
      {children}
    </span>
  );
}

function Empty({ children }: { children: ReactNode }) {
  return <p className="py-6 text-[13px] text-muted-foreground">{children}</p>;
}

function Figure({
  label,
  value,
  unit,
  missing,
  children,
}: {
  label: string;
  value: string;
  unit?: string;
  missing: string;
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
        {value === '–' ? missing : children}
      </p>
    </Card>
  );
}
