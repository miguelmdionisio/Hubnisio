import type { ReactNode } from 'react';
import { Bar, BarChart, ComposedChart, Line, ReferenceLine, XAxis, YAxis } from 'recharts';
import type { TrainingPoint, WeekSummary } from '@/api/types.gen';
import { ChartContainer } from '@/components/ui/chart';
import { LOCALE, parseDate } from '@/lib/format';
import { BAND_NAMES, dayMonth, FormChart, hoursText, SPORTS } from '../training/charts';

const axisText = { fontSize: 11.5, fontWeight: 500, fill: 'var(--faint)' };
const margin = { top: 8, right: 0, bottom: 0, left: 0 };

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

/** Fitness in the accent and fatigue muted; below them form, drawn as on Training (`FormChart`). */
export function FitnessChart({ points }: { points: TrainingPoint[] }) {
  const top = Math.max(...points.map((p) => Math.max(p.fitness, p.fatigue)), 10);
  const ceiling = Math.ceil(top / 10) * 10;
  const ticks = [points[0]?.day, points[Math.floor(points.length / 2)]?.day, points.at(-1)?.day];
  return (
    <Figure
      caption="Fitness, fatigue and form over 90 days"
      values={points.map((p) => ({
        key: p.day,
        text: `${dayMonth(p.day)}: fitness ${p.fitness}, fatigue ${p.fatigue}, form ${p.form} (${BAND_NAMES[p.band]})`,
      }))}
    >
      <ChartContainer
        config={{
          fitness: { label: 'Fitness', color: 'var(--primary)' },
          fatigue: { label: 'Fatigue', color: 'var(--muted-foreground)' },
        }}
        className="aspect-auto h-[150px] w-full"
        aria-hidden
      >
        <ComposedChart data={points} margin={margin}>
          <XAxis
            dataKey="day"
            ticks={ticks.filter((t): t is string => !!t)}
            interval={0}
            tickFormatter={dayMonth}
            tickLine={false}
            axisLine={false}
            height={4}
            tick={false}
          />
          <YAxis
            yAxisId="ctl"
            orientation="right"
            domain={[0, ceiling + 10]}
            ticks={[0, ceiling]}
            tickLine={false}
            axisLine={false}
            width={34}
            tick={axisText}
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
      <FormChart points={points} height={90} />
    </Figure>
  );
}

const weekday = (isoDate: string) =>
  new Intl.DateTimeFormat(LOCALE, { weekday: 'short' }).format(parseDate(isoDate));

/** The last 7 days: hours stacked by sport, the daily average dashed. */
export function WeekChart({ week }: { week: WeekSummary }) {
  const top = Math.max(...week.days.map((d) => d.swim + d.bike + d.run + d.strength + d.other), 1);
  return (
    <Figure
      caption="Hours per day by sport over the last 7 days"
      values={week.days.map((d) => {
        const parts = SPORTS.filter((s) => d[s.key] > 0).map(
          (s) => `${s.label} ${hoursText(d[s.key])}`,
        );
        return {
          key: d.day,
          text: `${weekday(d.day)} ${dayMonth(d.day)}: ${parts.length ? parts.join(', ') : 'no activity'}`,
        };
      })}
    >
      <ChartContainer
        config={Object.fromEntries(SPORTS.map((s) => [s.key, { label: s.label, color: s.color }]))}
        className="aspect-auto h-[170px] w-full"
        aria-hidden
      >
        <BarChart data={week.days} margin={margin} barCategoryGap="22%">
          <XAxis
            dataKey="day"
            tickFormatter={(d: string) => weekday(d).slice(0, 3)}
            tickLine={false}
            axisLine={false}
            height={22}
            tick={axisText}
          />
          <YAxis hide domain={[0, Math.ceil(top) + 0.5]} />
          {SPORTS.map((s) => (
            <Bar
              key={s.key}
              dataKey={s.key}
              stackId="h"
              fill={`var(--color-${s.key})`}
              isAnimationActive={false}
              maxBarSize={34}
            />
          ))}
          <ReferenceLine y={week.average_hours} stroke="var(--faint)" strokeDasharray="4 4" />
        </BarChart>
      </ChartContainer>
    </Figure>
  );
}
