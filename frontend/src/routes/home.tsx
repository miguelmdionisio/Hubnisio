import { PageHeader } from '../components/app-shell';
import { BudgetsCard } from './overview/budgets-card';
import { CashFlowCard } from './overview/cash-flow-card';
import { NetWorthCard } from './overview/net-worth-card';
import { SpendingCard } from './overview/spending-card';
import { SpendingDonutCard } from './overview/spending-donut-card';
import { SyncStatus } from './overview/sync-status';
import { NetWorthTile, NextPaymentTile, ThisMonthTile, ToCategorize } from './overview/tiles';
import { UpcomingCard } from './overview/upcoming-card';

/** The daily glance on top (where things stand, what's left, what's due), then the weekly
 * review: what needs a category and the charts. */
export function HomePage() {
  return (
    <>
      <PageHeader title="Overview" showsView actions={<SyncStatus />} />
      <section aria-labelledby="glance" className="space-y-4">
        <h2 id="glance" className="sr-only">
          At a glance
        </h2>
        <div className="grid gap-4 sm:grid-cols-3">
          <NetWorthTile />
          <ThisMonthTile />
          <NextPaymentTile />
        </div>
        <div className="grid items-start gap-4 lg:grid-cols-3">
          <BudgetsCard className="lg:col-span-2" />
          <UpcomingCard />
        </div>
      </section>
      <section aria-labelledby="review" className="mt-12 border-t pt-6">
        <div className="mb-4 flex flex-wrap items-baseline justify-between gap-x-6 gap-y-2">
          <h2 id="review" className="text-lg font-semibold">
            Weekly review
          </h2>
          <ToCategorize />
        </div>
        <div className="grid gap-4 lg:grid-cols-2">
          <SpendingCard />
          <CashFlowCard />
          <SpendingDonutCard />
          <NetWorthCard />
        </div>
      </section>
    </>
  );
}
