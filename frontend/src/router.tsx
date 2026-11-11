import {
  createRootRoute,
  createRoute,
  createRouter,
  type RouterHistory,
} from '@tanstack/react-router';
import { AppShell } from './components/app-shell';
import { errorMessage } from './lib/errors';
import { AccountsPage } from './routes/finance/accounts';
import { BudgetsPage, validateBudgetSearch } from './routes/finance/budgets';
import { CallbackPage, validateCallbackSearch } from './routes/finance/callback';
import { CategoriesPage } from './routes/finance/categories';
import { ConnectionsPage } from './routes/finance/connections';
import { InvestmentsPage } from './routes/finance/investments';
import { MerchantsPage } from './routes/finance/merchants';
import { MorePage } from './routes/finance/more';
import { RecurringPage, validateRecurringSearch } from './routes/finance/recurring';
import { RulesPage } from './routes/finance/rules';
import { CategorySpendingPage, MerchantSpendingPage } from './routes/finance/spending/detail';
import { validateSpendingSearch } from './routes/finance/spending/search';
import { SpendingPage } from './routes/finance/spending/spending';
import { TransactionsPage, validateTransactionSearch } from './routes/finance/transactions';
import { ActivitiesPage } from './routes/health/activities/activities';
import { ActivityPage } from './routes/health/activities/activity';
import { validateActivitiesSearch } from './routes/health/activities/search';
import { BodyPage } from './routes/health/body/body';
import { validateBodySearch } from './routes/health/body/search';
import { GarminPage } from './routes/health/garmin/garmin';
import { HealthMorePage } from './routes/health/more/more';
import { PerformancePage } from './routes/health/performance/performance';
import { RecoveryPage } from './routes/health/recovery/recovery';
import { validateRecoverySearch } from './routes/health/recovery/search';
import { validateSleepSearch } from './routes/health/sleep/search';
import { SleepPage } from './routes/health/sleep/sleep';
import { TodayPage } from './routes/health/today/today';
import { TrainingPage } from './routes/health/training/training';
import { HomePage } from './routes/home';

const rootRoute = createRootRoute({
  component: AppShell,
  errorComponent: ({ error }) => (
    <div className="p-8">
      <h1 className="text-2xl font-semibold">Something broke</h1>
      <p className="mt-2 text-sm text-muted-foreground">{errorMessage(error)}</p>
    </div>
  ),
});

const routeTree = rootRoute.addChildren([
  createRoute({ getParentRoute: () => rootRoute, path: '/', component: HomePage }),
  createRoute({
    getParentRoute: () => rootRoute,
    path: '/finance/accounts',
    component: AccountsPage,
  }),
  createRoute({
    getParentRoute: () => rootRoute,
    path: '/finance/investments',
    component: InvestmentsPage,
  }),
  createRoute({
    getParentRoute: () => rootRoute,
    path: '/finance/spending',
    validateSearch: validateSpendingSearch,
    component: SpendingPage,
  }),
  createRoute({
    getParentRoute: () => rootRoute,
    path: '/finance/spending/category/$id',
    validateSearch: validateSpendingSearch,
    component: CategorySpendingPage,
  }),
  createRoute({
    getParentRoute: () => rootRoute,
    path: '/finance/spending/merchant/$id',
    validateSearch: validateSpendingSearch,
    component: MerchantSpendingPage,
  }),
  createRoute({
    getParentRoute: () => rootRoute,
    path: '/finance/transactions',
    validateSearch: validateTransactionSearch,
    component: TransactionsPage,
  }),
  createRoute({
    getParentRoute: () => rootRoute,
    path: '/finance/categories',
    component: CategoriesPage,
  }),
  createRoute({
    getParentRoute: () => rootRoute,
    path: '/finance/budgets',
    validateSearch: validateBudgetSearch,
    component: BudgetsPage,
  }),
  createRoute({
    getParentRoute: () => rootRoute,
    path: '/finance/recurring',
    validateSearch: validateRecurringSearch,
    component: RecurringPage,
  }),
  createRoute({ getParentRoute: () => rootRoute, path: '/finance/rules', component: RulesPage }),
  createRoute({
    getParentRoute: () => rootRoute,
    path: '/finance/merchants',
    component: MerchantsPage,
  }),
  createRoute({
    getParentRoute: () => rootRoute,
    path: '/finance/connections',
    component: ConnectionsPage,
  }),
  createRoute({ getParentRoute: () => rootRoute, path: '/finance/more', component: MorePage }),
  createRoute({ getParentRoute: () => rootRoute, path: '/health', component: TodayPage }),
  createRoute({
    getParentRoute: () => rootRoute,
    path: '/health/activities',
    validateSearch: validateActivitiesSearch,
    component: ActivitiesPage,
  }),
  createRoute({
    getParentRoute: () => rootRoute,
    path: '/health/activities/$id',
    component: ActivityPage,
  }),
  createRoute({
    getParentRoute: () => rootRoute,
    path: '/health/training',
    component: TrainingPage,
  }),
  createRoute({
    getParentRoute: () => rootRoute,
    path: '/health/performance',
    component: PerformancePage,
  }),
  createRoute({
    getParentRoute: () => rootRoute,
    path: '/health/recovery',
    component: RecoveryPage,
    validateSearch: validateRecoverySearch,
  }),
  createRoute({
    getParentRoute: () => rootRoute,
    path: '/health/sleep',
    validateSearch: validateSleepSearch,
    component: SleepPage,
  }),
  createRoute({
    getParentRoute: () => rootRoute,
    path: '/health/body',
    component: BodyPage,
    validateSearch: validateBodySearch,
  }),
  createRoute({ getParentRoute: () => rootRoute, path: '/health/garmin', component: GarminPage }),
  createRoute({ getParentRoute: () => rootRoute, path: '/health/more', component: HealthMorePage }),
  // Where the bank sends the browser back after authorization (Enable Banking redirect URL).
  createRoute({
    getParentRoute: () => rootRoute,
    path: '/finance/connections/callback',
    validateSearch: validateCallbackSearch,
    component: CallbackPage,
  }),
]);

export function createAppRouter(history?: RouterHistory) {
  return createRouter({ routeTree, history });
}

export const router = createAppRouter();

declare module '@tanstack/react-router' {
  interface Register {
    router: typeof router;
  }
}
