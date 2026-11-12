import {
  Bar,
  BarChart,
  Cell,
  ComposedChart,
  LabelList,
  Line,
  ReferenceLine,
  Scatter,
  ScatterChart,
  XAxis,
  YAxis,
} from 'recharts';
import type {
  CorrelationOut,
  NightOut,
  NightPointOut,
  SeriesPointOut,
  SpreadOut,
  WeekdayScoreOut,
} from '@/api/types.gen';
import { ChartContainer } from '@/components/ui/chart';
import { formatDay, LOCALE, parseDate } from '@/lib/format';
import { edgeTick } from '../edge-tick';
import { clock, hm, STAGE_COLORS, STAGE_NAMES, WEEKDAYS } from './units';

const axisText = { fontSize: 11.5, fontWeight: 500, fill: 'var(--faint)' };

const shortDate = (isoDate: string) =>
  new Intl.DateTimeFormat(LOCALE, { day: 'numeric', month: 'short' }).format(parseDate(isoDate));

/** A short marker where a chart has nothing to draw. */
export function Gap({ children }: { children: string }) {
  return <p className="text-sm text-muted-foreground">{children}</p>;
}

/** Neutral series (an overnight heart rate is not an alarm, nor a verdict), and SpO2 apart from
 * the sleep stages' hues. Shapes tell them apart too: a line, dots, a dashed line. */
export const SERIES = {
  hr: { label: 'Heart rate', color: 'var(--foreground)' },
  hrv: { label: 'HRV', color: 'var(--muted-foreground)' },
  spo2: { label: 'SpO2', color: 'var(--sport-swim)' },
};

type Row = { t: number; hr?: number; hrv?: number; spo2?: number };

function merge(night: NightOut): Row[] {
  const rows = new Map<number, Row>();
  const put = (series: SeriesPointOut[], key: 'hr' | 'hrv' | 'spo2') => {
    for (const point of series) {
      const row = rows.get(point.t) ?? { t: point.t };
      row[key] = point.v;
      rows.set(point.t, row);
    }
  };
  put(night.heart_rate.series, 'hr');
  put(night.hrv.series, 'hrv');
  put(night.spo2.series, 'spo2');
  return [...rows.values()].sort((a, b) => a.t - b.t);
}

/**
 * The night on a time axis from sleep start to sleep end: heart rate as a line, HRV readings
 * as dots, SpO2 as a dashed line on its own scale. Garmin sends no stage timeline.
 */
export function NightChart({ night }: { night: NightOut }) {
  const rows = merge(night);
  const length = Math.max(Math.round(night.in_bed_s / 60), 1);
  const first = ((night.bed_min % 60) + 60) % 60;
  const ticks: number[] = [];
  for (let t = (60 - first) % 60; t <= length; t += 60) ticks.push(t);
  const hasSpo2 = night.spo2.series.length > 0;
  const values = rows.flatMap((row) => [row.hr, row.hrv].filter((v): v is number => v != null));
  if (rows.length === 0) return <Gap>No readings overnight</Gap>;
  const low = Math.floor(Math.min(...values) / 5) * 5 - 5;
  const high = Math.ceil(Math.max(...values) / 5) * 5 + 5;
  return (
    <figure>
      <ChartContainer config={SERIES} className="aspect-auto h-[220px] w-full" aria-hidden>
        <ComposedChart data={rows} margin={{ top: 8, right: 0, bottom: 0, left: 0 }}>
          <XAxis
            dataKey="t"
            type="number"
            domain={[0, length]}
            ticks={ticks}
            tickFormatter={(t: number) => clock(night.bed_min + t)}
            tickLine={false}
            axisLine={false}
            height={22}
            tick={axisText}
            interval="preserveStartEnd"
          />
          <YAxis
            orientation="right"
            domain={[low, high]}
            tickLine={false}
            axisLine={false}
            width={34}
            tick={axisText}
          />
          {hasSpo2 && <YAxis yAxisId="spo2" domain={[80, 100]} hide />}
          <Line
            dataKey="hr"
            stroke="var(--color-hr)"
            strokeWidth={2}
            dot={false}
            connectNulls
            isAnimationActive={false}
          />
          <Line
            dataKey="hrv"
            stroke="none"
            dot={{ r: 3, fill: 'var(--color-hrv)', stroke: 'none' }}
            activeDot={false}
            isAnimationActive={false}
          />
          {hasSpo2 && (
            <Line
              yAxisId="spo2"
              dataKey="spo2"
              stroke="var(--color-spo2)"
              strokeWidth={1.6}
              strokeDasharray="4 4"
              dot={false}
              connectNulls
              isAnimationActive={false}
            />
          )}
        </ComposedChart>
      </ChartContainer>
      <figcaption className="sr-only">Overnight heart rate, HRV and SpO2</figcaption>
      <ul className="sr-only">
        {rows.map((row) => (
          <li key={row.t}>
            {clock(night.bed_min + row.t)}:{row.hr != null && ` heart rate ${row.hr} bpm`}
            {row.hrv != null && ` HRV ${row.hrv} ms`}
            {row.spo2 != null && ` SpO2 ${row.spo2}%`}
          </li>
        ))}
      </ul>
    </figure>
  );
}

