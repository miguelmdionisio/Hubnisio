import { useQuery } from '@tanstack/react-query';
import { Area, AreaChart, CartesianGrid, XAxis, YAxis } from 'recharts';
import { getNetWorthOptions } from '@/api/@tanstack/react-query.gen';
import {
  type ChartConfig,
  ChartContainer,
  ChartTooltip,
  ChartTooltipContent,
} from '@/components/ui/chart';
import { formatCompactMoney, formatDate, formatMoney } from '@/lib/format';
import { useView } from '@/lib/view';
import { axisTicks } from './chart-data';
import { Note, Panel } from './panel';

const config = { amount: { label: 'Net worth', color: 'var(--chart-1)' } } satisfies ChartConfig;

export function NetWorthCard() {
  const { view } = useView();
  const netWorth = useQuery(getNetWorthOptions({ query: { view } }));
  return (
    <Panel
      title="Net worth over time"
      description="The accounts included in net worth, in euros"
      query={netWorth}
      skeleton="h-64"
      className="lg:col-span-2"
    >
      {(data) => {
        if (data.points.length < 2) return <Note>Not enough history yet.</Note>;
        const points = data.points.map((point) => ({ on: point.on, amount: Number(point.amount) }));
        return (
          <>
            <ChartContainer config={config} className="aspect-auto h-64 w-full">
              <AreaChart data={points}>
                <CartesianGrid vertical={false} />
                <XAxis
                  dataKey="on"
                  ticks={axisTicks(data.points)}
                  interval={0}
                  tickLine={false}
                  axisLine={false}
                  tickMargin={8}
                  tickFormatter={(value) => formatDate(String(value))}
                />
                <YAxis
                  width={52}
                  domain={['auto', 'auto']}
                  tickLine={false}
                  axisLine={false}
                  tickFormatter={(value) => formatCompactMoney(value, 'EUR')}
                />
                <ChartTooltip
                  content={
                    <ChartTooltipContent
                      hideIndicator
                      valueFormatter={(value) => formatMoney(Number(value), 'EUR')}
                      labelFormatter={(_, payload) => formatDate(String(payload[0]?.payload.on))}
                    />
                  }
                />
                <Area
                  dataKey="amount"
                  type="monotone"
                  stroke="var(--color-amount)"
                  fill="var(--color-amount)"
                  fillOpacity={0.15}
                  strokeWidth={2}
                  dot={false}
                />
              </AreaChart>
            </ChartContainer>
            {data.unconverted > 0 && (
              <Note className="mt-2">
                {data.unconverted} {data.unconverted === 1 ? 'day is' : 'days are'} left out of the
                accounts' history: no exchange rate into euros.
              </Note>
            )}
            {data.unpriced > 0 && (
              <Note className="mt-2">
                {data.unpriced} {data.unpriced === 1 ? 'holding-day is' : 'holding-days are'} left
                out of investment accounts' history: no price for the day.
              </Note>
            )}
          </>
        );
      }}
    </Panel>
  );
}
