import { useQuery } from '@tanstack/react-query';
import { Link } from '@tanstack/react-router';
import type { ReactNode } from 'react';
import { Bar, BarChart, CartesianGrid, XAxis, YAxis } from 'recharts';
import { getInvestmentsOptions } from '@/api/@tanstack/react-query.gen';
import type { Holding, InvestmentAccount } from '@/api/types.gen';
import { PageHeader } from '@/components/app-shell';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import {
  type ChartConfig,
  ChartContainer,
  ChartLegend,
  ChartLegendContent,
  ChartTooltip,
  ChartTooltipContent,
} from '@/components/ui/chart';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import {
  formatCompactMoney,
  formatMoney,
  formatMonth,
  formatMonthName,
  formatPercent,
  formatQuantity,
  formatRelative,
} from '@/lib/format';
import { cn } from '@/lib/utils';
import { Note, QueryView } from '../overview/panel';

const MONTHS = 12;

const incomeConfig = {
  dividends: { label: 'Dividends', color: 'var(--chart-2)' },
  interest: { label: 'Interest', color: 'var(--chart-4)' },
} satisfies ChartConfig;

/** Investment accounts as of their latest sync (ADR-0008): figures, holdings, and income. */
export function InvestmentsPage() {
  const investments = useQuery(getInvestmentsOptions({ query: { months: MONTHS } }));
  return (
    <>
      <PageHeader
        title="Investments"
        description="As Trading 212 reported them at the latest sync, in the account's currency."
      />
      <QueryView query={investments} skeleton="h-72">
        {(data) =>
          data.accounts.length === 0 ? (
            <Card className="max-w-xl">
              <CardHeader>
                <CardTitle>No investment accounts</CardTitle>
                <CardDescription>
                  A Trading 212 account appears here once it's linked with{' '}
                  <code>cli t212-link</code> (README, "Linking Trading 212").
                </CardDescription>
              </CardHeader>
            </Card>
          ) : (
            <div className="space-y-10">
              {data.accounts.map((account) => (
                <AccountSection key={account.id} account={account} months={data.months} />
              ))}
            </div>
          )
        }
      </QueryView>
    </>
  );
}

function AccountSection({ account, months }: { account: InvestmentAccount; months: string[] }) {
  const money = (amount: string) => formatMoney(amount, account.currency);
  return (
    <section aria-labelledby={`account-${account.id}`} className="space-y-4">
      <div className="flex items-baseline justify-between gap-4">
        <h2 id={`account-${account.id}`} className="text-lg font-semibold">
          {account.name}
        </h2>
        {account.as_of && <Note>Synced {formatRelative(account.as_of)}</Note>}
      </div>
      {account.as_of === null && (
        <Card size="sm" className="max-w-xl">
          <CardHeader>
            <CardTitle>No holdings yet</CardTitle>
            <CardDescription>
              They're read at the next sync.{' '}
              <Link to="/finance/connections" className="underline underline-offset-4">
                Sync it now
              </Link>
            </CardDescription>
          </CardHeader>
        </Card>
      )}
      {account.as_of !== null && (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <Figure title="Value" note="Cash plus holdings at market value">
            {account.value === null ? null : money(account.value)}
          </Figure>
          <Figure title="Cash" note="Not invested">
            {account.cash === null ? null : money(account.cash)}
          </Figure>
          <Figure title="Cost" note="What the holdings cost">
            {account.cost === null ? null : money(account.cost)}
          </Figure>
          <Figure
            title="Result"
            note={
              account.realised_result !== null
                ? `${money(account.realised_result)} realised on sales`
                : 'On the holdings'
            }
            tone={account.result}
          >
            {account.result === null ? null : (
              <>
                {signed(account.result, money)}
                {account.cost !== null && Number(account.cost) > 0 && (
                  <span className="ml-2 text-sm font-normal">
                    {formatPercent(Number(account.result) / Number(account.cost), true)}
                  </span>
                )}
              </>
            )}
          </Figure>
        </div>
      )}
      {account.holdings.length > 0 && <Holdings holdings={account.holdings} money={money} />}
      <IncomeCard account={account} months={months} />
    </section>
  );
}

function Figure({
  title,
  note,
  tone,
  children,
}: {
  title: string;
  note: string;
  tone?: string | null; // a result: green when positive, red when negative
  children: ReactNode;
}) {
  return (
    <Card size="sm">
      <CardHeader>
        <CardTitle>
          <h3>{title}</h3>
        </CardTitle>
      </CardHeader>
      <CardContent>
        <p className={cn('text-2xl font-semibold tabular-nums', toneClass(tone))}>
          {children ?? '—'}
        </p>
        <Note>{note}</Note>
      </CardContent>
    </Card>
  );
}