export function Legend({ items }: { items: { name: string; color: string }[] }) {
  return (
    <ul className="flex flex-wrap gap-x-3.5 gap-y-1 text-xs text-muted-foreground">
      {items.map((item) => (
        <li key={item.name} className="flex items-center gap-1.5">
          <i className="size-2 rounded-full" style={{ background: item.color }} aria-hidden />
          {item.name}
        </li>
      ))}
    </ul>
  );
}

export const NIGHT_LEGEND = [
  { name: 'Heart rate', color: SERIES.hr.color },
  { name: 'HRV', color: SERIES.hrv.color },
  { name: 'SpO2', color: SERIES.spo2.color },
];

export const STAGE_LEGEND = (['deep', 'light', 'rem', 'awake'] as const).map((stage) => ({
  name: STAGE_NAMES[stage],
  color: STAGE_COLORS[stage],
}));

/** A small line of one overnight series. */
export function Sparkline({
  series,
  color,
  label,
}: {
  series: SeriesPointOut[];
  color: string;
  label: string;
}) {
  return (
    <figure className="my-1.5">
      <ChartContainer
        config={{ v: { label, color } }}
        className="aspect-auto h-[46px] w-full"
        aria-hidden
      >
        <ComposedChart data={series} margin={{ top: 4, right: 2, bottom: 4, left: 2 }}>
          <XAxis dataKey="t" type="number" hide domain={['dataMin', 'dataMax']} />
          <YAxis hide domain={['dataMin - 1', 'dataMax + 1']} />
          <Line
            dataKey="v"
            stroke="var(--color-v)"
            strokeWidth={1.8}
            dot={false}
            isAnimationActive={false}
          />
        </ComposedChart>
      </ChartContainer>
      <figcaption className="sr-only">{label} through the night</figcaption>
    </figure>
  );
}

const hours = (seconds: number | null) => (seconds === null ? null : seconds / 3600);

