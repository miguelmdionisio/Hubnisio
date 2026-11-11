import { Area, AreaChart, Bar, BarChart, Line, LineChart, Tooltip, XAxis, YAxis } from 'recharts';
import type { ActivityStreams, SwimLength } from '@/api/types.gen';
import { ChartContainer } from '@/components/ui/chart';
import { formatDistance, formatDuration, formatPace } from '@/lib/format';
import type { Group } from './sport';

const axisText = { fontSize: 11.5, fontWeight: 500, fill: 'var(--faint)' };
const SAMPLES = 16; // values a screen reader hears per chart

type Lane = {
  key: string;
  label: string;
  color: string;
  format: (value: number) => string;
  /** Faster (smaller) is higher: pace. */
  reversed?: boolean;
  area?: boolean;
};

const whole = (value: number) => Math.round(value).toString();

const SPORT_COLOR: Record<Group, string> = {
  swim: 'var(--sport-swim)',
  bike: 'var(--sport-bike)',
  run: 'var(--sport-run)',
  strength: 'var(--sport-strength)',
  other: 'var(--foreground)',
};

/** The series an activity has, in the order they are drawn, for its sport. */
export function lanesFor(group: Group, streams: ActivityStreams): Lane[] {
  const all: Lane[] = [
    {
      key: 'pace',
      label: 'Pace /km',
      color: SPORT_COLOR[group],
      format: formatPace,
      reversed: true,
    },
    {
      key: 'pace100',
      label: 'Pace /100 m',
      color: SPORT_COLOR[group],
      format: formatPace,
      reversed: true,
    },
    {
      key: 'speed',
      label: 'Speed km/h',
      color: SPORT_COLOR[group],
      format: (v) => v.toFixed(1),
    },
    { key: 'heart_rate', label: 'Heart rate', color: 'var(--destructive)', format: whole },
    {
      key: 'altitude',
      label: 'Elevation m',
      color: 'var(--muted-foreground)',
      format: whole,
      area: true,
    },
    { key: 'power', label: 'Power W', color: 'var(--primary)', format: whole },
    { key: 'cadence', label: 'Cadence', color: 'var(--good)', format: whole },
  ];
  return all.filter((lane) => streams.series[lane.key]?.some((v) => v !== null));
}

const axisLabel = (axis: ActivityStreams['axis'], value: number) =>
  axis === 'distance' ? formatDistance(value) : formatDuration(value);

function percentile(sorted: number[], share: number): number {
  return sorted[Math.min(sorted.length - 1, Math.floor(share * (sorted.length - 1)))] ?? 0;
}

/** A range that leaves out the odd spike (a stop, a GPS jump) and pads what is left. */
function rangeOf(values: (number | null)[]): [number, number] {
  const sorted = values.filter((v): v is number => v !== null).sort((a, b) => a - b);
  const lo = percentile(sorted, 0.02);
  const hi = percentile(sorted, 0.98);
  const pad = (hi - lo) * 0.1 || 1;
  return [lo - pad, hi + pad];
}

/** Every Nth sample, for a screen reader. */
function sampled<T>(items: T[], count = SAMPLES): T[] {
  const step = Math.max(1, Math.ceil(items.length / count));
  return items.filter((_, index) => index % step === 0);
}

/**
 * One small chart per series, stacked and sharing the x axis (distance or time); hovering one
 * shows the same point in all. Each series is also listed, sampled, for a screen reader.
 */
