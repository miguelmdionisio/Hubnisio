import { Link, Outlet } from '@tanstack/react-router';
import {
  ArrowLeftRight,
  House,
  Landmark,
  ListChecks,
  type LucideIcon,
  PiggyBank,
  Repeat,
  Store,
  Tags,
  Wallet,
} from 'lucide-react';
import type { ReactNode } from 'react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Toaster } from '@/components/ui/sonner';
import { useView, VIEW_LABELS, VIEW_NOTES, type View, ViewProvider } from '@/lib/view';

type Path =
  | '/'
  | '/finance/accounts'
  | '/finance/transactions'
  | '/finance/categories'
  | '/finance/budgets'
  | '/finance/recurring'
  | '/finance/rules'
  | '/finance/merchants'
  | '/finance/connections';

function NavLink({
  to,
  icon: Icon,
  children,
}: {
  to: Path;
  icon: LucideIcon;
  children: ReactNode;
}) {
  return (
    <Link
      to={to}
      activeOptions={{ exact: to === '/' }}
      className="flex items-center gap-2 rounded-md px-2 py-1.5 text-sm text-sidebar-foreground hover:bg-sidebar-accent"
      activeProps={{ className: 'bg-sidebar-accent font-medium text-sidebar-accent-foreground' }}
    >
      <Icon className="size-4" aria-hidden />
      {children}
    </Link>
  );
}

function NavSection({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div>
      <p className="px-2 pb-1 text-xs font-medium tracking-wide text-muted-foreground uppercase">
        {title}
      </p>
      <div className="space-y-0.5">{children}</div>
    </div>
  );
}

/** Mine or Household: which accounts the overview, charts and budgets count. */
function ViewToggle() {
  const { view, setView } = useView();
  return (
    <fieldset aria-label="View" className="mt-4 flex rounded-md border bg-background p-0.5">
      {(['personal', 'household'] satisfies View[]).map((option) => (
        <Button
          key={option}
          variant={view === option ? 'secondary' : 'ghost'}
          size="sm"
          className="h-7 flex-1"
          aria-pressed={view === option}
          title={VIEW_NOTES[option]}
          onClick={() => setView(option)}
        >
          {VIEW_LABELS[option]}
        </Button>
      ))}
    </fieldset>
  );
}

export function AppShell() {
  return (
    <ViewProvider>
      <Shell />
    </ViewProvider>
  );
}

function Shell() {
  return (
    <div className="flex min-h-screen bg-background text-foreground">
      <aside className="sticky top-0 h-screen w-56 shrink-0 overflow-y-auto border-r bg-sidebar px-3 py-4">
        <Link to="/" className="block px-2 text-lg font-semibold">
          Hubnisio
        </Link>
        <ViewToggle />
        <nav className="mt-6 space-y-6" aria-label="Main">
          <div className="space-y-0.5">
            <NavLink to="/" icon={House}>
              Home
            </NavLink>
          </div>
          <NavSection title="Finance">
            <NavLink to="/finance/accounts" icon={Wallet}>
              Accounts
            </NavLink>
            <NavLink to="/finance/transactions" icon={ArrowLeftRight}>
              Transactions
            </NavLink>
            <NavLink to="/finance/categories" icon={Tags}>
              Categories
            </NavLink>
            <NavLink to="/finance/budgets" icon={PiggyBank}>
              Budgets
            </NavLink>
            <NavLink to="/finance/recurring" icon={Repeat}>
              Recurring
            </NavLink>
            <NavLink to="/finance/rules" icon={ListChecks}>
              Rules
            </NavLink>
            <NavLink to="/finance/merchants" icon={Store}>
              Merchants
            </NavLink>
            <NavLink to="/finance/connections" icon={Landmark}>
              Bank connections
            </NavLink>
          </NavSection>
        </nav>
      </aside>
      <main className="min-w-0 flex-1 px-8 py-6">
        <Outlet />
      </main>
      <Toaster />
    </div>
  );
}

/** `showsView`: the page counts the accounts of the chosen view, so it says which. */
export function PageHeader({
  title,
  description,
  actions,
  showsView,
}: {
  title: string;
  description?: string;
  actions?: ReactNode;
  showsView?: boolean;
}) {
  return (
    <div className="mb-6 flex items-start justify-between gap-4">
      <div>
        <h1 className="text-2xl font-semibold">{title}</h1>
        {description && <p className="mt-1 text-sm text-muted-foreground">{description}</p>}
        {showsView && <ViewNote />}
      </div>
      {actions && <div className="flex shrink-0 gap-2">{actions}</div>}
    </div>
  );
}

function ViewNote() {
  const { view } = useView();
  return (
    <p className="mt-1 flex items-center gap-2 text-sm text-muted-foreground">
      <Badge variant="secondary">{VIEW_LABELS[view]}</Badge>
      {VIEW_NOTES[view]}
    </p>
  );
}
