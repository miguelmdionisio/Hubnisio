import type { ReactNode } from 'react';
import { Card } from '@/components/ui/card';

/** A card with a title and, at the right, short facts about it. */
export function Section({
  title,
  aside,
  children,
}: {
  title: string;
  aside?: ReactNode;
  children: ReactNode;
}) {
  return (
    <Card className="min-w-0 px-(--card-spacing)">
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <h2 className="text-[15px] font-semibold">{title}</h2>
        {aside && (
          <div className="ml-auto flex flex-wrap items-center gap-x-3.5 gap-y-1 text-xs text-muted-foreground">
            {aside}
          </div>
        )}
      </div>
      {children}
    </Card>
  );
}

/** A figure with its label and, beneath, a short note. */
export function Figure({
  label,
  value,
  unit,
  note,
}: {
  label: string;
  value: string;
  unit?: string;
  note?: ReactNode;
}) {
  return (
    <Card size="sm" className="min-w-0 gap-1 px-(--card-spacing)">
      <p className="text-[13px] text-muted-foreground">{label}</p>
      <p className="text-3xl font-bold tracking-tight tabular-nums">
        {value}
        {unit && (
          <small className="ml-1 text-base font-semibold text-muted-foreground">{unit}</small>
        )}
      </p>
      <p className="min-h-5 text-[13px] text-muted-foreground tabular-nums">{note}</p>
    </Card>
  );
}

/** A smaller figure inside a card. */
export function Mini({
  label,
  value,
  unit,
  note,
}: {
  label: string;
  value: string;
  unit?: string;
  note?: ReactNode;
}) {
  return (
    <div className="min-w-0 rounded-[14px] bg-surface-2 px-3.5 py-3">
      <p className="text-[13px] text-muted-foreground">{label}</p>
      <p className="mt-0.5 text-xl font-bold tabular-nums">
        {value}
        {unit && <small className="ml-1 text-xs font-semibold text-muted-foreground">{unit}</small>}
      </p>
      <p className="min-h-4 text-[13px] text-muted-foreground tabular-nums">{note}</p>
    </div>
  );
}

export const number = (value: number | null | undefined, places = 0) =>
  value === null || value === undefined
    ? '–'
    : value.toLocaleString('en-GB', {
        minimumFractionDigits: places,
        maximumFractionDigits: places,
      });

/** Headers and cells of the page's tables, which scroll sideways in their own box. */
export const th =
  'px-2 py-1.5 text-left text-xs font-medium whitespace-nowrap text-muted-foreground';
export const td = 'px-2 py-2 whitespace-nowrap tabular-nums';

export function Table({ children, label }: { children: ReactNode; label: string }) {
  return (
    <div className="-mx-1 overflow-x-auto px-1">
      <table className="w-full min-w-[420px] text-[13.5px]" aria-label={label}>
        {children}
      </table>
    </div>
  );
}