/** Stages per night as stacked bars against the need; nights without a reading are gaps. */
export function NightsChart({
  points,
  needMinutes,
}: {
  points: NightPointOut[];
  needMinutes: number | null;
}) {
  const rows = points.map((p) => ({
    day: p.day,
    deep: hours(p.deep_s),
    light: hours(p.light_s),
    rem: hours(p.rem_s),
    awake: hours(p.awake_s),
  }));
  const need = needMinutes === null ? null : needMinutes / 60;
  const top = Math.max(
    ...rows.map((r) => (r.deep ?? 0) + (r.light ?? 0) + (r.rem ?? 0) + (r.awake ?? 0)),
    need ?? 0,
    1,
  );
  const ends = [points[0]?.day, points.at(-1)?.day].filter((d): d is string => !!d);
  return (
    <figure>
      <ChartContainer
        config={Object.fromEntries(
          (['deep', 'light', 'rem', 'awake'] as const).map((s) => [
            s,
            { label: STAGE_NAMES[s], color: STAGE_COLORS[s] },
          ]),
        )}
        className="aspect-auto h-[220px] w-full"
        aria-hidden
      >
        <BarChart
          data={rows}
          margin={{ top: 8, right: 0, bottom: 0, left: 0 }}
          barCategoryGap="12%"
        >
          <XAxis
            dataKey="day"
            ticks={ends}
            tickFormatter={shortDate}
            tickLine={false}
            axisLine={false}
            height={22}
            tick={edgeTick}
            interval={0}
          />
          <YAxis
            orientation="right"
            domain={[0, Math.ceil(top)]}
            tickFormatter={(h: number) => `${h}h`}
            tickLine={false}
            axisLine={false}
            width={34}
            tick={axisText}
          />
          {/* Named in the card's key ("Need 8h 00"), not on the line, where it sat on the bars. */}
          {need !== null && <ReferenceLine y={need} stroke="var(--faint)" strokeDasharray="4 4" />}
          {(['deep', 'light', 'rem', 'awake'] as const).map((stage) => (
            <Bar
              key={stage}
              dataKey={stage}
              stackId="night"
              fill={`var(--color-${stage})`}
              isAnimationActive={false}
            />
          ))}
        </BarChart>
      </ChartContainer>
      <figcaption className="sr-only">Sleep stages per night</figcaption>
      <ul className="sr-only">
        {points
          .filter((p) => p.worn && p.slept_s !== null)
          .map((p) => (
            <li key={p.day}>
              {formatDay(p.day)}: slept {hm((p.slept_s ?? 0) / 60)}, deep {hm((p.deep_s ?? 0) / 60)}
              , light {hm((p.light_s ?? 0) / 60)}, REM {hm((p.rem_s ?? 0) / 60)}, awake{' '}
              {hm((p.awake_s ?? 0) / 60)}
            </li>
          ))}
      </ul>
    </figure>
  );
}

/** Bedtime to wake time per night as floating bars, weekend nights lighter. */
export function ScheduleChart({ points, spread }: { points: NightPointOut[]; spread: SpreadOut }) {
  const rows = points.map((p) => ({
    day: p.day,
    range: p.bed_min !== null && p.wake_min !== null ? [p.bed_min, p.wake_min] : null,
    weekend: [5, 6].includes((parseDate(p.day).getDay() + 6) % 7),
  }));
  const beds = points.flatMap((p) => (p.bed_min === null ? [] : [p.bed_min]));
  const wakes = points.flatMap((p) => (p.wake_min === null ? [] : [p.wake_min]));
  const lo = Math.floor((Math.min(...beds) - 20) / 60) * 60;
  const hi = Math.ceil((Math.max(...wakes) + 20) / 60) * 60;
  const ticks: number[] = [];
  for (let t = lo; t <= hi; t += hi - lo > 600 ? 180 : 120) ticks.push(t);
  const ends = [points[0]?.day, points.at(-1)?.day].filter((d): d is string => !!d);
  return (
    <figure>
      <ChartContainer
        config={{ range: { label: 'Asleep', color: 'var(--sleep-light)' } }}
        className="aspect-auto h-[220px] w-full"
        aria-hidden
      >
        <BarChart
          data={rows}
          margin={{ top: 8, right: 0, bottom: 0, left: 0 }}
          barCategoryGap="12%"
        >
          <XAxis
            dataKey="day"
            ticks={ends}
            tickFormatter={shortDate}
            tickLine={false}
            axisLine={false}
            height={22}
            tick={edgeTick}
            interval={0}
          />
          <YAxis
            orientation="right"
            reversed
            domain={[lo, hi]}
            ticks={ticks}
            tickFormatter={clock}
            tickLine={false}
            axisLine={false}
            width={40}
            tick={axisText}
          />
          {spread.bed_avg !== null && (
            <ReferenceLine y={spread.bed_avg} stroke="var(--primary)" strokeDasharray="4 4" />
          )}
          {spread.wake_avg !== null && (
            <ReferenceLine y={spread.wake_avg} stroke="var(--primary)" strokeDasharray="4 4" />
          )}
          <Bar dataKey="range" radius={3} isAnimationActive={false}>
            {rows.map((row) => (
              <Cell key={row.day} fill="var(--color-range)" opacity={row.weekend ? 0.5 : 1} />
            ))}
          </Bar>
        </BarChart>
      </ChartContainer>
      <figcaption className="sr-only">Bedtime and wake time per night</figcaption>
      <ul className="sr-only">
        {points
          .filter((p) => p.bed_min !== null && p.wake_min !== null)
          .map((p) => (
            <li key={p.day}>
              {formatDay(p.day)}: bed {clock(p.bed_min ?? 0)}, up {clock(p.wake_min ?? 0)}
            </li>
          ))}
      </ul>
    </figure>
  );
}

