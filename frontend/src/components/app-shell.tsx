import { Link, Outlet } from '@tanstack/react-router';
import {
  ArrowLeftRight,
  House,
  Landmark,
  ListChecks,
  type LucideIcon,
  Menu,
  PiggyBank,
  Repeat,
  Store,
  Tags,
  TrendingUp,
  Wallet,
} from 'lucide-react';
import { type ReactNode, useState } from 'react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Sheet, SheetContent, SheetTitle, SheetTrigger } from '@/components/ui/sheet';
import { Toaster } from '@/components/ui/sonner';
import { useView, VIEW_LABELS, VIEW_NOTES, type View, ViewProvider } from '@/lib/view';

type Path =
  | '/'
  | '/finance/accounts'
  | '/finance/investments'
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
  onNavigate,
  children,
}: {
  to: Path;
  icon: LucideIcon;
  onNavigate?: () => void;
  children: ReactNode;
}) {
  return (
    <Link
      to={to}
      activeOptions={{ exact: to === '/' }}
      onClick={onNavigate}
      className="flex items-center gap-2 rounded-md px-2 py-2.5 text-sm text-sidebar-foreground hover:bg-sidebar-accent md:py-1.5"
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

/** What the sidebar holds, and the menu on a phone: the view and the pages. */
function Navigation({ onNavigate }: { onNavigate?: () => void }) {
  return (
    <>
      <ViewToggle />
      <nav className="mt-6 space-y-6" aria-label="Main">
        <div className="space-y-0.5">
          <NavLink to="/" icon={House} onNavigate={onNavigate}>
            Home
          </NavLink>
        </div>
        <NavSection title="Finance">
          <NavLink to="/finance/accounts" icon={Wallet} onNavigate={onNavigate}>
            Accounts
          </NavLink>
          <NavLink to="/finance/investments" icon={TrendingUp} onNavigate={onNavigate}>
            Investments
          </NavLink>
          <NavLink to="/finance/transactions" icon={ArrowLeftRight} onNavigate={onNavigate}>
            Transactions
          </NavLink>
          <NavLink to="/finance/categories" icon={Tags} onNavigate={onNavigate}>
            Categories
          </NavLink>
          <NavLink to="/finance/budgets" icon={PiggyBank} onNavigate={onNavigate}>
            Budgets
          </NavLink>
          <NavLink to="/finance/recurring" icon={Repeat} onNavigate={onNavigate}>
            Recurring
          </NavLink>
          <NavLink to="/finance/rules" icon={ListChecks} onNavigate={onNavigate}>
            Rules
          </NavLink>
          <NavLink to="/finance/merchants" icon={Store} onNavigate={onNavigate}>
            Merchants
          </NavLink>
          <NavLink to="/finance/connections" icon={Landmark} onNavigate={onNavigate}>
            Bank connections
          </NavLink>
        </NavSection>
      </nav>
    </>
  );
}

/** On a phone, a bar with the menu in a sheet; from `md` up, the sidebar. */
function MobileBar() {
  const [open, setOpen] = useState(false);
  return (
    <header className="sticky top-0 z-40 flex items-center gap-2 border-b bg-background/95 px-2 py-2 backdrop-blur md:hidden">
      <Sheet open={open} onOpenChange={setOpen}>
        <SheetTrigger asChild>
          <Button variant="ghost" size="icon" className="size-11" aria-label="Menu">
            <Menu className="size-5" aria-hidden />
          </Button>
        </SheetTrigger>
        <SheetContent side="left" className="w-72 overflow-y-auto bg-sidebar px-3 py-4">
          <SheetTitle className="px-2 text-lg font-semibold">Hubnisio</SheetTitle>
          <Navigation onNavigate={() => setOpen(false)} />
        </SheetContent>
      </Sheet>
      <Link to="/" className="text-lg font-semibold">
        Hubnisio
      </Link>
    </header>
  );
}

function Shell() {
  return (
    <div className="min-h-screen bg-background text-foreground md:flex">
      <a
        href="#main"
        className="sr-only z-50 rounded-md bg-background px-3 py-2 text-sm font-medium shadow focus:not-sr-only focus:fixed focus:top-2 focus:left-2"
      >
        Skip to content
      </a>
      <MobileBar />
      <aside className="sticky top-0 hidden h-screen w-56 shrink-0 overflow-y-auto border-r bg-sidebar px-3 py-4 md:block">
        <Link to="/" className="block px-2 text-lg font-semibold">
          Hubnisio
        </Link>
        <Navigation />
      </aside>
      <main
        id="main"
        tabIndex={-1}
        className="min-w-0 flex-1 px-4 py-5 outline-none md:px-8 md:py-6"
      >
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
    <div className="mb-6 flex flex-wrap items-start justify-between gap-x-4 gap-y-3">
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
    <p className="mt-1 flex items-center gap-2 text-sm text-muted-foreground" aria-live="polite">
      <Badge variant="secondary">{VIEW_LABELS[view]}</Badge>
      {VIEW_NOTES[view]}
    </p>
  );
}
