import { keepPreviousData, type UseQueryResult, useQuery } from '@tanstack/react-query';
import { Link } from '@tanstack/react-router';
import { type ReactNode, useState } from 'react';
import { Area, Bar, BarChart, CartesianGrid, ComposedChart, Line, XAxis, YAxis } from 'recharts';
import {
  getInvestmentReturnsOptions,
  getInvestmentsOptions,
} from '@/api/@tanstack/react-query.gen';
import type {
  Holding,
  InvestmentAccount,
  InvestmentCheck,
  InvestmentReturns,
  InvestmentReturnsOut,
  ReturnGap,
} from '@/api/types.gen';
import { PageHeader } from '@/components/app-shell';
import {
  Card,
  CardAction,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card';
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
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs';
import {
  formatCompactMoney,
  formatDate,
  formatMoney,
  formatMonth,
  formatMonthName,
  formatPercent,
  formatQuantity,
  formatRelative,
} from '@/lib/format';
import { cn } from '@/lib/utils';
import { axisTicks } from '../overview/chart-data';
import { Note, QueryView } from '../overview/panel';

const MONTHS = 12;

const incomeConfig = {
  dividends: { label: 'Dividends', color: 'var(--chart-2)' },
  interest: { label: 'Interest', color: 'var(--chart-4)' },
} satisfies ChartConfig;

const valueConfig = {
  value: { label: 'Value', color: 'var(--chart-1)' },
  net_deposits: { label: 'Net deposits', color: 'var(--chart-3)' },
} satisfies ChartConfig;

type Period = 'all' | 'year' | '12m';

const PERIODS: { value: Period; label: string }[] = [
  { value: 'all', label: 'All time' },
  { value: 'year', label: 'This year' },
  { value: '12m', label: '12 months' },
];

/** The period's first day; none for all time, which starts at the account's first movement. */
function periodStart(period: Period, today = new Date()): string | undefined {
  if (period === 'all') return undefined;
  const start =
    period === 'year'
      ? new Date(today.getFullYear(), 0, 1)
      : new Date(today.getFullYear() - 1, today.getMonth(), today.getDate() + 1);
  const month = String(start.getMonth() + 1).padStart(2, '0');
  return `${start.getFullYear()}-${month}-${String(start.getDate()).padStart(2, '0')}`;
}

/** Investment accounts as of their latest sync (ADR-0008): figures, holdings, income, and
 * returns over a period. */
export function InvestmentsPage() {
  const investments = useQuery(getInvestmentsOptions({ query: { months: MONTHS } }));
  const [period, setPeriod] = useState<Period>('all');
  const returns = useQuery({
    ...getInvestmentReturnsOptions({ query: { date_from: periodStart(period) } }),
    placeholderData: keepPreviousData,
  });
  return (
    <>
      <PageHeader title="Investments" />
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
                <AccountSection
                  key={account.id}
                  account={account}
                  months={data.months}
                  returns={
                    <ReturnsCard
                      id={account.id}
                      query={returns}
                      period={period}
                      onPeriod={setPeriod}
                    />
                  }
                />
              ))}
            </div>
          )
        }
      </QueryView>
    </>
  );
}