/** Hours slept against the next morning's HRV, with the fitted line. */
export function CorrelationChart({ correlation }: { correlation: CorrelationOut }) {
  const { pairs, slope, intercept } = correlation;
  const xs = pairs.map((p) => p.hours);
  const ys = pairs.map((p) => p.hrv);
  const x0 = Math.floor(Math.min(...xs) * 2) / 2;
  const x1 = Math.ceil(Math.max(...xs) * 2) / 2;
  const y0 = Math.floor(Math.min(...ys) / 5) * 5 - 5;
  const y1 = Math.ceil(Math.max(...ys) / 5) * 5 + 5;
  return (
    <figure>
      <ChartContainer
        config={{ hrv: { label: 'HRV', color: 'var(--sleep-rem)' } }}
        className="aspect-auto h-[220px] w-full"
        aria-hidden
      >
        <ScatterChart margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
          <XAxis
            dataKey="hours"
            type="number"
            domain={[x0, x1]}
            tickFormatter={(h: number) => `${h} h`}
            tickLine={false}
            axisLine={false}
            height={22}
            tick={axisText}
          />
          <YAxis
            dataKey="hrv"
            type="number"
            orientation="right"
            domain={[y0, y1]}
            tickLine={false}
            axisLine={false}
            width={34}
            tick={axisText}
          />
          {slope !== null && intercept !== null && (
            <ReferenceLine
              stroke="var(--primary)"
              strokeWidth={2.5}
              segment={[
                { x: x0, y: intercept + slope * x0 },
                { x: x1, y: intercept + slope * x1 },
              ]}
            />
          )}
          <Scatter
            data={pairs}
            fill="var(--color-hrv)"
            fillOpacity={0.7}
            isAnimationActive={false}
          />
        </ScatterChart>
      </ChartContainer>
      <figcaption className="sr-only">Hours slept against next morning HRV</figcaption>
      <ul className="sr-only">
        {pairs.map((p) => (
          <li key={p.day}>
            {formatDay(p.day)}: {hm(p.hours * 60)} slept, HRV {p.hrv} ms next morning
          </li>
        ))}
      </ul>
    </figure>
  );
}

/** Average score by the weekday the night ends on. */
export function WeekdayChart({ scores }: { scores: WeekdayScoreOut[] }) {
  const rows = scores.map((s) => ({
    name: WEEKDAYS[s.weekday],
    score: s.score === null ? null : Math.round(s.score),
  }));
  return (
    <figure>
      <ChartContainer
        config={{ score: { label: 'Score', color: 'var(--sleep-light)' } }}
        className="aspect-auto h-[200px] w-full"
        aria-hidden
      >
        <BarChart data={rows} margin={{ top: 18, right: 0, bottom: 0, left: 0 }}>
          <XAxis dataKey="name" tickLine={false} axisLine={false} height={22} tick={axisText} />
          <YAxis hide domain={[0, 100]} />
          <Bar
            dataKey="score"
            radius={6}
            maxBarSize={44}
            isAnimationActive={false}
            fill="var(--color-score)"
          >
            <LabelList
              dataKey="score"
              position="top"
              style={{ fill: 'var(--foreground)', fontSize: 12, fontWeight: 600 }}
            />
          </Bar>
        </BarChart>
      </ChartContainer>
      <figcaption className="sr-only">Average sleep score by weekday</figcaption>
      <ul className="sr-only">
        {rows.map((row) => (
          <li key={row.name}>
            {row.name}: {row.score === null ? 'no nights' : row.score}
          </li>
        ))}
      </ul>
    </figure>
  );
}
