import { useQuery } from '@tanstack/react-query';
import { getHealthOptions } from '../api/@tanstack/react-query.gen';
import { PageHeader } from '../components/app-shell';
import { BudgetsCard } from './overview/budgets-card';
import { CashFlowCard } from './overview/cash-flow-card';
import { NetWorthCard } from './overview/net-worth-card';
import { SpendingCard } from './overview/spending-card';
import { SpendingDonutCard } from './overview/spending-donut-card';
import { NetWorthTile, ThisMonthTile, ToCategorizeTile } from './overview/tiles';
import { UpcomingCard } from './overview/upcoming-card';

export function HomePage() {
  return (
    <>
      <PageHeader title="Overview" showsView />
      <div className="grid gap-4 lg:grid-cols-3">
        <div className="grid gap-4 sm:grid-cols-3 lg:col-span-3">
          <NetWorthTile />
          <ThisMonthTile />
          <ToCategorizeTile />
        </div>
        <SpendingCard />
        <SpendingDonutCard />
        <CashFlowCard />
        <BudgetsCard />
        <NetWorthCard />
        <UpcomingCard />
      </div>
      <SystemStatus />
    </>
  );
}

function SystemStatus() {
  const health = useQuery(getHealthOptions());
  return (
    <p className="mt-8 text-xs text-muted-foreground">
      {health.isPending && 'Checking the API…'}
      {health.isError && 'The API is unreachable.'}
      {health.data && `API ${health.data.status}, database ${health.data.database}.`}
    </p>
  );
}
