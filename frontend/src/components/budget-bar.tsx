import { formatMoney } from '@/lib/format';
import { cn } from '@/lib/utils';

const eur = (amount: string) => formatMoney(amount, 'EUR');

/**
 * How much of what's available is spent. Red once it's over. Negative spending (repayments
 * above what was spent) leaves the bar empty: what remains is shown beside it, above the limit.
 */
export function BudgetBar({
  label,
  spent,
  available,
  over,
  className,
}: {
  label: string;
  spent: string;
  available: string;
  over: boolean;
  className?: string;
}) {
  const used = Number(spent);
  const total = Number(available);
  const ratio = used <= 0 ? 0 : total > 0 ? used / total : 1;
  const percent = Math.round(Math.min(1, ratio) * 100);
  return (
    <div
      role="progressbar"
      aria-label={`${label} spent`}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={percent}
      aria-valuetext={`${eur(spent)} of ${eur(available)}${over ? ', over budget' : ''}`}
      className={cn('h-2 w-full overflow-hidden rounded-full bg-muted', className)}
    >
      <div
        className={cn('h-full rounded-full', over ? 'bg-destructive' : 'bg-primary')}
        style={{ width: `${percent}%` }}
      />
    </div>
  );
}
