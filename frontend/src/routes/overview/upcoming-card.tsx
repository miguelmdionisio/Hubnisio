import { useQuery } from '@tanstack/react-query';
import { Link } from '@tanstack/react-router';
import { listUpcomingPaymentsOptions } from '@/api/@tanstack/react-query.gen';
import { formatDate, formatMoney } from '@/lib/format';
import { cardLink, Note, Panel } from './panel';
import { UPCOMING_DAYS as DAYS } from './tiles';

export function UpcomingCard() {
  const upcoming = useQuery(listUpcomingPaymentsOptions({ query: { days: DAYS } }));
  return (
    <Panel
      title="Upcoming payments"
      description={`The next ${DAYS} days`}
      query={upcoming}
      skeleton="h-40"
      action={
        <Link to="/finance/recurring" className={cardLink}>
          Recurring
        </Link>
      }
    >
      {(data) => {
        const payments = data.filter((payment) => payment.kind === 'expense');
        if (payments.length === 0) {
          return (
            <Note>
              No confirmed payment is due in the next {DAYS} days. Payments show up here once you've
              confirmed recurring payments.{' '}
              <Link to="/finance/recurring" className="underline underline-offset-4">
                Review recurring payments
              </Link>
            </Note>
          );
        }
        // Euros where there's a rate; a payment without one shows in its own currency.
        const total = payments.reduce((sum, payment) => sum + Number(payment.amount_eur ?? 0), 0);
        const unconverted = payments.filter((payment) => payment.amount_eur === null).length;
        return (
          <>
            <ul className="divide-y text-sm">
              {payments.map((payment) => (
                <li
                  key={`${payment.series_id}-${payment.on}`}
                  className="flex items-baseline justify-between gap-3 py-1.5"
                >
                  <span className="flex min-w-0 items-baseline gap-2">
                    <span className="shrink-0 text-xs whitespace-nowrap text-muted-foreground tabular-nums">
                      {formatDate(payment.on)}
                    </span>
                    <span className="truncate" title={payment.name}>
                      {payment.name}
                    </span>
                  </span>
                  <span className="shrink-0 tabular-nums">
                    {payment.amount_eur !== null
                      ? formatMoney(payment.amount_eur, 'EUR')
                      : formatMoney(payment.amount, payment.currency)}
                  </span>
                </li>
              ))}
            </ul>
            <p className="mt-2 flex justify-between border-t pt-2 text-sm font-medium">
              <span>Total</span>
              <span className="tabular-nums">{formatMoney(total, 'EUR')}</span>
            </p>
            {unconverted > 0 && (
              <Note className="mt-1">
                The total leaves out {unconverted} in another currency without an exchange rate.
              </Note>
            )}
          </>
        );
      }}
    </Panel>
  );
}
