import { useQuery } from '@tanstack/react-query';
import type { ReactNode } from 'react';
import { Area, AreaChart, XAxis, YAxis } from 'recharts';
import { getNetWorthOptions } from '@/api/@tanstack/react-query.gen';
import {
  type ChartConfig,
  ChartContainer,
  ChartTooltip,
  ChartTooltipContent,
} from '@/components/ui/chart';
import { formatCompactMoney, formatDate, formatMoney, formatShortMonth } from '@/lib/format';
import { cn } from '@/lib/utils';
import { useView } from '@/lib/view';
import { axisTicks, netWorthChange } from '../overview/chart-data';
import { QueryView } from '../overview/panel';
import { Total } from './spending/parts';

const config = { amount: { label: 'Net worth', color: 'var(--primary)' } } satisfies ChartConfig;

/** Net worth now, how it moved in 30 days, and its history. */
export function NetWorth() {
  const { view } = useView();
  const netWorth = useQuery(getNetWorthOptions({ query: { view } }));
  return (
    <section aria-label="Net worth" className="mb-7">
      <QueryView query={netWorth} skeleton="h-72 rounded-[18px]">
        {(data) => {
          const change = netWorthChange(data.points);
          const points = data.points.map((point) => ({
            on: point.on,
            amount: Number(point.amount),
          }));
          return (
            <>
              <Total amount={data.total}>
                {change && (
                  <>
                    <span
                      className={cn(
                        change.amount > 0 && 'text-good',
                        change.amount < 0 && 'text-destructive',
                      )}
                    >
                      {change.amount > 0 ? '+' : change.amount < 0 ? '−' : ''}
                      {formatMoney(Math.abs(change.amount), 'EUR')}
                    </span>
                    <span className="font-medium text-muted-foreground">in {change.days} days</span>
                  </>
                )}
                {data.unconverted > 0 && (
                  <Marker title="Days left out of the history for want of an exchange rate">
                    {data.unconverted} without a rate
                  </Marker>
                )}
                {data.unpriced > 0 && (
                  <Marker title="Holding-days left out of the history for want of a price">
                    {data.unpriced} without a price
                  </Marker>
                )}
              </Total>
              {points.length > 1 && (
                <ChartContainer config={config} className="mt-3.5 aspect-auto h-56 w-full">
                  <AreaChart data={points} margin={{ top: 8, right: 0, bottom: 0, left: 0 }}>
                    <XAxis
                      dataKey="on"
                      ticks={axisTicks(data.points)}
                      interval={0}
                      tickLine={false}
                      axisLine={false}
                      tickMargin={8}
                      tickFormatter={(value) => formatShortMonth(String(value))}
                    />
                    <YAxis
                      orientation="right"
                      width={52}
                      domain={['auto', 'auto']}
                      tickLine={false}
                      axisLine={false}
                      tickCount={3}
                      tickFormatter={(value) => formatCompactMoney(value, 'EUR')}
                    />
                    <ChartTooltip
                      content={
                        <ChartTooltipContent
                          hideIndicator
                          valueFormatter={(value) => formatMoney(Number(value), 'EUR')}
                          labelFormatter={(_, payload) =>
                            formatDate(String(payload[0]?.payload.on))
                          }
                        />
                      }
                    />
                    <Area
                      dataKey="amount"
                      type="monotone"
                      stroke="var(--color-amount)"
                      fill="var(--color-amount)"
                      fillOpacity={0.12}
                      strokeWidth={2.4}
                      dot={false}
                      isAnimationActive={false}
                    />
                  </AreaChart>
                </ChartContainer>
              )}
            </>
          );
        }}
      </QueryView>
    </section>
  );
}

function Marker({ title, children }: { title: string; children: ReactNode }) {
  return (
    <span
      title={title}
      className="rounded-full bg-surface px-2 py-px text-xs font-semibold text-muted-foreground"
    >
      {children}
    </span>
  );
}
