import type { UseQueryResult } from '@tanstack/react-query';
import type { ReactNode } from 'react';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import {
  Card,
  CardAction,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';
import { errorMessage } from '@/lib/errors';
import { formatMoney, formatMonth } from '@/lib/format';
import { cn } from '@/lib/utils';

/** What a query shows until it has data: a skeleton, or why it failed. Then `children(data)`. */
export function QueryView<T>({
  query,
  skeleton = 'h-10',
  children,
}: {
  query: UseQueryResult<T, unknown>;
  skeleton?: string; // the placeholder's size
  children: (data: T) => ReactNode;
}) {
  if (query.isPending) return <Skeleton className={cn('w-full', skeleton)} />;
  if (query.isError) {
    return (
      <Alert variant="destructive">
        <AlertTitle>Couldn't load this</AlertTitle>
        <AlertDescription>{errorMessage(query.error)}</AlertDescription>
      </Alert>
    );
  }
  return children(query.data);
}

/** A card of the overview, fed by one query. */
export function Panel<T>({
  title,
  description,
  action,
  query,
  skeleton,
  className,
  children,
}: {
  title: string;
  description?: string;
  action?: ReactNode;
  query: UseQueryResult<T, unknown>;
  skeleton?: string;
  className?: string;
  children: (data: T) => ReactNode;
}) {
  return (
    <Card size="sm" className={className}>
      <CardHeader>
        <CardTitle>
          <h3>{title}</h3>
        </CardTitle>
        {description && <CardDescription>{description}</CardDescription>}
        {action && <CardAction>{action}</CardAction>}
      </CardHeader>
      <CardContent>
        <QueryView query={query} skeleton={skeleton}>
          {children}
        </QueryView>
      </CardContent>
    </Card>
  );
}

/** A card's link to the page behind it. */
export const cardLink = 'text-xs text-muted-foreground underline-offset-4 hover:underline';

/** What a chart shows, as a table for screen readers: a row per month, a column per series. */
export function ChartTable({
  caption,
  rows,
  series,
}: {
  caption: string;
  rows: Record<string, string | number>[];
  series: { key: string; label: string }[];
}) {
  // A table ignores `width`, so the hiding goes on a wrapper.
  return (
    <div className="sr-only">
      <table>
        <caption>{caption}</caption>
        <thead>
          <tr>
            <th scope="col">Month</th>
            {series.map((item) => (
              <th key={item.key} scope="col">
                {item.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={String(row.month)}>
              <th scope="row">{formatMonth(String(row.month))}</th>
              {series.map((item) => (
                <td key={item.key}>{formatMoney(Number(row[item.key] ?? 0), 'EUR')}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** A small note under a chart or a figure. */
export function Note({ className, children }: { className?: string; children: ReactNode }) {
  return <p className={cn('text-xs text-muted-foreground', className)}>{children}</p>;
}
