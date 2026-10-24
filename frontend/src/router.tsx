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
import { RecurringPage, validateRecurringSearch } from './routes/finance/recurring';
import { RulesPage } from './routes/finance/rules';
import { TransactionsPage, validateTransactionSearch } from './routes/finance/transactions';
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
