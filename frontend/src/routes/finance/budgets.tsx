import { useQuery } from '@tanstack/react-query';
import { useNavigate, useSearch } from '@tanstack/react-router';
import { ChevronLeft, ChevronRight, Plus } from 'lucide-react';
import { type ReactNode, useState } from 'react';
import { listBudgetsOptions } from '@/api/@tanstack/react-query.gen';
import type { BudgetOut, BudgetsOut, OverallBudgetOut } from '@/api/types.gen';
import { PageHeader } from '@/components/app-shell';
import { BudgetBar } from '@/components/budget-bar';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { errorMessage } from '@/lib/errors';
import { formatMoney, formatMonth } from '@/lib/format';
import { currentMonth, isMonth, monthStart, shiftMonth } from '@/lib/months';
import { cn } from '@/lib/utils';
import { useView } from '@/lib/view';
import { BudgetSheet, type BudgetTarget } from './budget-sheet';

export type BudgetSearch = { month?: string }; // "YYYY-MM"; the current month when absent

export function validateBudgetSearch(search: Record<string, unknown>): BudgetSearch {
  return { month: isMonth(search.month) ? search.month : undefined };
}

const eur = (amount: string) => formatMoney(amount, 'EUR');

/** Every category and group with a budget, nested ones too. */
function budgetedIds(budgets: BudgetOut[]): Set<string> {
  const ids = new Set<string>();
  const collect = (list: BudgetOut[]) => {
    for (const budget of list) {
      ids.add(budget.category_id);
      collect(budget.children);
    }
  };
  collect(budgets);
  return ids;
}

export function BudgetsPage() {
  const search = useSearch({ from: '/finance/budgets' });
  const navigate = useNavigate({ from: '/finance/budgets' });
  const month = search.month ?? currentMonth();
  const goTo = (target: string) => navigate({ search: { month: target } });

  const { view } = useView();
  const budgets = useQuery(listBudgetsOptions({ query: { month: monthStart(month), view } }));
  const [target, setTarget] = useState<BudgetTarget | null>(null);

  return (
    <>
      <PageHeader
        title="Budgets"
        showsView
        actions={
          <Button onClick={() => setTarget({ type: 'new' })}>
            <Plus aria-hidden />
            Add budget
          </Button>
        }
      />

      <div className="mb-4 flex items-center gap-2">
        <Button
          variant="outline"
          size="icon"
          aria-label="Previous month"
          onClick={() => goTo(shiftMonth(month, -1))}
        >
          <ChevronLeft aria-hidden />
        </Button>
        <h2 className="min-w-40 text-center text-lg font-medium" aria-live="polite">
          {formatMonth(month)}
        </h2>
        <Button
          variant="outline"
          size="icon"
          aria-label="Next month"
          onClick={() => goTo(shiftMonth(month, 1))}
        >
          <ChevronRight aria-hidden />
        </Button>
        {month !== currentMonth() && (
          <Button variant="ghost" onClick={() => goTo(currentMonth())}>
            This month
          </Button>
        )}
      </div>

      {budgets.isPending && <Skeleton className="h-64 w-full" />}
      {budgets.isError && (
        <Alert variant="destructive">
          <AlertTitle>Couldn't load budgets</AlertTitle>
          <AlertDescription>{errorMessage(budgets.error)}</AlertDescription>
        </Alert>
      )}
      {budgets.isSuccess && (
        <>
          <OverallCard
            overall={budgets.data.overall}
            onOpen={() => setTarget({ type: 'overall', budget: budgets.data.overall })}
          />
          <Summary data={budgets.data} />
          {budgets.data.budgets.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              No budgets in {formatMonth(month)}. Add one to see what's left of it each month.
            </p>
          ) : (
            <BudgetTable
              budgets={budgets.data.budgets}
              onOpen={(budget) => setTarget({ type: 'edit', budget })}
            />
          )}
        </>
      )}

      <BudgetSheet
        target={target}
        month={month}
        budgeted={budgetedIds(budgets.data?.budgets ?? [])}
        onClose={() => setTarget(null)}
      />
    </>
  );
}

/** The cap on all spending, uncategorized included: the headline above the category budgets. */
function OverallCard({
  overall,
  onOpen,
}: {
  overall: OverallBudgetOut | null;
  onOpen: () => void;
}) {
  if (!overall) {
    return (
      <Card size="sm" className="mb-3 max-w-4xl">
        <CardHeader>
          <CardTitle>All spending</CardTitle>
        </CardHeader>
        <CardContent className="flex flex-wrap items-center justify-between gap-3">
          <p className="text-sm text-muted-foreground">
            One monthly cap on everything you spend, uncategorized too.
          </p>
          <Button variant="outline" onClick={onOpen}>
            Set a monthly cap
          </Button>
        </CardContent>
      </Card>
    );
  }
  const over = Number(overall.remaining) < 0;
  return (
    <Card size="sm" className="mb-3 max-w-4xl">
      <CardHeader>
        <CardTitle className="flex flex-wrap items-center gap-1.5">
          <button
            type="button"
            className="tap-area text-left [--tap-x:0px] [--tap-y:13px] hover:underline"
            onClick={onOpen}
          >
            All spending
          </button>
          <BudgetBadges rollover={overall.rollover} carriedIn={overall.carried_in} over={over} />
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-2">
        <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
          <p className={cn('text-xl font-semibold tabular-nums', over && 'text-destructive')}>
            {eur(overall.spent)}{' '}
            <span className="text-sm font-normal text-muted-foreground">
              of {eur(overall.available)} available
            </span>
          </p>
          <p className={cn('text-sm tabular-nums', over && 'text-destructive')}>
            {eur(overall.remaining)} remaining
          </p>
        </div>
        <BudgetBar
          label="All spending"
          spent={overall.spent}
          available={overall.available}
          over={over}
        />
      </CardContent>
    </Card>
  );
}

