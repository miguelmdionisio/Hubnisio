import { useQuery } from '@tanstack/react-query';
import { useNavigate, useSearch } from '@tanstack/react-router';
import { ArrowDown, ArrowUp, Check, Minus, TriangleAlert } from 'lucide-react';
import type { ReactNode } from 'react';
import { getRecoveryOptions } from '@/api/@tanstack/react-query.gen';
import type { Recovery, Signal } from '@/api/types.gen';
import { PageHeader } from '@/components/app-shell';
import { Segmented } from '@/components/segmented';
import { Card } from '@/components/ui/card';
import { cn } from '@/lib/utils';
import { QueryView } from '@/routes/overview/panel';
import { BatteryChart, HrvChart, RestingChart, STRESS_LEVELS, StressChart } from './charts';
import { type Days, daysOf, type RecoverySearch } from './search';

const PERIODS: { value: `${Days}`; label: string }[] = [
  { value: '30', label: '30 days' },
  { value: '90', label: '90 days' },
  { value: '365', label: '1 year' },
];

export function RecoveryPage() {
  const search = useSearch({ from: '/health/recovery' });
  const navigate = useNavigate();
  const days = daysOf(search);
  const query = useQuery(getRecoveryOptions({ query: { days } }));
  const setDays = (value: `${Days}`) =>
    navigate({
      to: '/health/recovery',
      search: { days: value === '90' ? undefined : (Number(value) as RecoverySearch['days']) },
      replace: true,
    });
  return (
    <>
      <PageHeader
        title="Recovery"
        actions={
          <Segmented label="Period" value={`${days}`} onChange={setDays} options={PERIODS} />
        }
      />
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

function hoursMinutes(minutes: number): string {
  const total = Math.round(minutes);
  return `${Math.floor(total / 60)}h ${String(total % 60).padStart(2, '0')}`;
}

/** A short marker for days the watch sent nothing; nothing when there are none. */
function Gaps({ count, unit }: { count: number; unit: 'nights' | 'days' }) {
  if (count === 0) return null;
  return (
    <p className="mt-1.5 text-[13px] text-muted-foreground">
      {count} {count === 1 ? unit.slice(0, -1) : unit} without data
    </p>
  );
}

function Content({ data }: { data: Recovery }) {
  const { hrv, resting_hr: resting, body_battery: battery, stress, signals } = data;
  const hrvGaps = hrv.points.filter((p) => p.value === null).length;
  const rhrGaps = resting.points.filter((p) => p.value === null).length;
  const batteryGaps = battery.points.filter((p) => p.charged === null && p.drained === null).length;
  const stressGaps = stress.points.filter((p) => p.rest_min === null).length;
  return (
    <div className="flex flex-col gap-5">
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <HrvFigure data={hrv.summary} />
        <Figure label="Night-to-night swing" value={number(hrv.summary.swing, 1)} unit="%">
          {hrv.summary.swing_90 !== null && `90-day ${number(hrv.summary.swing_90, 1)}%`}
        </Figure>
        <RestingFigure data={resting.summary} />
        <Figure label="Body Battery at wake" value={number(battery.summary.at_wake)}>
          {battery.summary.charged !== null && `Charged +${number(battery.summary.charged)}`}
        </Figure>
      </div>

      <div className="grid gap-5 lg:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]">
        <Card className="min-w-0 px-(--card-spacing)">
          <Heading title="HRV against your normal">
            <Legend swatch="band">Normal range</Legend>
            <Legend swatch="dot">Night</Legend>
            <Legend swatch="below">Below range</Legend>
            <Legend swatch="line">7-day</Legend>
          </Heading>
          <HrvChart data={hrv} />
          <p className="text-[13px] text-muted-foreground">
            {hrv.summary.band_low === null
              ? 'No normal range yet'
              : `Below range ${hrv.summary.below_nights} ${hrv.summary.below_nights === 1 ? 'night' : 'nights'}`}
          </p>
          <Gaps count={hrvGaps} unit="nights" />
        </Card>
        <SignalsCard signals={signals} />
      </div>

      <div className="grid gap-5 lg:grid-cols-2">
        <Card className="min-w-0 px-(--card-spacing)">
          <Heading title="Resting heart rate">
            {resting.summary.average !== null && (
              <span className="ml-auto text-[13px] text-muted-foreground">
                Average {number(resting.summary.average, 1)}
              </span>
            )}
          </Heading>
          <RestingChart data={resting} />
          <Gaps count={rhrGaps} unit="days" />
        </Card>
        <Card className="min-w-0 px-(--card-spacing)">
          <Heading title="Body Battery">
            <Legend swatch="charged">Charged</Legend>
            <Legend swatch="drained">Drained</Legend>
          </Heading>
          <BatteryChart data={battery} />
          <Gaps count={batteryGaps} unit="days" />
        </Card>
      </div>

      <Card className="min-w-0 px-(--card-spacing)">
        <Heading title="Stress by day">
          {stress.summary.avg !== null && (
            <span className="text-[13px] text-muted-foreground">
              Average {number(stress.summary.avg)} · high {number(stress.summary.high_min)} min a
              day
            </span>
          )}
          {STRESS_LEVELS.map((level) => (
            <Legend key={level.key} color={level.color}>
              {level.label}
            </Legend>
          ))}
        </Heading>
        <StressChart data={stress} />
        <Gaps count={stressGaps} unit="days" />
      </Card>
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

type Swatch = 'band' | 'dot' | 'below' | 'line' | 'charged' | 'drained';

function Legend({
  swatch,
  color,
  children,
}: {
  swatch?: Swatch;
  color?: string;
  children: ReactNode;
}) {
  const style: Record<Swatch, string> = {
    band: 'h-2 w-3 rounded-sm bg-good/25',
    dot: 'size-2 rounded-full bg-foreground',
    below: 'size-2 rounded-full bg-destructive',
    line: 'h-[3px] w-3 rounded-full bg-primary',
    charged: 'size-2 rounded-sm bg-good',
    drained: 'size-2 rounded-sm bg-faint',
  };
  return (
    <span className="inline-flex items-center gap-1.5">
      <i
        aria-hidden
        className={cn('inline-block', swatch ? style[swatch] : 'size-2 rounded-sm')}
        style={color ? { background: color } : undefined}
      />
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
        {children || (value === '–' ? 'No data' : null)}
      </p>
    </Card>
  );
}

function HrvFigure({ data }: { data: Recovery['hrv']['summary'] }) {
  const range = `${number(data.band_low)}–${number(data.band_high)}`;
  return (
    <Figure label="HRV, 7-day" value={number(data.avg7)} unit="ms">
      {data.position === null ? (
        data.avg7 !== null && 'No normal range yet'
      ) : (
        <span
          className={cn(
            'inline-flex items-center gap-1',
            data.position === 'in' ? 'text-good' : 'text-destructive',
          )}
        >
          {data.position === 'below' && <ArrowDown className="size-3.5" aria-hidden />}
          {data.position === 'above' && <ArrowUp className="size-3.5" aria-hidden />}
          {data.position === 'in' ? 'In range' : data.position === 'below' ? 'Below' : 'Above'}{' '}
          {range}
        </span>
      )}
    </Figure>
  );
}

function RestingFigure({ data }: { data: Recovery['resting_hr']['summary'] }) {
  const change = data.change;
  return (
    <Figure label="Resting HR" value={number(data.latest)} unit="bpm">
      {change !== null && (
        <span
          className={cn(
            'inline-flex items-center gap-1',
            change <= 0 ? 'text-good' : change > 3 ? 'text-destructive' : undefined,
          )}
        >
          {change < 0 && <ArrowDown className="size-3.5" aria-hidden />}
          {change > 0 && <ArrowUp className="size-3.5" aria-hidden />}
          {change === 0 ? 'Same as' : number(Math.abs(change), 1)} {change === 0 ? '' : 'vs'} 7-day
        </span>
      )}
    </Figure>
  );
}

const SIGNAL_NAMES: Record<Signal['key'], string> = {
  hrv: 'HRV',
  resting_hr: 'Resting HR',
  sleep: 'Sleep',
  body_battery: 'Body Battery',
  form: 'Form',
};

/** What a signal's value is set against, short: "58 vs 52–66". */
function signalNote(signal: Signal): string {
  if (signal.value === null) return 'No data';
  const value = number(signal.value, 1);
  switch (signal.key) {
    case 'hrv':
      return signal.reference_low === null
        ? `${value} ms, no normal range yet`
        : `${value} vs ${number(signal.reference_low)}–${number(signal.reference_high)} ms`;
    case 'resting_hr':
      return `${value} vs ${number(signal.reference_low, 1)} 7-day`;
    case 'sleep':
      return `${hoursMinutes(signal.value)} of ${hoursMinutes(signal.reference_high ?? 0)} need`;
    case 'body_battery':
      return `${value} at wake, ${number(signal.reference_low)} or more`;
    case 'form':
      return `${value}, ${number(signal.reference_low)} or more`;
  }
}

const STATES = {
  ok: { label: 'OK', icon: Check, tone: 'bg-good text-background' },
  watch: { label: 'Watch', icon: TriangleAlert, tone: 'bg-chart-3 text-background' },
  no_data: { label: 'No data', icon: Minus, tone: 'bg-surface-2 text-muted-foreground' },
} as const;

function SignalsCard({ signals }: { signals: Recovery['signals'] }) {
  return (
    <Card className="min-w-0 px-(--card-spacing)">
      <Heading title="Signals today" />
      <ul className="divide-y">
        {signals.items.map((signal) => {
          const state = STATES[signal.state];
          const Icon = state.icon;
          return (
            <li
              key={signal.key}
              className="grid grid-cols-[28px_minmax(0,1fr)_auto] items-center gap-3 py-2.5"
            >
              <span className={cn('grid size-6 place-items-center rounded-full', state.tone)}>
                <Icon className="size-3.5" strokeWidth={3} aria-hidden />
              </span>
              <span className="min-w-0">
                <span className="block text-sm font-semibold">{SIGNAL_NAMES[signal.key]}</span>
                <span className="block truncate text-[13px] text-muted-foreground">
                  {signalNote(signal)}
                </span>
              </span>
              <span className="text-[13px] font-semibold">{state.label}</span>
            </li>
          );
        })}
      </ul>
      <p className="text-[13px] text-muted-foreground">
        {signals.ok} of {signals.total} OK
      </p>
    </Card>
  );
}
