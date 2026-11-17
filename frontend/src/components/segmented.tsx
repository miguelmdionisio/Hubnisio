import type { LucideIcon } from 'lucide-react';
import { cn } from '@/lib/utils';

export type SegmentedOption<T extends string> = {
  value: T;
  label: string;
  /** Shown instead of the label, which then names the button for screen readers. */
  icon?: LucideIcon;
  title?: string;
};

/** A pill of mutually exclusive buttons: Mine / Household, the theme. */
export function Segmented<T extends string>({
  label,
  options,
  value,
  onChange,
  className,
}: {
  label: string;
  options: SegmentedOption<T>[];
  value: T;
  onChange: (value: T) => void;
  className?: string;
}) {
  return (
    <fieldset
      aria-label={label}
      className={cn('inline-flex shrink-0 rounded-full bg-surface p-[3px] text-[13px]', className)}
    >
      {options.map((option) => {
        const on = option.value === value;
        const Icon = option.icon;
        return (
          <button
            key={option.value}
            type="button"
            aria-pressed={on}
            aria-label={Icon ? option.label : undefined}
            title={option.title ?? (Icon ? option.label : undefined)}
            onClick={() => onChange(option.value)}
            className={cn(
              'tap-area grid h-7 place-items-center rounded-full [--tap-x:0px] font-medium text-muted-foreground transition-colors hover:text-foreground focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring',
              Icon ? 'w-11 md:w-8' : 'min-w-11 px-3 md:min-w-0',
              on && 'bg-surface-2 font-semibold text-foreground',
            )}
          >
            {Icon ? <Icon className="size-3.5" aria-hidden /> : option.label}
          </button>
        );
      })}
    </fieldset>
  );
}
