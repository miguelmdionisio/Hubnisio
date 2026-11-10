import { useQuery } from '@tanstack/react-query';
import { useNavigate, useSearch } from '@tanstack/react-router';
import { ArrowDown, ArrowUp } from 'lucide-react';
import type { ReactNode } from 'react';
import { getBodyOptions } from '@/api/@tanstack/react-query.gen';
import type { Body } from '@/api/types.gen';
import { PageHeader } from '@/components/app-shell';
import { Segmented } from '@/components/segmented';
import { Card } from '@/components/ui/card';
import { formatDate } from '@/lib/format';
import { cn } from '@/lib/utils';
import { QueryView } from '@/routes/overview/panel';
import { FitnessAgeChart, WeightChart } from './charts';
import { type BodySearch, type Period, periodOf } from './search';

const PERIODS: { value: Period; label: string }[] = [
  { value: '90', label: '90 days' },
  { value: '365', label: '1 year' },
  { value: 'all', label: 'All' },
];

export function BodyPage() {
  const search = useSearch({ from: '/health/body' });
  const navigate = useNavigate();
  const days = periodOf(search);
  const query = useQuery(getBodyOptions({ query: { days } }));
  const setDays = (value: Period) =>
    navigate({
      to: '/health/body',
      search: { days: value === '365' ? undefined : (value as BodySearch['days']) },
      replace: true,
    });
  return (
    <>
      <PageHeader
        title="Body"
        actions={<Segmented label="Period" value={days} onChange={setDays} options={PERIODS} />}
      />
      <QueryView query={query} skeleton="h-96 rounded-[18px]">
        {(data) => <Content data={data} />}
      </QueryView>
    </>
  );
}

const number = (value: number | null | undefined, places = 1) =>
  value === null || value === undefined
    ? '–'
    : value.toLocaleString('en-GB', { maximumFractionDigits: places });

const signed = (value: number) =>
  `${value > 0 ? '+' : value < 0 ? '−' : ''}${number(Math.abs(value))}`;

/** "No weigh-ins", "1 weigh-in", "2 weigh-ins". */
export function countLabel(count: number, noun: string): string {
  return count === 0 ? `No ${noun}s` : `${count} ${noun}${count === 1 ? '' : 's'}`;
}

function Content({ data }: { data: Body }) {
  const { summary, goal_kg: goal, points } = data.weight;
  const age = data.fitness_age;
  const readings = age.points.filter((p) => p.fitness_age !== null);
  return (
    <div className="flex flex-col gap-5">
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Figure
          label="Latest weight"
          value={number(summary.latest_kg)}
          unit="kg"
          note={summary.latest_day ? formatDate(summary.latest_day) : null}
        />
        <Figure
          label="Change"
          value={summary.change_kg === null ? '–' : signed(summary.change_kg)}
          unit="kg"
        />
        {goal !== null && (
          <Figure
            label="Goal"
            value={number(goal)}
            unit="kg"
            note={
              summary.to_goal_kg === null
                ? null
                : summary.to_goal_kg === 0
                  ? 'Reached'
                  : `${number(Math.abs(summary.to_goal_kg))} ${summary.to_goal_kg > 0 ? 'to lose' : 'under'}`
            }
          />
        )}
        {summary.bmi !== null && <Figure label="BMI" value={number(summary.bmi)} />}
      </div>

      <Card className="min-w-0 px-(--card-spacing)">
        <Heading title="Weight">{goal !== null && <Legend dashed>Goal</Legend>}</Heading>
        {points.length >= 2 && <WeightChart data={data} />}
        <p className="text-[13px] text-muted-foreground">{countLabel(summary.count, 'weigh-in')}</p>
      </Card>

      <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_minmax(0,2fr)]">
        <Card className="min-w-0 gap-3 px-(--card-spacing)">
          <Heading title="Fitness age" />
          {age.latest === null ? (
            <p className="text-[13px] text-muted-foreground">No readings</p>
          ) : (
            <>
              <p className="text-3xl font-bold tracking-tight tabular-nums">
                {number(age.latest.fitness_age)}
                {age.latest.chronological_age !== null && (
                  <small className="ml-1 text-base font-semibold text-muted-foreground">
                    vs {age.latest.chronological_age}
                  </small>
                )}
              </p>
              {age.latest.difference !== null && (
                <p
                  className={cn(
                    'inline-flex items-center gap-1 text-[13px]',
                    age.latest.difference <= 0 ? 'text-good' : 'text-destructive',
                  )}
                >
                  {age.latest.difference < 0 && <ArrowDown className="size-3.5" aria-hidden />}
                  {age.latest.difference > 0 && <ArrowUp className="size-3.5" aria-hidden />}
                  {age.latest.difference === 0
                    ? 'Same as real age'
                    : `${number(Math.abs(age.latest.difference))} ${age.latest.difference < 0 ? 'younger' : 'older'}`}
                </p>
              )}
              <Components latest={age.latest} />
              <p className="text-[13px] text-muted-foreground">{formatDate(age.latest.day)}</p>
            </>
          )}
        </Card>
        <Card className="min-w-0 px-(--card-spacing)">
          <Heading title="Fitness age over time">
            <Legend>Fitness age</Legend>
            <Legend dashed muted>
              Real age
            </Legend>
          </Heading>
          {readings.length >= 2 && <FitnessAgeChart data={data} />}
          <p className="text-[13px] text-muted-foreground">
            {countLabel(readings.length, 'reading')}
          </p>
        </Card>
      </div>
    </div>
  );
}

/** What Garmin stored with the latest reading, where it did. */
function Components({ latest }: { latest: NonNullable<Body['fitness_age']['latest']> }) {
  const items: [string, string][] = [];
  if (latest.resting_hr !== null) items.push(['Resting HR', `${latest.resting_hr} bpm`]);
  if (latest.bmi !== null) items.push(['BMI', number(latest.bmi)]);
  if (latest.vigorous_days_avg !== null) {
    items.push(['Vigorous days', `${number(latest.vigorous_days_avg)} a week`]);
  }
  if (latest.vigorous_minutes_avg !== null) {
    items.push(['Vigorous minutes', `${number(latest.vigorous_minutes_avg, 0)} a week`]);
  }
  if (items.length === 0) return null;
  return (
    <dl className="divide-y text-sm">
      {items.map(([label, value]) => (
        <div key={label} className="flex items-baseline justify-between gap-3 py-1.5">
          <dt className="text-muted-foreground">{label}</dt>
          <dd className="tabular-nums">{value}</dd>
        </div>
      ))}
    </dl>
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
  dashed,
  muted,
  children,
}: {
  dashed?: boolean;
  muted?: boolean;
  children: ReactNode;
}) {
  return (
    <span className="inline-flex items-center gap-1.5">
      <i
        aria-hidden
        className={cn(
          'inline-block w-3.5 border-t-[3px]',
          dashed ? 'border-dashed' : 'rounded-full',
          muted ? 'border-faint' : dashed ? 'border-good' : 'border-primary',
        )}
      />
      {children}
    </span>
  );
}

function Figure({
  label,
  value,
  unit,
  note,
}: {
  label: string;
  value: string;
  unit?: string;
  note?: string | null;
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
        {note || (value === '–' ? 'No data' : null)}
      </p>
    </Card>
  );
}
