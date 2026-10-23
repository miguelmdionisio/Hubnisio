import { useQuery } from '@tanstack/react-query';
import { Bar, CartesianGrid, ComposedChart, Line, XAxis, YAxis } from 'recharts';
import { getCashFlowOptions } from '@/api/@tanstack/react-query.gen';
import {
  type ChartConfig,
  ChartContainer,
  ChartLegend,
  ChartLegendContent,
  ChartTooltip,
  ChartTooltipContent,
} from '@/components/ui/chart';
import { formatCompactMoney, formatMoney, formatMonth } from '@/lib/format';
import { useView } from '@/lib/view';
import { cashFlowRows } from './chart-data';
import { Note, Panel } from './panel';

const config = {
  income: { label: 'Income', color: 'var(--chart-2)' },
  spending: { label: 'Spending', color: 'var(--chart-6)' },
  net: { label: 'Net', color: 'var(--foreground)' },
} satisfies ChartConfig;

export function CashFlowCard() {
  const { view } = useView();
  const cashFlow = useQuery(getCashFlowOptions({ query: { months: 12, view } }));
  return (
    <Panel
      title="Income vs spending"
      description="Per month, the last 12 months"
      query={cashFlow}
      skeleton="h-72"
      className="lg:col-span-2"
    >
      {(data) => (
        <>
          <ChartContainer config={config} className="aspect-auto h-72 w-full">
            <ComposedChart data={cashFlowRows(data)}>
              <CartesianGrid vertical={false} />
              <XAxis dataKey="label" tickLine={false} axisLine={false} />
              <YAxis
                width={52}
                tickLine={false}
                axisLine={false}
                tickFormatter={(value) => formatCompactMoney(value, 'EUR')}
              />
              <ChartTooltip
                content={
                  <ChartTooltipContent
                    valueFormatter={(value) => formatMoney(Number(value), 'EUR')}
                    labelFormatter={(_, payload) => formatMonth(String(payload[0]?.payload.month))}
                  />
                }
              />
              <ChartLegend content={<ChartLegendContent />} />
              <Bar dataKey="income" fill="var(--color-income)" radius={[3, 3, 0, 0]} />
              <Bar dataKey="spending" fill="var(--color-spending)" radius={[3, 3, 0, 0]} />
              <Line
                dataKey="net"
                type="monotone"
                stroke="var(--color-net)"
                strokeWidth={2}
                dot={false}
              />
            </ComposedChart>
          </ChartContainer>
          {data.unconverted > 0 && (
            <Note className="mt-2">
              {data.unconverted} {data.unconverted === 1 ? 'transaction is' : 'transactions are'}{' '}
              left out: no exchange rate into euros for their day.
            </Note>
          )}
        </>
      )}
    </Panel>
  );
}
