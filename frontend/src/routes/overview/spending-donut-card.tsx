import { useQuery } from '@tanstack/react-query';
import { Link } from '@tanstack/react-router';
import { ArrowLeft, ArrowUpRight, ChevronLeft, ChevronRight } from 'lucide-react';
import { useState } from 'react';
import { Pie, PieChart } from 'recharts';
import { getSpendingOptions } from '@/api/@tanstack/react-query.gen';
import type { Spending } from '@/api/types.gen';
import { Button } from '@/components/ui/button';
import {
  type ChartConfig,
  ChartContainer,
  ChartTooltip,
  ChartTooltipContent,
} from '@/components/ui/chart';
import { formatMoney, formatMonth } from '@/lib/format';
import { currentMonth, monthStart, shiftMonth } from '@/lib/months';
import type { TransactionSearch } from '../finance/transactions';
import { type DonutSlice, donutSlices, OTHER } from './chart-data';
import { Note, Panel } from './panel';

const eur = (amount: number) => formatMoney(amount, 'EUR');

/** The last day of a month ("YYYY-MM") as a date: the Transactions page's `to`. */
function monthEnd(month: string): string {
  const [year = 1970, number = 1] = month.split('-').map(Number);
  return `${month}-${String(new Date(year, number, 0).getDate()).padStart(2, '0')}`;
}

/** The transactions behind a slice in `month`; none for "Other", which is many groups. */
function transactionsOf(slice: DonutSlice, month: string): TransactionSearch | null {
  const range = { from: monthStart(month), to: monthEnd(month) };
  if (slice.kind === 'uncategorized') {
    return { category: 'uncategorized', kind: 'expense', ...range };
  }
  // A group's filter includes its categories, so "no subcategory" shows the whole group.
  return slice.id ? { category: slice.id, ...range } : null;
}

function percent(share: number): string {
  const rounded = Math.round(share * 100);
  return rounded === 0 && share > 0 ? '<1%' : `${rounded}%`;
}

export function SpendingDonutCard() {
  const [month, setMonth] = useState(currentMonth);
  const [path, setPath] = useState<string[]>([]); // what has been drilled into, outermost first
  const spending = useQuery(getSpendingOptions({ query: { months: 1, until: monthStart(month) } }));
  const goTo = (next: string) => {
    setMonth(next);
    setPath([]);
  };
  return (
    <Panel
      title="Spending breakdown"
      description={formatMonth(month)}
      query={spending}
      skeleton="h-72"
      action={
        <div className="flex gap-1">
          <Button
            variant="ghost"
            size="icon-sm"
            aria-label="Previous month"
            onClick={() => goTo(shiftMonth(month, -1))}
          >
            <ChevronLeft aria-hidden />
          </Button>
          <Button
            variant="ghost"
            size="icon-sm"
            aria-label="Next month"
            disabled={month >= currentMonth()}
            onClick={() => goTo(shiftMonth(month, 1))}
          >
            <ChevronRight aria-hidden />
          </Button>
        </div>
      }
    >
      {(data) => <Breakdown data={data} month={month} path={path} onPath={setPath} />}
    </Panel>
  );
}

function Breakdown({
  data,
  month,
  path,
  onPath,
}: {
  data: Spending;
  month: string;
  path: string[];
  onPath: (path: string[]) => void;
}) {
  const scope = path.at(-1);
  const { slices, total, leftOut } = donutSlices(data, scope);
  const scopeName =
    scope === OTHER ? 'Other' : data.groups.find((group) => group.id === scope)?.name;
  const drill = (slice: DonutSlice | undefined) => {
    if (slice?.into) onPath([...path, slice.into]);
  };

  const config: ChartConfig = Object.fromEntries(
    slices.map((slice) => [slice.key, { label: slice.label, color: slice.color }]),
  );
  const rows = slices.map((slice) => ({
    key: slice.key,
    amount: slice.amount,
    fill: `var(--color-${slice.key})`,
  }));

  return (
    <div className="space-y-3">
      {scopeName && (
        <div className="flex items-center gap-2">
          <Button variant="ghost" size="sm" onClick={() => onPath(path.slice(0, -1))}>
            <ArrowLeft aria-hidden />
            Back
          </Button>
          <span className="truncate text-sm font-medium">{scopeName}</span>
        </div>
      )}

      {slices.length === 0 ? (
        <Note>No spending to chart in {formatMonth(month)}.</Note>
      ) : (
        <>
          <div className="relative mx-auto w-full max-w-56">
            <ChartContainer config={config} className="aspect-square w-full">
              <PieChart>
                <ChartTooltip
                  content={
                    <ChartTooltipContent
                      hideLabel
                      nameKey="key"
                      valueFormatter={(value) => eur(Number(value))}
                    />
                  }
                />
                <Pie
                  data={rows}
                  dataKey="amount"
                  nameKey="key"
                  innerRadius="62%"
                  outerRadius="100%"
                  startAngle={90}
                  endAngle={-270}
                  isAnimationActive={false}
                  onClick={(_, index) => drill(slices[index])}
                />
              </PieChart>
            </ChartContainer>
            <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center text-center">
              <span className="max-w-[55%] truncate text-xs text-muted-foreground">
                {scopeName ?? 'Spent'}
              </span>
              <span className="text-lg font-semibold tabular-nums">{eur(total)}</span>
            </div>
          </div>

          <ul className="space-y-0.5">
            {slices.map((slice) => (
              <SliceRow
                key={slice.key}
                slice={slice}
                search={transactionsOf(slice, month)}
                onDrill={() => drill(slice)}
              />
            ))}
          </ul>
        </>
      )}

      {leftOut.length > 0 && (
        <Note>
          Left out of the chart, as refunds are above spending:{' '}
          {leftOut.map((item) => `${item.label} (${eur(item.amount)})`).join(', ')}.
        </Note>
      )}
      {data.unconverted > 0 && (
        <Note>
          {data.unconverted} {data.unconverted === 1 ? 'transaction is' : 'transactions are'} left
          out: no exchange rate into euros for their day.
        </Note>
      )}
    </div>
  );
}

function SliceRow({
  slice,
  search,
  onDrill,
}: {
  slice: DonutSlice;
  search: TransactionSearch | null;
  onDrill: () => void;
}) {
  const content = (
    <>
      <span
        className="size-2.5 shrink-0 rounded-full"
        style={{ backgroundColor: slice.color }}
        aria-hidden
      />
      <span className="min-w-0 flex-1 truncate">{slice.label}</span>
      <span className="shrink-0 tabular-nums">{eur(slice.amount)}</span>
      <span className="w-9 shrink-0 text-right text-xs text-muted-foreground tabular-nums">
        {percent(slice.share)}
      </span>
    </>
  );
  const row = 'flex min-w-0 flex-1 items-center gap-2 rounded-md px-1.5 py-1 text-sm';
  return (
    <li className="flex items-center gap-1">
      {slice.into ? (
        <button
          type="button"
          className={`${row} text-left hover:bg-muted focus-visible:ring-3 focus-visible:ring-ring/50 focus-visible:outline-none`}
          onClick={onDrill}
        >
          {content}
        </button>
      ) : (
        <div className={row}>{content}</div>
      )}
      {search ? (
        <Link
          to="/finance/transactions"
          search={search}
          aria-label={`${slice.label}: view transactions`}
          className="shrink-0 rounded-md p-1 text-muted-foreground hover:bg-muted hover:text-foreground"
        >
          <ArrowUpRight className="size-4" aria-hidden />
        </Link>
      ) : (
        <span className="size-6 shrink-0" aria-hidden />
      )}
    </li>
  );
}
