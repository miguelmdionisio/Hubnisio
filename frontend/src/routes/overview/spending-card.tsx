import { useQuery } from '@tanstack/react-query';
import { Bar, BarChart, CartesianGrid, XAxis, YAxis } from 'recharts';
import { getSpendingOptions } from '@/api/@tanstack/react-query.gen';
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
import { spendingChart } from './chart-data';
import { Note, Panel } from './panel';

export function SpendingCard() {
  const { view } = useView();
  const spending = useQuery(getSpendingOptions({ query: { months: 12, view } }));
  return (
    <Panel
      title="Spending by category"
      description="Per month, the last 12 months"
      query={spending}
      skeleton="h-72"
      className="lg:col-span-2"
    >
      {(data) => {
        const { rows, series } = spendingChart(data);
        if (series.length === 0) return <Note>No spending in the last 12 months.</Note>;
        const config: ChartConfig = Object.fromEntries(
          series.map((item) => [item.key, { label: item.label, color: item.color }]),
        );
        return (
          <>
            <ChartContainer config={config} className="aspect-auto h-72 w-full">
              <BarChart data={rows} stackOffset="sign">
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
                      hideZero
                      valueFormatter={(value) => formatMoney(Number(value), 'EUR')}
                      labelFormatter={(_, payload) =>
                        formatMonth(String(payload[0]?.payload.month))
                      }
                    />
                  }
                />
                <ChartLegend content={<ChartLegendContent />} />
                {series.map((item) => (
                  <Bar
                    key={item.key}
                    dataKey={item.key}
                    stackId="spending"
                    fill={`var(--color-${item.key})`}
                    stroke="var(--card)"
                    strokeWidth={2}
                  />
                ))}
              </BarChart>
            </ChartContainer>
            {data.unconverted > 0 && (
              <Note className="mt-2">
                {data.unconverted} {data.unconverted === 1 ? 'transaction is' : 'transactions are'}{' '}
                left out: no exchange rate into euros for their day.
              </Note>
            )}
          </>
        );
      }}
    </Panel>
  );
}
