import { Check, ChevronLeft, ChevronRight, type LucideIcon } from 'lucide-react';
import { type ComponentProps, type ReactNode, useState } from 'react';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import { formatMonth, formatShortMonth } from '@/lib/format';
import { currentMonth, monthStart, shiftMonth } from '@/lib/months';
import { cn } from '@/lib/utils';

export const pillClass =
  'inline-flex h-[34px] shrink-0 items-center gap-[7px] rounded-full bg-surface px-3 text-[13.5px] font-semibold whitespace-nowrap transition-colors hover:bg-surface-2 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring disabled:pointer-events-none disabled:opacity-50 md:h-9 md:px-3.5 md:text-sm [&>svg]:size-4 [&>svg]:shrink-0';

/** A rounded control on the soft tone; `on` when it narrows what's shown. */
export function Pill({ on, className, ...props }: ComponentProps<'button'> & { on?: boolean }) {
  return (
    <button
      type="button"
      className={cn(
        pillClass,
        on && 'bg-primary-soft text-primary hover:bg-primary-soft',
        className,
      )}
      {...props}
    />
  );
}

export type MenuOption = { value: string; label: string; leading?: ReactNode };

/** A pill that opens a short menu of choices, the chosen one ticked. */
export function MenuPill({
  icon: Icon,
  label,
  value,
  options,
  onChange,
  on,
  ariaLabel,
  align = 'start',
}: {
  icon: LucideIcon;
  label: ReactNode;
  value: string;
  options: MenuOption[];
  onChange: (value: string) => void;
  on?: boolean;
  ariaLabel: string;
  align?: 'start' | 'end';
}) {
  const [open, setOpen] = useState(false);
  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Pill on={on} aria-label={ariaLabel}>
          <Icon aria-hidden />
          {label}
        </Pill>
      </PopoverTrigger>
      <PopoverContent
        align={align}
        className="max-h-[min(24rem,var(--radix-popover-content-available-height))] w-60 overflow-y-auto p-1.5 shadow-pop"
      >
        {options.map((option) => (
          <button
            key={option.value}
            type="button"
            aria-pressed={option.value === value}
            onClick={() => {
              onChange(option.value);
              setOpen(false);
            }}
            className="flex w-full items-center gap-2.5 rounded-lg px-2.5 py-2 text-left text-sm font-medium hover:bg-surface-2"
          >
            {option.leading}
            <span className="min-w-0 flex-1 truncate">{option.label}</span>
            {option.value === value && <Check className="size-4 text-primary" aria-hidden />}
          </button>
        ))}
      </PopoverContent>
    </Popover>
  );
}

/** "‹ This month ›": steps a month at a time, never past the current one. */
export function MonthStepper({
  month,
  onChange,
}: {
  month: string;
  onChange: (month: string) => void;
}) {
  const now = currentMonth();
  const step =
    'grid h-[30px] w-8 place-items-center rounded-full text-muted-foreground hover:bg-surface-2 hover:text-foreground disabled:pointer-events-none disabled:opacity-30 [&>svg]:size-4';
  return (
    <div className="inline-flex h-[34px] shrink-0 items-center rounded-full bg-surface px-1 text-[13.5px] font-semibold md:h-9 md:text-sm">
      <button
        type="button"
        className={step}
        aria-label="Previous month"
        onClick={() => onChange(shiftMonth(month, -1))}
      >
        <ChevronLeft aria-hidden />
      </button>
      <span
        aria-live="polite"
        className="border-x px-2 text-center leading-5 tabular-nums md:min-w-[118px] md:px-3"
      >
        {month === now ? (
          'This month'
        ) : (
          <>
            <span className="md:hidden">{formatShortMonth(monthStart(month))}</span>
            <span className="hidden md:inline">{formatMonth(month)}</span>
          </>
        )}
      </span>
      <button
        type="button"
        className={step}
        aria-label="Next month"
        disabled={month >= now}
        onClick={() => onChange(shiftMonth(month, 1))}
      >
        <ChevronRight aria-hidden />
      </button>
    </div>
  );
}
