import {
  Area,
  Bar,
  BarChart,
  Cell,
  ComposedChart,
  Line,
  Pie,
  PieChart,
  ReferenceLine,
  XAxis,
  YAxis,
} from 'recharts';
import type { SpendingDay } from '@/api/types.gen';
import { ChartContainer } from '@/components/ui/chart';
import { formatDay, formatMoney, formatWholeMoney, parseDate } from '@/lib/format';
import { useIsDesktop } from './search';

const eur = (amount: string | number) => formatMoney(amount, 'EUR');
const whole = (amount: number) => formatWholeMoney(amount, 'EUR');
const today = () => {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`;
};

const axisText = { fontSize: 11.5, fontWeight: 500, fill: 'var(--faint)' };

type TickProps = { x?: number | string; y?: number | string; payload?: { value: number } };

/**
 * Spending per day: a bar per day so far, dashed lines at the highest day and the daily
 * average. Picking a bar (or its button in the list for screen readers) selects that day.
 */
export function DayBars({
  days,
  average,
  color = 'var(--foreground)',
  height = 220,
  selected,
  onSelect,
}: {
  days: SpendingDay[];
  average: string;
  color?: string;
  height?: number;
  selected?: string;
  onSelect?: (day: string | undefined) => void;
}) {
  const desktop = useIsDesktop();
  const rows = days.map((day) => ({
    day: day.day,
    n: parseDate(day.day).getDate(),
    amount: day.running === null ? null : Number(day.amount),
  }));
  const max = Math.max(...rows.map((row) => row.amount ?? 0), 0);
  const avg = Number(average);
  const last = rows.length;
  const now = today();
  const shown = (n: number) => desktop || n === 1 || n % 7 === 1 || n === last;
  const ticks = max > 0 ? (Math.abs(max - avg) > max * 0.08 ? [max, avg] : [max]) : [];
  const pick = onSelect ? (day: string) => onSelect(selected === day ? undefined : day) : undefined;
  return (
    <figure className="mt-3.5">
      <ChartContainer
        config={{ amount: { label: 'Spent', color } }}
        className="aspect-auto w-full [&_.recharts-bar-rectangle]:transition-opacity"
        style={{ height }}
        aria-hidden
      >
        <BarChart data={rows} margin={{ top: 10, right: 0, bottom: 0, left: 0 }}>
          <XAxis
            dataKey="n"
            interval={0}
            tickLine={false}
            axisLine={false}
            height={22}
            tick={({ x, y, payload }: TickProps) => {
              const row = rows[(payload?.value ?? 1) - 1];
              if (!row || !shown(row.n)) return <g />;
              const isToday = row.day === now;
              return (
                <text
                  x={x}
                  y={Number(y ?? 0) + 10}
                  textAnchor="middle"
                  {...axisText}
                  fill={isToday ? 'var(--foreground)' : axisText.fill}
                  fontWeight={isToday ? 700 : 500}
                >
                  {row.n}
                </text>
              );
            }}
          />
          <YAxis
            orientation="right"
            domain={[0, max || 1]}
            ticks={ticks}
            tickFormatter={whole}
            tickLine={false}
            axisLine={false}
            width={50}
            tick={axisText}
          />
          {ticks.map((tick) => (
            <ReferenceLine
              key={tick}
              y={tick}
              stroke="var(--faint)"
              strokeDasharray="2 5"
              strokeOpacity={0.7}
            />
          ))}
          <Bar
            dataKey="amount"
            radius={3}
            maxBarSize={22}
            minPointSize={3}
            isAnimationActive={false}
            onClick={pick ? (_, index) => rows[index] && pick(rows[index].day) : undefined}
          >
            {rows.map((row) => (
              <Cell
                key={row.day}
                fill="var(--color-amount)"
                opacity={selected && selected !== row.day ? 0.28 : 1}
                cursor={pick && row.amount ? 'pointer' : undefined}
              />
            ))}
          </Bar>
        </BarChart>
      </ChartContainer>
      <figcaption className="sr-only">Spending per day</figcaption>
      <ul className="sr-only">
        {rows
          .filter((row) => row.amount)
          .map((row) =>
            pick ? (
              <li key={row.day}>
                <button
                  type="button"
                  aria-pressed={selected === row.day}
                  onClick={() => pick(row.day)}
                >
                  {formatDay(row.day)}: {eur(row.amount ?? 0)}
                </button>
              </li>
            ) : (
              <li key={row.day}>
                {formatDay(row.day)}: {eur(row.amount ?? 0)}
              </li>
            ),
          )}
      </ul>
    </figure>
  );
}

/** The month's running total against the month before's, day by day. */
export function RunningTotal({
  days,
  previous,
  color = 'var(--primary)',
}: {
  days: SpendingDay[];
  previous: SpendingDay[];
  color?: string;
}) {
  const length = Math.max(days.length, previous.length);
  const rows = Array.from({ length }, (_, index) => {
    const now = days[index]?.running;
    const before = previous[index]?.running ?? previous.at(-1)?.running;
    return {
      n: index + 1,
      now: now === null || now === undefined ? null : Number(now),
      before: index < previous.length && before ? Number(before) : null,
    };
  });
  const lastIndex = rows.findLastIndex((row) => row.now !== null);
  const end = rows[lastIndex]?.now ?? 0;
  const endBefore = Number(previous.at(-1)?.running ?? 0);
  const top = Math.max(...rows.map((row) => Math.max(row.now ?? 0, row.before ?? 0)), 1) * 1.08;
  const ticks = Math.abs(end - endBefore) > top * 0.07 ? [end, endBefore] : [end];
  return (
    <figure className="mt-3.5">
      <ChartContainer
        config={{ now: { label: 'This month', color }, before: { label: 'Month before' } }}
        className="aspect-auto h-[220px] w-full"
        aria-hidden
      >
        <ComposedChart data={rows} margin={{ top: 8, right: 0, bottom: 0, left: 0 }}>
          <XAxis
            dataKey="n"
            type="number"
            domain={[1, length]}
            ticks={[1, 15, length]}
            tickLine={false}
            axisLine={false}
            height={22}
            tick={axisText}
          />
          <YAxis
            orientation="right"
            domain={[0, top]}
            ticks={ticks}
            tickFormatter={whole}
            tickLine={false}
            axisLine={false}
            width={56}
            tick={axisText}
          />
          <Line
            dataKey="before"
            stroke="var(--faint)"
            strokeWidth={1.8}
            strokeDasharray="5 5"
            dot={false}
            activeDot={false}
            isAnimationActive={false}
          />
          <Area
            dataKey="now"
            stroke="var(--color-now)"
            strokeWidth={2.6}
            fill="var(--color-now)"
            fillOpacity={0.12}
            isAnimationActive={false}
            activeDot={false}
            dot={(props: { cx?: number; cy?: number; index?: number }) =>
              props.index === lastIndex ? (
                <circle
                  key="end"
                  cx={props.cx}
                  cy={props.cy}
                  r={5}
                  fill="var(--color-now)"
                  stroke="var(--background)"
                  strokeWidth={2.5}
                />
              ) : (
                <g key={props.index} />
              )
            }
          />
        </ComposedChart>
      </ChartContainer>
      <figcaption className="sr-only">
        Running total {eur(end)}; the month before {eur(endBefore)}
      </figcaption>
    </figure>
  );
}

export type Slice = { key: string; name: string; amount: number; color: string; href?: () => void };

/** Shares of the month: the biggest four and Others, the total and its change in the middle. */
export function Donut({
  slices,
  center,
  size,
}: {
  slices: Slice[];
  center: React.ReactNode;
  size: number;
}) {
  const shown = slices.filter((slice) => slice.amount > 0);
  return (
    <figure className="mt-5">
      <div className="relative mx-auto" style={{ width: size, height: size }}>
        <PieChart width={size} height={size} aria-hidden>
          <Pie
            data={shown}
            dataKey="amount"
            nameKey="name"
            innerRadius={size / 2 - 21}
            outerRadius={size / 2 - 7}
            startAngle={90}
            endAngle={-270}
            paddingAngle={shown.length > 1 ? 1.5 : 0}
            cornerRadius={2}
            stroke="none"
            isAnimationActive={false}
            onClick={(_, index) => shown[index]?.href?.()}
          >
            {shown.map((slice) => (
              <Cell
                key={slice.key}
                fill={slice.color}
                cursor={slice.href ? 'pointer' : undefined}
              />
            ))}
          </Pie>
        </PieChart>
        <div className="pointer-events-none absolute inset-0 grid place-content-center text-center">
          {center}
        </div>
      </div>
      <figcaption className="mt-3.5 flex flex-wrap justify-center gap-x-4 gap-y-2 text-[13.5px]">
        {shown.map((slice) => {
          const content = (
            <>
              <i className="size-[9px] rounded-[2px]" style={{ background: slice.color }} />
              {slice.name}
              <span className="sr-only">: {eur(slice.amount)}</span>
            </>
          );
          return slice.href ? (
            <button
              key={slice.key}
              type="button"
              onClick={slice.href}
              className="flex items-center gap-1.5 rounded hover:text-primary"
            >
              {content}
            </button>
          ) : (
            <span key={slice.key} className="flex items-center gap-1.5">
              {content}
            </span>
          );
        })}
      </figcaption>
    </figure>
  );
}
