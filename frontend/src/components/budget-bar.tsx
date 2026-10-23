import { formatMoney } from '@/lib/format';
import { cn } from '@/lib/utils';

const eur = (amount: string) => formatMoney(amount, 'EUR');

/** How much of what's available is spent. Red once it's over. */
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
  const ratio = total > 0 ? used / total : used > 0 ? 1 : 0;
  const percent = Math.round(Math.min(1, Math.max(0, ratio)) * 100);
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
