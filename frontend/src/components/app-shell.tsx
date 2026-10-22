import { Link, Outlet } from '@tanstack/react-router';
import {
  ArrowLeftRight,
  House,
  Landmark,
  ListChecks,
  type LucideIcon,
  PiggyBank,
  Store,
  Tags,
  Wallet,
} from 'lucide-react';
import type { ReactNode } from 'react';
import { Toaster } from '@/components/ui/sonner';

type Path =
  | '/'
  | '/finance/accounts'
  | '/finance/transactions'
  | '/finance/categories'
  | '/finance/budgets'
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

export function AppShell() {
  return (
    <div className="flex min-h-screen bg-background text-foreground">
      <aside className="sticky top-0 h-screen w-56 shrink-0 overflow-y-auto border-r bg-sidebar px-3 py-4">
        <Link to="/" className="block px-2 text-lg font-semibold">
          Hubnisio
        </Link>
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

export function PageHeader({
  title,
  description,
  actions,
}: {
  title: string;
  description?: string;
  actions?: ReactNode;
}) {
  return (
    <div className="mb-6 flex items-start justify-between gap-4">
      <div>
        <h1 className="text-2xl font-semibold">{title}</h1>
        {description && <p className="mt-1 text-sm text-muted-foreground">{description}</p>}
      </div>
      {actions && <div className="flex shrink-0 gap-2">{actions}</div>}
    </div>
  );
}
