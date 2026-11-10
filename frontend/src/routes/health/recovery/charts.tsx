import type { ReactNode } from 'react';
import { Area, Bar, BarChart, ComposedChart, Line, ReferenceLine, XAxis, YAxis } from 'recharts';
import type { Recovery } from '@/api/types.gen';
import { ChartContainer } from '@/components/ui/chart';
import { LOCALE, parseDate } from '@/lib/format';

const axisText = { fontSize: 11.5, fontWeight: 500, fill: 'var(--faint)' };
const margin = { top: 8, right: 0, bottom: 0, left: 0 };

export function dayMonth(isoDate: string): string {
  return new Intl.DateTimeFormat(LOCALE, { day: 'numeric', month: 'short' }).format(
    parseDate(isoDate),
  );
}

/** Three labels under a chart: its first day, middle and last. */
function dayTicks(days: string[]): string[] {
  const first = days[0];
  const last = days.at(-1);
  const middle = days[Math.floor(days.length / 2)];
  return first && last && middle ? [first, middle, last] : [];
}

function DayAxis({ days }: { days: string[] }) {
  return (
    <XAxis
      dataKey="day"
      ticks={dayTicks(days)}
      interval={0}
      tickFormatter={dayMonth}
      tickLine={false}
      axisLine={false}
      height={22}
      tick={axisText}
    />
  );
}

/** What a chart tells a screen reader: a caption and the values it draws, gaps left out. */
function Figure({
  caption,
  values,
  children,
}: {
  caption: string;
  values: { day: string; text: string }[];
  children: ReactNode;
}) {
  return (
    <figure className="mt-1">
      {children}
      <figcaption className="sr-only">{caption}</figcaption>
      <ul className="sr-only">
        {values.map((value) => (
          <li key={value.day}>
            {dayMonth(value.day)}: {value.text}
          </li>
        ))}
      </ul>
    </figure>
  );
}

const present = (value: number | null | undefined): value is number =>
  value !== null && value !== undefined;

/** Nightly HRV as dots, below-range nights in `destructive`, the 7-day line and the band. */
export function HrvChart({ data, height = 260 }: { data: Recovery['hrv']; height?: number }) {
  const rows = data.points.map((p) => ({
    ...p,
    base: p.band_low,
    span: present(p.band_low) && present(p.band_high) ? p.band_high - p.band_low : null,
  }));
  const all = rows.flatMap((r) => [r.value, r.avg7, r.band_low, r.band_high]).filter(present);
  const low = Math.floor(Math.min(...all, 100) / 5) * 5 - 5;
  const high = Math.ceil(Math.max(...all, 0) / 5) * 5 + 5;
  return (
    <Figure
      caption="Nightly HRV, its 7-day average and the normal range"
      values={data.points
        .filter((p) => present(p.value))
        .map((p) => ({
          day: p.day,
          text: `${p.value} ms${p.below ? ', below range' : ''}${
            present(p.avg7) ? `, 7-day ${p.avg7}` : ''
          }`,
        }))}
    >
      <ChartContainer
        config={{ avg7: { label: '7-day', color: 'var(--primary)' } }}
        className="aspect-auto w-full"
        style={{ height }}
        aria-hidden
      >
        <ComposedChart data={rows} margin={margin}>
          <DayAxis days={rows.map((r) => r.day)} />
          <YAxis
            orientation="right"
            domain={[low, high]}
            ticks={[low + 5, Math.round((low + high) / 2 / 5) * 5, high - 5]}
            tickFormatter={(v: number) => `${v} ms`}
            tickLine={false}
            axisLine={false}
            width={50}
            tick={axisText}
          />
          <Area
            dataKey="base"
            stackId="band"
            stroke="none"
            fill="none"
            isAnimationActive={false}
            activeDot={false}
            connectNulls={false}
          />
          <Area
            dataKey="span"
            stackId="band"
            stroke="none"
            fill="var(--good)"
            fillOpacity={0.14}
            isAnimationActive={false}
            activeDot={false}
            connectNulls={false}
          />
          <Line
            dataKey="value"
            stroke="none"
            isAnimationActive={false}
            activeDot={false}
            dot={(props: { cx?: number; cy?: number; index?: number }) => {
              const row = rows[props.index ?? -1];
              if (!row || !present(row.value) || props.cx === undefined) {
                return <g key={props.index} />;
              }
              return (
                <circle
                  key={row.day}
                  cx={props.cx}
                  cy={props.cy}
                  r={rows.length > 100 ? 1.6 : 2.6}
                  fill={row.below ? 'var(--destructive)' : 'var(--foreground)'}
                />
              );
            }}
          />
          <Line
            dataKey="avg7"
            stroke="var(--color-avg7)"
            strokeWidth={2.6}
            dot={false}
            activeDot={false}
            connectNulls={false}
            isAnimationActive={false}
          />
        </ComposedChart>
      </ChartContainer>
    </Figure>
  );
}