function Holdings({ holdings, money }: { holdings: Holding[]; money: (amount: string) => string }) {
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Holding</TableHead>
          <TableHead className="text-right">Quantity</TableHead>
          <TableHead className="text-right">Price</TableHead>
          <TableHead className="text-right">Value</TableHead>
          <TableHead className="text-right">Cost</TableHead>
          <TableHead className="text-right">Result</TableHead>
          <TableHead className="text-right">Weight</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {holdings.map((holding) => (
          <TableRow key={holding.ticker}>
            <TableCell>
              <div className="font-medium">{holding.name}</div>
              <div className="text-xs text-muted-foreground">
                {[holding.ticker, holding.type && typeLabel(holding.type)]
                  .filter(Boolean)
                  .join(' · ')}
              </div>
            </TableCell>
            <TableCell className="text-right tabular-nums">
              {formatQuantity(holding.quantity)}
            </TableCell>
            <TableCell className="text-right tabular-nums">
              {holding.current_price === null
                ? '—'
                : holding.instrument_currency
                  ? formatMoney(holding.current_price, holding.instrument_currency)
                  : formatQuantity(holding.current_price)}
            </TableCell>
            <TableCell className="text-right tabular-nums">
              {holding.value === null ? '—' : money(holding.value)}
            </TableCell>
            <TableCell className="text-right tabular-nums">
              {holding.cost === null ? '—' : money(holding.cost)}
            </TableCell>
            <TableCell className={cn('text-right tabular-nums', toneClass(holding.result))}>
              {holding.result === null ? '—' : signed(holding.result, money)}
            </TableCell>
            <TableCell className="text-right tabular-nums">
              {holding.weight === null ? '—' : formatPercent(holding.weight)}
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}

function IncomeCard({ account, months }: { account: InvestmentAccount; months: string[] }) {
  const rows = months.map((month, index) => ({
    month,
    label: formatMonthName(month),
    dividends: Number(account.dividends[index] ?? 0),
    interest: Number(account.interest[index] ?? 0),
  }));
  const total = rows.reduce((sum, row) => sum + row.dividends + row.interest, 0);
  return (
    <Card size="sm">
      <CardHeader>
        <CardTitle>
          <h3>Dividends and interest</h3>
        </CardTitle>
        <CardDescription>
          Per month, the last {months.length} months: {formatMoney(total, account.currency)} in all
        </CardDescription>
      </CardHeader>
      <CardContent>
        {total === 0 ? (
          <Note>Nothing paid in these months.</Note>
        ) : (
          <ChartContainer config={incomeConfig} className="aspect-auto h-60 w-full">
            <BarChart data={rows}>
              <CartesianGrid vertical={false} />
              <XAxis dataKey="label" tickLine={false} axisLine={false} />
              <YAxis
                width={52}
                tickLine={false}
                axisLine={false}
                tickFormatter={(value) => formatCompactMoney(value, account.currency)}
              />
              <ChartTooltip
                content={
                  <ChartTooltipContent
                    valueFormatter={(value) => formatMoney(Number(value), account.currency)}
                    labelFormatter={(_, payload) => formatMonth(String(payload[0]?.payload.month))}
                  />
                }
              />
              <ChartLegend content={<ChartLegendContent />} />
              <Bar dataKey="dividends" stackId="income" fill="var(--color-dividends)" />
              <Bar
                dataKey="interest"
                stackId="income"
                fill="var(--color-interest)"
                radius={[3, 3, 0, 0]}
              />
            </BarChart>
          </ChartContainer>
        )}
      </CardContent>
    </Card>
  );
}

const TYPE_LABELS: Record<string, string> = { ETF: 'ETF', STOCK: 'Stock' };

function typeLabel(type: string): string {
  return TYPE_LABELS[type] ?? type.charAt(0) + type.slice(1).toLowerCase();
}

function signed(amount: string, money: (amount: string) => string): string {
  return Number(amount) > 0 ? `+${money(amount)}` : money(amount);
}

function toneClass(amount: string | null | undefined): string | undefined {
  if (amount === null || amount === undefined) return undefined;
  if (Number(amount) > 0) return 'text-emerald-700 dark:text-emerald-400';
  if (Number(amount) < 0) return 'text-destructive';
  return undefined;
}
