import { formatMoney } from '@/lib/format';
import { cn } from '@/lib/utils';

const eur = (amount: string) => formatMoney(amount, 'EUR');

/** How much of the current month has gone, counting today: where spending "should" be. */
export function monthPace(today = new Date()): number {
  const days = new Date(today.getFullYear(), today.getMonth() + 1, 0).getDate();
  return today.getDate() / days;
}

/**
 * How much of what's available is spent. Red once it's over. Negative spending (repayments
 * above what was spent) leaves the bar empty: what remains is shown beside it, above the limit.
 * `color` fills it (a category's colour; the accent by default); `pace` (0 to 1) ticks where
 * the month has got to.
 */
export function BudgetBar({
  label,
  spent,
  available,
  over,
  color,
  pace,
  className,
}: {
  label: string;
  spent: string;
  available: string;
  over: boolean;
  color?: string;
  pace?: number;
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
      className={cn('relative h-1.5 w-full rounded-full bg-track', className)}
    >
      <div
        className={cn('h-full rounded-full', over ? 'bg-destructive' : !color && 'bg-primary')}
        style={{ width: `${percent}%`, background: over || !color ? undefined : color }}
      />
      {pace !== undefined && (
        <span
          aria-hidden
          className="absolute -top-[3px] -bottom-[3px] w-0.5 rounded-full bg-foreground/40"
          style={{ left: `${Math.min(1, pace) * 100}%` }}
        />
      )}
    </div>
  );
}