/** Resting heart rate: each day faintly, the 7-day average on top. */
export function RestingChart({
  data,
  height = 200,
}: {
  data: Recovery['resting_hr'];
  height?: number;
}) {
  const all = data.points.flatMap((p) => [p.value, p.avg7]).filter(present);
  const low = Math.floor(Math.min(...all, 100)) - 1;
  const high = Math.ceil(Math.max(...all, 0)) + 1;
  return (
    <Figure
      caption="Resting heart rate and its 7-day average"
      values={data.points
        .filter((p) => present(p.value))
        .map((p) => ({ day: p.day, text: `${p.value} bpm` }))}
    >
      <ChartContainer
        config={{ avg7: { label: '7-day', color: 'var(--primary)' } }}
        className="aspect-auto w-full"
        style={{ height }}
        aria-hidden
      >
        <ComposedChart data={data.points} margin={margin}>
          <DayAxis days={data.points.map((p) => p.day)} />
          <YAxis
            orientation="right"
            domain={[low, high]}
            ticks={[low + 1, high - 1]}
            tickLine={false}
            axisLine={false}
            width={34}
            tick={axisText}
          />
          <Line
            dataKey="value"
            stroke="var(--faint)"
            strokeWidth={1.4}
            strokeOpacity={0.7}
            dot={false}
            activeDot={false}
            connectNulls={false}
            isAnimationActive={false}
          />
          <Line
            dataKey="avg7"
            stroke="var(--color-avg7)"
            strokeWidth={2.6}
            dot={false}
            activeDot={false}
            connectNulls={false}
            isAnimationActive={false}
          />
        </ComposedChart>
      </ChartContainer>
    </Figure>
  );
}

/** Body Battery charged up from a zero line, drained down from it. */
export function BatteryChart({
  data,
  height = 200,
}: {
  data: Recovery['body_battery'];
  height?: number;
}) {
  const rows = data.points.map((p) => ({
    day: p.day,
    charged: p.charged,
    drained: present(p.drained) ? -p.drained : null,
  }));
  const top = Math.max(...rows.map((r) => Math.max(r.charged ?? 0, -(r.drained ?? 0))), 10);
  return (
    <Figure
      caption="Body Battery charged and drained per day"
      values={data.points
        .filter((p) => present(p.charged) || present(p.drained))
        .map((p) => ({
          day: p.day,
          text: `charged ${p.charged ?? 'no data'}, drained ${p.drained ?? 'no data'}`,
        }))}
    >
      <ChartContainer
        config={{
          charged: { label: 'Charged', color: 'var(--good)' },
          drained: { label: 'Drained', color: 'var(--faint)' },
        }}
        className="aspect-auto w-full"
        style={{ height }}
        aria-hidden
      >
        <BarChart data={rows} margin={margin} stackOffset="sign" barCategoryGap="12%">
          <DayAxis days={rows.map((r) => r.day)} />
          <YAxis domain={[-top, top]} hide />
          <ReferenceLine y={0} stroke="var(--border)" />
          <Bar
            dataKey="charged"
            stackId="b"
            fill="var(--color-charged)"
            radius={2}
            isAnimationActive={false}
            maxBarSize={14}
          />
          <Bar
            dataKey="drained"
            stackId="b"
            fill="var(--color-drained)"
            radius={2}
            isAnimationActive={false}
            maxBarSize={14}
          />
        </BarChart>
      </ChartContainer>
    </Figure>
  );
}

export const STRESS_LEVELS = [
  { key: 'rest_min', label: 'Rest', color: 'var(--chart-2)' },
  { key: 'low_min', label: 'Low', color: 'var(--chart-3)' },
  { key: 'medium_min', label: 'Medium', color: 'var(--chart-6)' },
  { key: 'high_min', label: 'High', color: 'var(--destructive)' },
] as const;

/** Minutes of rest, low, medium and high stress per day, stacked. */
export function StressChart({ data, height = 180 }: { data: Recovery['stress']; height?: number }) {
  const hasAny = (p: Recovery['stress']['points'][number]) =>
    STRESS_LEVELS.some((level) => present(p[level.key]));
  return (
    <Figure
      caption="Minutes of rest, low, medium and high stress per day"
      values={data.points.filter(hasAny).map((p) => ({
        day: p.day,
        text: STRESS_LEVELS.map((level) => `${level.label} ${p[level.key] ?? 0} min`).join(', '),
      }))}
    >
      <ChartContainer
        config={Object.fromEntries(
          STRESS_LEVELS.map((level) => [level.key, { label: level.label, color: level.color }]),
        )}
        className="aspect-auto w-full"
        style={{ height }}
        aria-hidden
      >
        <BarChart data={data.points} margin={margin} barCategoryGap="12%">
          <DayAxis days={data.points.map((p) => p.day)} />
          <YAxis hide />
          {STRESS_LEVELS.map((level) => (
            <Bar
              key={level.key}
              dataKey={level.key}
              stackId="s"
              fill={`var(--color-${level.key})`}
              isAnimationActive={false}
              maxBarSize={16}
            />
          ))}
        </BarChart>
      </ChartContainer>
    </Figure>
  );
}