function AccountSection({
  account,
  months,
  returns,
}: {
  account: InvestmentAccount;
  months: string[];
  returns: ReactNode;
}) {
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
      {account.as_of !== null && returns}
      {account.check && account.value !== null && (
        <CheckCard check={account.check} value={account.value} money={money} />
      )}
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

/** The value rebuilt from trades and daily prices, which net worth uses, against Trading 212's
 * own; and what the history doesn't explain. Shown whatever it says, never hidden. */
function CheckCard({
  check,
  value,
  money,
}: {
  check: InvestmentCheck;
  value: string;
  money: (amount: string) => string;
}) {
  const unexplained = Number(check.unexplained_cash) !== 0 || check.unexplained.length > 0;
  const matches =
    check.difference !== null &&
    Number(check.difference) === 0 &&
    !unexplained &&
    check.unpriced.length === 0;
  return (
    <Card size="sm">
      <CardHeader>
        <CardTitle>
          <h3>Check against Trading 212</h3>
        </CardTitle>
        <CardDescription>
          Net worth values the account from its trades and daily prices. On {formatDate(check.on)},
          the day of the latest sync:
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-2">
        <dl className="grid grid-cols-3 gap-4 text-sm">
          <div>
            <dt className="text-muted-foreground">Rebuilt</dt>
            <dd className="font-semibold tabular-nums">
              {check.rebuilt_value === null ? '—' : money(check.rebuilt_value)}
            </dd>
          </div>
          <div>
            <dt className="text-muted-foreground">Trading 212</dt>
            <dd className="font-semibold tabular-nums">{money(value)}</dd>
          </div>
          <div>
            <dt className="text-muted-foreground">Difference</dt>
            <dd className="font-semibold tabular-nums">
              {check.difference === null ? '—' : signed(check.difference, money)}
            </dd>
          </div>
        </dl>
        {matches && <Note>They match to the cent.</Note>}
        {check.rebuilt_value === null && <Note>No exchange rate for that day yet.</Note>}
        {check.unpriced.length > 0 && (
          <Note>Left out, with no price for that day: {check.unpriced.join(', ')}.</Note>
        )}
        {unexplained && (
          <Note>
            Trading 212 has{' '}
            {[
              ...(Number(check.unexplained_cash) !== 0
                ? [`${difference(check.unexplained_cash, money)} cash`]
                : []),
              ...check.unexplained.map(
                (item) => `${difference(item.quantity, formatQuantity)} shares of ${item.name}`,
              ),
            ].join(' and ')}{' '}
            than the trades and cash movements add up to: something the history doesn't show, such
            as a corporate action, so earlier days are off by that much.
          </Note>
        )}
      </CardContent>
    </Card>
  );
}

const GAPS: Record<ReturnGap, string> = {
  no_money: 'Nothing was invested in this period.',
  no_value: "No exchange rate for the account's currency at the period's start or end.",
  no_solution: "No single rate fits this period's money in and out.",
};

/** The account's result over a period, broken down; both returns; and its value against what
 * went in (ADR-0008, "Returns"). */
function ReturnsCard({
  id,
  query,
  period,
  onPeriod,
}: {
  id: string;
  query: UseQueryResult<InvestmentReturnsOut, unknown>;
  period: Period;
  onPeriod: (period: Period) => void;
}) {
  const shown = query.data?.accounts.find((account) => account.id === id);
  return (
    <Card size="sm">
      <CardHeader>
        <CardTitle>
          <h3>Returns</h3>
        </CardTitle>
        <CardDescription>
          {shown?.date_from && shown.date_to
            ? `${formatDate(shown.date_from)} to ${formatDate(shown.date_to)}`
            : 'Over the period'}
        </CardDescription>
        <CardAction>
          <Tabs value={period} onValueChange={(value) => onPeriod(value as Period)}>
            <TabsList>
              {PERIODS.map((option) => (
                <TabsTrigger key={option.value} value={option.value}>
                  {option.label}
                </TabsTrigger>
              ))}
            </TabsList>
          </Tabs>
        </CardAction>
      </CardHeader>
      <CardContent>
        <QueryView query={query} skeleton="h-72">
          {() =>
            shown?.date_from ? (
              <Returns returns={shown} />
            ) : (
              <Note>Returns show once the account's history is read.</Note>
            )
          }
        </QueryView>
      </CardContent>
    </Card>
  );
}

function Returns({ returns }: { returns: InvestmentReturns }) {
  const money = (amount: string) => formatMoney(amount, returns.currency);
  const { breakdown, start_value: start, end_value: end } = returns;
  return (
    <div className="space-y-6">
      <div className="grid gap-4 sm:grid-cols-2">
        <ReturnFigure
          title="Time-weighted return"
          rate={returns.time_weighted}
          annual={returns.time_weighted_annual}
          gap={returns.time_weighted_gap}
          explanation="How the investments did, whatever the timing of deposits and withdrawals."
        />
        <ReturnFigure
          title="Money-weighted return"
          rate={returns.money_weighted}
          annual={returns.money_weighted_annual}
          gap={returns.money_weighted_gap}
          explanation="What your money earned, given when it went in and came out."
        />
      </div>
      {breakdown && start !== null && end !== null && (
        <dl className="grid max-w-md grid-cols-[1fr_auto] gap-x-6 gap-y-1 text-sm">
          <BreakdownLine label="Value at the start">{money(start)}</BreakdownLine>
          <BreakdownLine label="Net deposits">{signed(returns.net_deposits, money)}</BreakdownLine>
          <BreakdownLine label="Result" strong tone={breakdown.total}>
            {signed(breakdown.total, money)}
          </BreakdownLine>
          <Part label="Price movements, realised" amount={breakdown.realised} money={money} />
          <Part label="Price movements, unrealised" amount={breakdown.unrealised} money={money} />
          <Part label="Dividends" amount={breakdown.dividends} money={money} />
          <Part label="Interest" amount={breakdown.interest} money={money} />
          <Part label="Fees and taxes" amount={breakdown.fees} money={money} />
          {Number(breakdown.other) !== 0 && (
            <Part label="Other cash movements" amount={breakdown.other} money={money} />
          )}
          <BreakdownLine label="Value at the end" strong>
            {money(end)}
          </BreakdownLine>
        </dl>
      )}
      <ValueChart returns={returns} />
      {returns.unpriced > 0 && (
        <Note>
          {returns.unpriced === 1
            ? '1 holding-day has no price and is left out of the value'
            : `${returns.unpriced} holding-days have no price and are left out of the value`}
          , so these figures are off by what they were worth.
        </Note>
      )}
      {returns.unconverted > 0 && (
        <Note>
          {returns.unconverted === 1
            ? "1 day has no exchange rate for the account's currency and is left out."
            : `${returns.unconverted} days have no exchange rate for the account's currency and are left out.`}
        </Note>
      )}
    </div>
  );
}

function ReturnFigure({
  title,
  rate,
  annual,
  gap,
  explanation,
}: {
  title: string;
  rate: string | null;
  annual: string | null;
  gap: ReturnGap | null;
  explanation: string;
}) {
  return (
    <div className="space-y-1">
      <h4 className="text-sm text-muted-foreground" title={explanation}>
        {title}
      </h4>
      <p className={cn('text-2xl font-semibold tabular-nums', toneClass(rate))}>
        {rate === null ? '—' : formatPercent(rate, true)}
        {annual !== null && annual !== rate && (
          <span className="ml-2 text-sm font-normal">{formatPercent(annual, true)} a year</span>
        )}
      </p>
      {rate === null && gap && <Note>{GAPS[gap]}</Note>}
    </div>
  );
}

/** A line of the breakdown. */
function BreakdownLine({
  label,
  strong,
  tone,
  children,
}: {
  label: string;
  strong?: boolean;
  tone?: string;
  children: ReactNode;
}) {
  return (
    <>
      <dt className={strong ? 'font-medium' : 'text-muted-foreground'}>{label}</dt>
      <dd className={cn('text-right tabular-nums', strong && 'font-semibold', toneClass(tone))}>
        {children}
      </dd>
    </>
  );
}

/** A part of the result, indented under it. */
function Part({
  label,
  amount,
  money,
}: {
  label: string;
  amount: string;
  money: (amount: string) => string;
}) {
  return (
    <>
      <dt className="pl-4 text-muted-foreground">{label}</dt>
      <dd className="text-right text-muted-foreground tabular-nums">{signed(amount, money)}</dd>
    </>
  );
}

/** The value each day against the net deposits since the account opened: the gap between
 * them is what the money earned. */
function ValueChart({ returns }: { returns: InvestmentReturns }) {
  if (returns.points.length < 2) return null;
  const points = returns.points.map((point) => ({
    on: point.on,
    value: point.value === null ? null : Number(point.value),
    net_deposits: Number(point.net_deposits),
  }));
  return (
    <figure className="space-y-2">
      <figcaption className="text-sm font-medium">Value against net deposits</figcaption>
      <ChartContainer config={valueConfig} className="aspect-auto h-64 w-full">
        <ComposedChart data={points}>
          <CartesianGrid vertical={false} />
          <XAxis
            dataKey="on"
            ticks={axisTicks(returns.points)}
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
            tickFormatter={(value) => formatCompactMoney(value, returns.currency)}
          />
          <ChartTooltip
            content={
              <ChartTooltipContent
                valueFormatter={(value) => formatMoney(Number(value), returns.currency)}
                labelFormatter={(_, payload) => formatDate(String(payload[0]?.payload.on))}
              />
            }
          />
          <ChartLegend content={<ChartLegendContent />} />
          <Area
            dataKey="value"
            type="monotone"
            stroke="var(--color-value)"
            fill="var(--color-value)"
            fillOpacity={0.15}
            strokeWidth={2}
            dot={false}
          />
          <Line
            dataKey="net_deposits"
            type="stepAfter"
            stroke="var(--color-net_deposits)"
            strokeWidth={2}
            strokeDasharray="4 3"
            dot={false}
          />
        </ComposedChart>
      </ChartContainer>
    </figure>
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

/** "5 more" or "5 less", for what the history doesn't explain. */
function difference(amount: string, format: (amount: string) => string): string {
  const absolute = format(String(Math.abs(Number(amount))));
  return Number(amount) > 0 ? `${absolute} more` : `${absolute} less`;
}

function signed(amount: string, money: (amount: string) => string): string {
  return Number(amount) > 0 ? `+${money(amount)}` : money(amount);
}

function toneClass(amount: string | null | undefined): string | undefined {
  if (amount === null || amount === undefined) return undefined;
  if (Number(amount) > 0) return 'text-good';
  if (Number(amount) < 0) return 'text-destructive';
  return undefined;
}
