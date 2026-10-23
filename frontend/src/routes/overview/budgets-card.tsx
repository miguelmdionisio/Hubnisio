import { useQuery } from '@tanstack/react-query';
import { Link } from '@tanstack/react-router';
import { listBudgetsOptions } from '@/api/@tanstack/react-query.gen';
import { BudgetBar } from '@/components/budget-bar';
import { formatMoney, formatMonth } from '@/lib/format';
import { currentMonth, monthStart } from '@/lib/months';
import { cn } from '@/lib/utils';
import { useView } from '@/lib/view';
import { cardLink, Note, Panel } from './panel';

const eur = (amount: string) => formatMoney(amount, 'EUR');

function BudgetItem({
  name,
  budget,
  className,
}: {
  name: string;
  budget: { spent: string; available: string; remaining: string };
  className?: string;
}) {
  const over = Number(budget.remaining) < 0;
  return (
    <li className={cn('space-y-1', className)}>
      <div className="flex items-baseline justify-between gap-2 text-sm">
        <span className="truncate">{name}</span>
        <span
          className={cn(
            'shrink-0 text-xs font-normal text-muted-foreground tabular-nums',
            over && 'text-destructive',
          )}
        >
          {eur(budget.spent)} of {eur(budget.available)}
        </span>
      </div>
      <BudgetBar label={name} spent={budget.spent} available={budget.available} over={over} />
    </li>
  );
}

export function BudgetsCard() {
  const month = currentMonth();
  const { view } = useView();
  const budgets = useQuery(listBudgetsOptions({ query: { month: monthStart(month), view } }));
  return (
    <Panel
      title="Budgets this month"
      description={formatMonth(month)}
      query={budgets}
      skeleton="h-72"
      action={
        <Link to="/finance/budgets" className={cardLink}>
          All budgets
        </Link>
      }
    >
      {(data) =>
        !data.overall && data.budgets.length === 0 ? (
          <Note>
            No budgets yet.{' '}
            <Link to="/finance/budgets" className="underline underline-offset-4">
              Create a budget
            </Link>{' '}
            to see how much is left.
          </Note>
        ) : (
          <ul className="space-y-3">
            {data.overall && (
              <BudgetItem
                name="All spending"
                budget={data.overall}
                className={cn('font-medium', data.budgets.length > 0 && 'border-b pb-3')}
              />
            )}
            {data.budgets.map((budget) => (
              <BudgetItem key={budget.category_id} name={budget.name} budget={budget} />
            ))}
          </ul>
        )
      }
    </Panel>
  );
}
