import type { ReactNode } from 'react';
import { ComposedChart, Line, XAxis, YAxis } from 'recharts';
import type { Performance } from '@/api/types.gen';
import { ChartContainer } from '@/components/ui/chart';
import { dayMonth } from '@/routes/health/recovery/charts';
import { durationLabel } from './units';

const axisText = { fontSize: 11.5, fontWeight: 500, fill: 'var(--faint)' };
const margin = { top: 8, right: 0, bottom: 0, left: 0 };

type Curve = Performance['run_power']['current'];

const present = (value: number | null | undefined): value is number =>
  value !== null && value !== undefined;

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

const TICKS = [5, 60, 300, 1200, 3600];

/** Best values per duration on a log time axis: this period, last season (dashed), and a
 * model line when there is one. `show` turns a value into the axis' unit (pace: s/km). */
export function CurveChart({
  caption,
  current,
  lastSeason,
  model,
  show = (v) => v,
  format,
  color,
  reversed = false,
  from = 1,
  height = 240,
}: {
  caption: string;
  current: Curve;
  lastSeason: Curve;
  model?: { duration_s: number; value: number }[] | null;
  show?: (value: number) => number;
  format: (value: number) => string;
  color: string;
  reversed?: boolean;
  from?: number;
  height?: number;
}) {
  const byDuration = new Map<
    number,
    { t: number; current?: number; last?: number; model?: number }
  >();
  const row = (t: number) => {
    const found = byDuration.get(t) ?? { t };
    byDuration.set(t, found);
    return found;
  };
  for (const p of current)
    if (p.duration_s >= from && present(p.value)) row(p.duration_s).current = show(p.value);
  for (const p of lastSeason)
    if (p.duration_s >= from && present(p.value)) row(p.duration_s).last = show(p.value);
  for (const p of model ?? []) row(p.duration_s).model = show(p.value);
  const rows = [...byDuration.values()].sort((a, b) => a.t - b.t);
  const values = rows.flatMap((r) => [r.current, r.last, r.model]).filter(present);
  const low = Math.min(...values);
  const high = Math.max(...values);
  const pad = (high - low) * 0.08 || 1;
  const first = rows[0]?.t ?? from;
  const last = rows.at(-1)?.t ?? 3600;
  return (
    <Figure
      caption={caption}
      values={current
        .filter((p) => p.duration_s >= from && present(p.value))
        .map((p) => ({
          key: `${p.duration_s}`,
          text: `${durationLabel(p.duration_s)}: ${format(show(p.value as number))}${
            p.day ? `, ${dayMonth(p.day)}` : ''
          }`,
        }))}
    >
      <ChartContainer
        config={{ current: { label: 'This period', color } }}
        className="aspect-auto w-full"
        style={{ height }}
        aria-hidden
      >
        <ComposedChart data={rows} margin={margin}>
          <XAxis
            dataKey="t"
            type="number"
            scale="log"
            domain={[first, last]}
            ticks={TICKS.filter((t) => t >= first && t <= last)}
            tickFormatter={durationLabel}
            tickLine={false}
            axisLine={false}
            height={22}
            tick={axisText}
          />
          <YAxis
            orientation="right"
            domain={[low - pad, high + pad]}
            reversed={reversed}
            tickCount={4}
            tickFormatter={format}
            tickLine={false}
            axisLine={false}
            width={56}
            tick={axisText}
          />
          <Line
            dataKey="last"
            stroke="var(--faint)"
            strokeDasharray="4 4"
            strokeWidth={1.5}
            dot={false}
            connectNulls
            isAnimationActive={false}
          />
          <Line
            dataKey="model"
            stroke="var(--muted-foreground)"
            strokeDasharray="2 3"
            strokeWidth={1.5}
            dot={false}
            connectNulls
            isAnimationActive={false}
          />
          <Line
            dataKey="current"
            stroke={color}
            strokeWidth={2.5}
            dot={false}
            connectNulls
            isAnimationActive={false}
          />
        </ComposedChart>
      </ChartContainer>
    </Figure>
  );
}

type DayPoint = { key: string; day: string; value: number; line: number | null };

/** Values by day as dots, with a line through them. */
export function DotsChart({
  caption,
  points,
  format,
  color,
  height = 200,
}: {
  caption: string;
  points: DayPoint[];
  format: (value: number) => string;
  color: string;
  height?: number;
}) {
  const rows = points.map((p, index) => ({ ...p, index }));
  const values = rows.flatMap((r) => [r.value, r.line]).filter(present);
  const low = Math.min(...values);
  const high = Math.max(...values);
  const pad = (high - low) * 0.1 || 1;
  const ticks = rows.length > 1 ? [0, rows.length - 1] : [0];
  return (
    <Figure
      caption={caption}
      values={points.map((p) => ({
        key: p.key,
        text: `${dayMonth(p.day)}: ${format(p.value)}${present(p.line) ? `, line ${format(p.line)}` : ''}`,
      }))}
    >
      <ChartContainer
        config={{ value: { label: caption, color } }}
        className="aspect-auto w-full"
        style={{ height }}
        aria-hidden
      >
        <ComposedChart data={rows} margin={margin}>
          <XAxis
            dataKey="index"
            type="number"
            domain={[0, Math.max(rows.length - 1, 1)]}
            ticks={ticks}
            tickFormatter={(i: number) => (rows[i] ? dayMonth(rows[i].day) : '')}
            tickLine={false}
            axisLine={false}
            height={22}
            tick={axisText}
          />
          <YAxis
            orientation="right"
            domain={[low - pad, high + pad]}
            tickCount={4}
            tickFormatter={format}
            tickLine={false}
            axisLine={false}
            width={44}
            tick={axisText}
          />
          <Line
            dataKey="value"
            stroke="none"
            dot={{ r: 3, fill: color, fillOpacity: 0.55, stroke: 'none' }}
            activeDot={false}
            isAnimationActive={false}
          />
          <Line
            dataKey="line"
            stroke="var(--foreground)"
            strokeWidth={2}
            dot={false}
            connectNulls
            isAnimationActive={false}
          />
        </ComposedChart>
      </ChartContainer>
    </Figure>
  );
}
