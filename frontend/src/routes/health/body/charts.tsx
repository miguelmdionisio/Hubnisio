import type { ReactNode } from 'react';
import { ComposedChart, Line, ReferenceLine, XAxis, YAxis } from 'recharts';
import type { Body } from '@/api/types.gen';
import { ChartContainer } from '@/components/ui/chart';
import { formatDate, parseDate } from '@/lib/format';

const axisText = { fontSize: 11.5, fontWeight: 500, fill: 'var(--faint)' };
const margin = { top: 8, right: 8, bottom: 0, left: 8 };

const time = (isoDate: string) => parseDate(isoDate).getTime();

function Figure({
  caption,
  values,
  children,
}: {
  caption: string;
  values: string[];
  children: ReactNode;
}) {
  return (
    <figure className="mt-1">
      {children}
      <figcaption className="sr-only">{caption}</figcaption>
      <ul className="sr-only">
        {values.map((value) => (
          <li key={value}>{value}</li>
        ))}
      </ul>
    </figure>
  );
}

function TimeAxis({ from, to }: { from: string; to: string }) {
  return (
    <XAxis
      dataKey="t"
      type="number"
      scale="time"
      domain={[time(from), time(to)]}
      ticks={[time(from), time(to)]}
      interval={0}
      tickFormatter={(value: number) => formatDate(new Date(value).toISOString().slice(0, 10))}
      tickLine={false}
      axisLine={false}
      height={22}
      tick={axisText}
    />
  );
}

/** Looks the same on every axis: a little air above and below the values. */
function span(values: number[], pad: number): [number, number] {
  const low = Math.min(...values);
  const high = Math.max(...values);
  return [Math.floor(low - pad), Math.ceil(high + pad)];
}

/** Weigh-ins as dots joined by a line, the goal as a dashed reference line. Two or more only. */
export function WeightChart({ data, height = 240 }: { data: Body; height?: number }) {
  const { points, goal_kg: goal } = data.weight;
  const rows = points.map((p) => ({ t: time(p.day), kg: p.kg }));
  const [low, high] = span([...points.map((p) => p.kg), ...(goal === null ? [] : [goal])], 1);
  const first = points[0]?.day ?? data.last_day;
  const last = points.at(-1)?.day ?? data.last_day;
  return (
    <Figure
      caption="Weigh-ins over time and the weight goal"
      values={[
        ...points.map((p) => `${formatDate(p.day)}: ${p.kg} kg`),
        ...(goal === null ? [] : [`Goal: ${goal} kg`]),
      ]}
    >
      <ChartContainer
        config={{ kg: { label: 'Weight', color: 'var(--primary)' } }}
        className="aspect-auto w-full"
        style={{ height }}
        aria-hidden
      >
        <ComposedChart data={rows} margin={margin}>
          <TimeAxis from={first} to={last} />
          <YAxis
            orientation="right"
            domain={[low, high]}
            tickFormatter={(v: number) => `${v} kg`}
            tickLine={false}
            axisLine={false}
            width={54}
            tick={axisText}
          />
          {goal !== null && (
            <ReferenceLine
              y={goal}
              stroke="var(--good)"
              strokeDasharray="5 4"
              strokeWidth={1.6}
              ifOverflow="extendDomain"
            />
          )}
          <Line
            dataKey="kg"
            stroke="var(--color-kg)"
            strokeWidth={2.4}
            dot={{ r: 3.5, fill: 'var(--color-kg)', stroke: 'none' }}
            activeDot={false}
            isAnimationActive={false}
          />
        </ComposedChart>
      </ChartContainer>
    </Figure>
  );
}

/** Fitness age as a line, the member's real age beneath it dashed. Two or more readings only. */
export function FitnessAgeChart({ data, height = 220 }: { data: Body; height?: number }) {
  const points = data.fitness_age.points.filter((p) => p.fitness_age !== null);
  const rows = points.map((p) => ({
    t: time(p.day),
    fitness: p.fitness_age,
    real: p.chronological_age,
  }));
  const values = points.flatMap((p) => [p.fitness_age, p.chronological_age]).filter(isNumber);
  const [low, high] = span(values, 1);
  const first = points[0]?.day ?? data.last_day;
  const last = points.at(-1)?.day ?? data.last_day;
  return (
    <Figure
      caption="Fitness age against real age over time"
      values={points.map(
        (p) =>
          `${formatDate(p.day)}: fitness age ${p.fitness_age}${
            p.chronological_age === null ? '' : `, real age ${p.chronological_age}`
          }`,
      )}
    >
      <ChartContainer
        config={{
          fitness: { label: 'Fitness age', color: 'var(--primary)' },
          real: { label: 'Real age', color: 'var(--faint)' },
        }}
        className="aspect-auto w-full"
        style={{ height }}
        aria-hidden
      >
        <ComposedChart data={rows} margin={margin}>
          <TimeAxis from={first} to={last} />
          <YAxis
            orientation="right"
            domain={[low, high]}
            allowDecimals={false}
            tickLine={false}
            axisLine={false}
            width={34}
            tick={axisText}
          />
          <Line
            dataKey="real"
            stroke="var(--color-real)"
            strokeWidth={1.6}
            strokeDasharray="5 4"
            dot={false}
            activeDot={false}
            connectNulls
            isAnimationActive={false}
          />
          <Line
            dataKey="fitness"
            stroke="var(--color-fitness)"
            strokeWidth={2.4}
            dot={{ r: 3, fill: 'var(--color-fitness)', stroke: 'none' }}
            activeDot={false}
            connectNulls
            isAnimationActive={false}
          />
        </ComposedChart>
      </ChartContainer>
    </Figure>
  );
}

const isNumber = (value: number | null): value is number => value !== null;
