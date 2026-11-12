/** The props Recharts hands a custom axis tick. */
type TickProps = {
  x?: number;
  y?: number;
  index?: number;
  visibleTicksCount?: number;
  payload?: { value: unknown };
  tickFormatter?: (value: never, index: number) => string;
};

/**
 * An x-axis label that stays inside the chart: the first tick is anchored at its start, the
 * last at its end, the rest centred. For axes whose first and last ticks sit on the plot's
 * edges (the first and last day), so their labels are never cut in half.
 */
export function EdgeTick({
  x = 0,
  y = 0,
  index = 0,
  visibleTicksCount = 1,
  payload,
  tickFormatter,
}: TickProps) {
  const anchor = index === 0 ? 'start' : index === visibleTicksCount - 1 ? 'end' : 'middle';
  const value = payload?.value;
  const text = tickFormatter ? tickFormatter(value as never, index) : String(value ?? '');
  return (
    <text
      x={x}
      y={y}
      dy="0.71em"
      textAnchor={visibleTicksCount === 1 ? 'middle' : anchor}
      fontSize={11.5}
      fontWeight={500}
      fill="var(--faint)"
    >
      {text}
    </text>
  );
}

/** The tick for a day axis: `tick={edgeTick}`. */
export const edgeTick = <EdgeTick />;