function BudgetBadges({
  rollover,
  carriedIn,
  over,
}: {
  rollover: boolean;
  carriedIn: string;
  over: boolean;
}) {
  const carried = Number(carriedIn);
  return (
    <>
      {rollover && <Badge variant="secondary">Rollover</Badge>}
      {carried !== 0 && (
        <Badge
          variant={carried < 0 ? 'destructive' : 'outline'}
          title={carried < 0 ? 'Overspent last month' : 'Left over from last month'}
        >
          {carried > 0 && '+'}
          {eur(carriedIn)} carried
        </Badge>
      )}
      {over && <Badge variant="destructive">Over budget</Badge>}
    </>
  );
}

function Summary({ data }: { data: BudgetsOut }) {
  const over = Number(data.total_spent) > Number(data.total_available);
  return (
    <div className="mb-6 max-w-4xl space-y-3">
      <div className="grid gap-3 sm:grid-cols-3">
        <Stat
          title="Category budgets"
          className={over ? 'text-destructive' : undefined}
          figure={data.total_spent}
        >
          of {eur(data.total_available)} available
          <BudgetBar
            label="All budgets"
            spent={data.total_spent}
            available={data.total_available}
            over={over}
            className="mt-2"
          />
        </Stat>
        <Stat title="Not budgeted" figure={data.unbudgeted}>
          spent in categories without a budget
        </Stat>
        <Stat title="Uncategorized" figure={data.uncategorized}>
          spent with no category yet
        </Stat>
      </div>
      {data.unconverted > 0 && (
        <p className="text-xs text-muted-foreground">
          {data.unconverted} {data.unconverted === 1 ? 'transaction is' : 'transactions are'} left
          out: no exchange rate into euros for {data.unconverted === 1 ? 'its' : 'their'} day.
        </p>
      )}
    </div>
  );
}

function Stat({
  title,
  figure,
  className,
  children,
}: {
  title: string;
  figure: string;
  className?: string;
  children: ReactNode;
}) {
  return (
    <Card size="sm">
      <CardHeader>
        <CardTitle className="text-muted-foreground">{title}</CardTitle>
      </CardHeader>
      <CardContent>
        <p className={cn('text-xl font-semibold tabular-nums', className)}>{eur(figure)}</p>
        <div className="text-xs text-muted-foreground">{children}</div>
      </CardContent>
    </Card>
  );
}

function BudgetTable({
  budgets,
  onOpen,
}: {
  budgets: BudgetOut[];
  onOpen: (budget: BudgetOut) => void;
}) {
  return (
    <Table className="max-w-4xl">
      <TableHeader>
        <TableRow>
          <TableHead>Budget</TableHead>
          <TableHead className="hidden text-right md:table-cell">Limit</TableHead>
          <TableHead className="hidden text-right md:table-cell">Available</TableHead>
          <TableHead className="text-right">Spent</TableHead>
          <TableHead className="text-right">Remaining</TableHead>
          <TableHead className="w-24 md:w-36">
            <span className="sr-only">Progress</span>
          </TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {budgets.map((budget) => (
          <BudgetRows key={budget.category_id} budget={budget} depth={0} onOpen={onOpen} />
        ))}
      </TableBody>
    </Table>
  );
}

/** A budget's row, then the budgets nested in it (a group's categories). */
function BudgetRows({
  budget,
  depth,
  onOpen,
}: {
  budget: BudgetOut;
  depth: number;
  onOpen: (budget: BudgetOut) => void;
}) {
  const over = Number(budget.remaining) < 0;
  return (
    <>
      <TableRow>
        <TableCell>
          <div className={cn('flex flex-wrap items-center gap-1.5', depth > 0 && 'pl-6 text-sm')}>
            <button
              type="button"
              className="tap-area text-left font-medium [--tap-x:0px] [--tap-y:12px] hover:underline"
              onClick={() => onOpen(budget)}
            >
              {budget.name}
            </button>
            <BudgetBadges rollover={budget.rollover} carriedIn={budget.carried_in} over={over} />
          </div>
        </TableCell>
        <TableCell className="hidden text-right tabular-nums md:table-cell">
          {eur(budget.limit)}
        </TableCell>
        <TableCell className="hidden text-right tabular-nums md:table-cell">
          {eur(budget.available)}
        </TableCell>
        <TableCell className="text-right tabular-nums">{eur(budget.spent)}</TableCell>
        <TableCell
          className={cn('text-right font-medium tabular-nums', over && 'text-destructive')}
        >
          {eur(budget.remaining)}
        </TableCell>
        <TableCell>
          <BudgetBar
            label={budget.name}
            spent={budget.spent}
            available={budget.available}
            over={over}
          />
        </TableCell>
      </TableRow>
      {budget.children.map((child) => (
        <BudgetRows key={child.category_id} budget={child} depth={depth + 1} onOpen={onOpen} />
      ))}
    </>
  );
}