export function StreamLanes({ group, streams }: { group: Group; streams: ActivityStreams }) {
  const lanes = lanesFor(group, streams);
  const rows = streams.x.map((x, index) => {
    const row: Record<string, number | null> = { x };
    for (const lane of lanes) row[lane.key] = streams.series[lane.key]?.[index] ?? null;
    return row;
  });
  return (
    <figure className="mt-1">
      {lanes.map((lane, index) => {
        const last = index === lanes.length - 1;
        const [lo, hi] = rangeOf(streams.series[lane.key] ?? []);
        const Chart = lane.area ? AreaChart : LineChart;
        return (
          <div key={lane.key}>
            <p className="text-xs font-medium text-muted-foreground">{lane.label}</p>
            <ChartContainer
              config={{ [lane.key]: { label: lane.label, color: lane.color } }}
              className="aspect-auto w-full"
              style={{ height: last ? 118 : 88 }}
              aria-hidden
            >
              <Chart
                data={rows}
                syncId="activity"
                margin={{ top: 4, right: 0, bottom: 0, left: 0 }}
              >
                <XAxis
                  dataKey="x"
                  type="number"
                  domain={['dataMin', 'dataMax']}
                  hide={!last}
                  tickCount={6}
                  tickFormatter={(v: number) => axisLabel(streams.axis, v)}
                  tickLine={false}
                  axisLine={false}
                  height={22}
                  tick={axisText}
                />
                <YAxis
                  orientation="right"
                  domain={[lo, hi]}
                  reversed={lane.reversed}
                  allowDataOverflow
                  ticks={[Math.ceil(lo), Math.floor(hi)]}
                  tickFormatter={lane.format}
                  tickLine={false}
                  axisLine={false}
                  width={46}
                  tick={axisText}
                />
                <Tooltip
                  isAnimationActive={false}
                  cursor={{ stroke: 'var(--faint)' }}
                  content={({ active, payload }) => {
                    const point = payload?.[0]?.payload as
                      | Record<string, number | null>
                      | undefined;
                    const value = point?.[lane.key];
                    if (!active || !point || value === null || value === undefined) return null;
                    return (
                      <div className="rounded-lg bg-popover px-2.5 py-1.5 text-xs shadow-pop tabular-nums">
                        <span className="text-muted-foreground">
                          {axisLabel(streams.axis, point.x ?? 0)}
                        </span>{' '}
                        <span className="font-semibold">{lane.format(value)}</span>
                      </div>
                    );
                  }}
                />
                {lane.area ? (
                  <Area
                    dataKey={lane.key}
                    type="monotone"
                    stroke={lane.color}
                    strokeWidth={1.5}
                    fill={lane.color}
                    fillOpacity={0.15}
                    dot={false}
                    isAnimationActive={false}
                    connectNulls={false}
                  />
                ) : (
                  <Line
                    dataKey={lane.key}
                    type="monotone"
                    stroke={lane.color}
                    strokeWidth={1.75}
                    dot={false}
                    isAnimationActive={false}
                    connectNulls={false}
                  />
                )}
              </Chart>
            </ChartContainer>
          </div>
        );
      })}
      <figcaption className="sr-only">
        {lanes.map((l) => l.label).join(', ')} by {streams.axis}, a sample of the values
      </figcaption>
      {lanes.map((lane) => (
        <ul key={lane.key} className="sr-only" aria-label={lane.label}>
          {sampled(rows.filter((row) => row[lane.key] !== null)).map((row) => (
            <li key={row.x}>
              {axisLabel(streams.axis, row.x ?? 0)}: {lane.format(row[lane.key] ?? 0)}
            </li>
          ))}
        </ul>
      ))}
    </figure>
  );
}

const SET_COLORS = ['var(--sport-swim)', 'var(--primary)'];

/** SWOLF of each swum length, the bars alternating colour from one set to the next. */
export function SwolfBars({ lengths }: { lengths: SwimLength[] }) {
  const rows = lengths
    .filter((length) => length.swolf !== null)
    .map((length) => ({ ...length, n: length.index + 1 }));
  if (rows.length === 0) return null;
  return (
    <figure className="mt-1">
      <ChartContainer
        config={{ swolf: { label: 'SWOLF', color: 'var(--sport-swim)' } }}
        className="aspect-auto h-36 w-full"
        aria-hidden
      >
        <BarChart data={rows} margin={{ top: 4, right: 0, bottom: 0, left: 0 }}>
          <XAxis
            dataKey="n"
            tickLine={false}
            axisLine={false}
            height={22}
            tick={axisText}
            interval="preserveStartEnd"
          />
          <YAxis
            orientation="right"
            domain={[0, 'dataMax']}
            tickCount={3}
            tickLine={false}
            axisLine={false}
            width={34}
            tick={axisText}
          />
          <Bar
            dataKey="swolf"
            isAnimationActive={false}
            radius={2}
            shape={(props: {
              x?: number;
              y?: number;
              width?: number;
              height?: number;
              payload?: SwimLength;
            }) => (
              <rect
                x={props.x}
                y={props.y}
                width={props.width}
                height={props.height}
                rx={2}
                fill={SET_COLORS[((props.payload?.set_index ?? 1) - 1) % SET_COLORS.length]}
              />
            )}
          />
        </BarChart>
      </ChartContainer>
      <figcaption className="sr-only">SWOLF of each length, by set</figcaption>
      <ul className="sr-only">
        {sampled(rows, 24).map((row) => (
          <li key={row.index}>
            Length {row.n}, set {row.set_index}: SWOLF {row.swolf}
          </li>
        ))}
      </ul>
    </figure>
  );
}
