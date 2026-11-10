import type { ReactNode } from 'react';
import {
  Bar,
  BarChart,
  ComposedChart,
  Line,
  LineChart,
  ReferenceArea,
  ReferenceLine,
  XAxis,
  YAxis,
} from 'recharts';
import type { Training } from '@/api/types.gen';
import { ChartContainer } from '@/components/ui/chart';
import { LOCALE, parseDate } from '@/lib/format';

const axisText = { fontSize: 11.5, fontWeight: 500, fill: 'var(--faint)' };
const margin = { top: 8, right: 0, bottom: 0, left: 0 };

export const SPORTS = [
  { key: 'swim', label: 'Swim', color: 'var(--sport-swim)' },
  { key: 'bike', label: 'Bike', color: 'var(--sport-bike)' },
  { key: 'run', label: 'Run', color: 'var(--sport-run)' },
  { key: 'strength', label: 'Strength', color: 'var(--sport-strength)' },
  { key: 'other', label: 'Other', color: 'var(--faint)' },
] as const;

export const BAND_NAMES = {
  fresh: 'Fresh',
  neutral: 'Neutral',
  optimal: 'Optimal',
  high_risk: 'High risk',
} as const;

export function dayMonth(isoDate: string): string {
  return new Intl.DateTimeFormat(LOCALE, { day: 'numeric', month: 'short' }).format(
    parseDate(isoDate),
  );
}

export const hoursText = (hours: number) => `${hours.toFixed(1)} h`;

function dayTicks(days: string[]): string[] {
  const first = days[0];
  const last = days.at(-1);
  const middle = days[Math.floor(days.length / 2)];
  return first && last && middle ? [first, middle, last] : [];
}

function DayAxis({ days, hide }: { days: string[]; hide?: boolean }) {
  return (
    <XAxis
      dataKey="day"
      ticks={dayTicks(days)}
      interval={0}
      tickFormatter={dayMonth}
      tickLine={false}
      axisLine={false}
      height={hide ? 4 : 22}
      tick={hide ? false : axisText}
    />
  );
}

/** What a chart tells a screen reader: a caption and the values it draws. */
function Figure({
  caption,
  values,
  children,
}: {
  caption: string;
  values: { key: string; text: string }[];
  children: ReactNode;
}) {
  return (
    <figure className="mt-1">
      {children}
      <figcaption className="sr-only">{caption}</figcaption>
      <ul className="sr-only">
        {values.map((value) => (
          <li key={value.key}>{value.text}</li>
        ))}
      </ul>
    </figure>
  );
}

/** Fitness and fatigue as lines over the day's load as faint bars; form below it, its bands
 * drawn and named. */
export function LoadChart({ data }: { data: Training }) {
  const points = data.points;
  const days = points.map((p) => p.day);
  const top = Math.max(...points.map((p) => Math.max(p.fitness, p.fatigue)), 10);
  const maxLoad = Math.max(...points.map((p) => p.load), 10);
  const config = {
    fitness: { label: 'Fitness', color: 'var(--primary)' },
    fatigue: { label: 'Fatigue', color: 'var(--muted-foreground)' },
    form: { label: 'Form', color: 'var(--foreground)' },
  };
  return (
    <Figure
      caption="Fitness, fatigue, form and load per day"
      values={points.map((p) => ({
        key: p.day,
        text: `${dayMonth(p.day)}: fitness ${p.fitness}, fatigue ${p.fatigue}, form ${p.form} (${BAND_NAMES[p.band]}), load ${p.load}`,
      }))}
    >
      <ChartContainer config={config} className="aspect-auto h-[220px] w-full" aria-hidden>
        <ComposedChart data={points} margin={margin}>
          <DayAxis days={days} hide />
          <YAxis yAxisId="load" hide domain={[0, maxLoad * 2.4]} />
          <YAxis
            yAxisId="ctl"
            orientation="right"
            domain={[0, Math.ceil(top / 10) * 10 + 10]}
            ticks={[0, Math.ceil(top / 10) * 10]}
            tickLine={false}
            axisLine={false}
            width={34}
            tick={axisText}
          />
          <Bar
            yAxisId="load"
            dataKey="load"
            fill="var(--surface-2)"
            isAnimationActive={false}
            maxBarSize={6}
          />
          <Line
            yAxisId="ctl"
            dataKey="fatigue"
            stroke="var(--color-fatigue)"
            strokeWidth={1.5}
            strokeOpacity={0.8}
            dot={false}
            activeDot={false}
            isAnimationActive={false}
          />
          <Line
            yAxisId="ctl"
            dataKey="fitness"
            stroke="var(--color-fitness)"
            strokeWidth={3}
            dot={false}
            activeDot={false}
            isAnimationActive={false}
          />
        </ComposedChart>
      </ChartContainer>
      <ChartContainer config={config} className="aspect-auto h-[140px] w-full" aria-hidden>
        <LineChart data={points} margin={margin}>
          <DayAxis days={days} />
          <YAxis
            orientation="right"
            domain={[-40, 25]}
            allowDataOverflow
            ticks={[]}
            tickLine={false}
            axisLine={false}
            width={34}
          />
          <ReferenceArea y1={5} y2={25} fill="var(--sport-swim)" fillOpacity={0.1} />
          <ReferenceArea y1={-30} y2={-10} fill="var(--good)" fillOpacity={0.12} />
          <ReferenceArea y1={-40} y2={-30} fill="var(--destructive)" fillOpacity={0.12} />
          <ReferenceLine y={0} stroke="var(--border)" strokeDasharray="3 4" />
          <Line
            dataKey="form"
            stroke="var(--color-form)"
            strokeWidth={2}
            dot={false}
            activeDot={false}
            isAnimationActive={false}
          />
        </LineChart>
      </ChartContainer>
    </Figure>
  );
}

/** Hours per week stacked by sport, the average as a dashed line. */
export function WeeksChart({ data }: { data: Training }) {
  const weeks = data.weeks;
  const average = data.average_week_hours;
  const top = Math.max(...weeks.map((w) => w.swim + w.bike + w.run + w.strength + w.other), 1);
  return (
    <Figure
      caption="Hours per week by sport"
      values={weeks.map((w) => ({
        key: w.week_start,
        text: `Week of ${dayMonth(w.week_start)}${w.partial ? ' (so far)' : ''}: ${SPORTS.map(
          (s) => `${s.label} ${hoursText(w[s.key])}`,
        ).join(', ')}`,
      }))}
    >
      <ChartContainer
        config={Object.fromEntries(SPORTS.map((s) => [s.key, { label: s.label, color: s.color }]))}
        className="aspect-auto h-[230px] w-full"
        aria-hidden
      >
        <BarChart data={weeks} margin={margin} barCategoryGap="14%">
          <XAxis
            dataKey="week_start"
            ticks={dayTicks(weeks.map((w) => w.week_start))}
            interval={0}
            tickFormatter={dayMonth}
            tickLine={false}
            axisLine={false}
            height={22}
            tick={axisText}
          />
          <YAxis hide domain={[0, Math.ceil(top) + 1]} />
          {SPORTS.map((s) => (
            <Bar
              key={s.key}
              dataKey={s.key}
              stackId="h"
              fill={`var(--color-${s.key})`}
              isAnimationActive={false}
              maxBarSize={28}
            />
          ))}
          {average !== null && (
            <ReferenceLine y={average} stroke="var(--faint)" strokeDasharray="4 4" />
          )}
        </BarChart>
      </ChartContainer>
    </Figure>
  );
}
