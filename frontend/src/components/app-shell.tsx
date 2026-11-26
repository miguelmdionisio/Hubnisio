import { useQueryClient } from '@tanstack/react-query';
import { Link, Outlet, useNavigate, useRouterState } from '@tanstack/react-router';
import { Check, ChevronDown, Ellipsis, Search, WifiOff } from 'lucide-react';
import { type ReactNode, useLayoutEffect, useRef, useState } from 'react';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import { Toaster } from '@/components/ui/sonner';
import { useHubUnreachable } from '@/lib/reachability';
import { ThemeProvider } from '@/lib/theme';
import { slideFor } from '@/lib/transitions';
import { cn } from '@/lib/utils';
import { useView, VIEW_LABELS, VIEW_NOTES, type View, ViewProvider } from '@/lib/view';
import { DOMAINS, type Domain, domainForPath, FINANCE, HEALTH, navItems } from './domains';
import { EdgeSwipeBack } from './edge-swipe-back';
import { HealthFreshness } from './health-freshness';
import { PullToRefresh } from './pull-to-refresh';
import { SearchProvider, useOpenSearch } from './search';
import { Segmented } from './segmented';
import { SyncFreshness } from './sync-freshness';
import { ThemeSwitch } from './theme-switch';

export function AppShell() {
  return (
    <ThemeProvider>
      <ViewProvider>
        <SearchProvider>
          <Shell />
        </SearchProvider>
      </ViewProvider>
    </ThemeProvider>
  );
}

/** Desktop: one sidebar (docs/design/navigation.md, B1). Below `md`: a tab bar at the bottom. */
function Shell() {
  const domain = useCurrentDomain();
  // On <html>, so portals (menus, the command menu, toasts) take the accent too.
  useLayoutEffect(() => {
    document.documentElement.dataset.domain = domain.id;
  }, [domain.id]);
  useDetailPageOpensAtTop();
  return (
    <div className="min-h-dvh bg-background text-foreground md:flex">
      <a
        href="#main"
        className="sr-only z-50 rounded-lg bg-background px-3 py-2 text-sm font-medium shadow-pop focus:not-sr-only focus:fixed focus:top-2 focus:left-2"
      >
        Skip to content
      </a>
      <Sidebar domain={domain} />
      <main
        id="main"
        tabIndex={-1}
        className="min-w-0 flex-1 px-4 pb-[calc(6rem+env(safe-area-inset-bottom))] outline-none md:px-7 md:pb-12"
      >
        <Outlet />
      </main>
      <TabBar domain={domain} />
      <Unreachable />
      <PullToRefresh />
      <EdgeSwipeBack />
      <Toaster />
    </div>
  );
}

/**
 * When the hub doesn't answer: on the phone that's the PC or the stack being off. The app's shell
 * still opens (it's kept on the phone); its data never is.
 */
function Unreachable() {
  const unreachable = useHubUnreachable();
  const queryClient = useQueryClient();
  if (!unreachable) return null;
  return (
    <div
      role="status"
      className="fixed inset-x-3 bottom-[calc(4.75rem+env(safe-area-inset-bottom))] z-40 flex items-center gap-3 rounded-2xl bg-popover px-4 py-2 text-sm shadow-pop md:right-6 md:bottom-6 md:left-auto md:w-[420px]"
    >
      <WifiOff className="size-4 shrink-0 text-muted-foreground" aria-hidden />
      <p className="min-w-0 flex-1">
        <span className="font-semibold">Can't reach the hub.</span>{' '}
        <span className="text-muted-foreground">It answers while the PC and its stack run.</span>
      </p>
      <button
        type="button"
        onClick={() => void queryClient.refetchQueries({ type: 'active' })}
        className="min-h-11 shrink-0 rounded-full px-3 font-semibold text-primary"
      >
        Try again
      </button>
    </div>
  );
}

/**
 * A detail page that slides in opens at its top. The router resets the scroll itself, but WebKit
 * loses that inside a view transition (M9 P5). Going back keeps the router's restored position.
 */
function useDetailPageOpensAtTop() {
  const pathname = useRouterState({ select: (state) => state.location.pathname });
  const previous = useRef(pathname);
  useLayoutEffect(() => {
    if (slideFor(previous.current, pathname) === 'slide-forward') window.scrollTo(0, 0);
    previous.current = pathname;
  }, [pathname]);
}

/** The domain the current URL belongs to. */
export function useCurrentDomain(): Domain {
  return domainForPath(useRouterState({ select: (state) => state.location.pathname }));
}

function Sidebar({ domain }: { domain: Domain }) {
  const openSearch = useOpenSearch();
  return (
    <aside className="sticky top-0 hidden h-dvh w-[200px] shrink-0 flex-col overflow-y-auto border-r bg-sidebar px-2 py-3 text-[13.5px] text-sidebar-foreground md:flex">
      <DomainSwitcher domain={domain} />
      <nav aria-label={domain.name} className="flex flex-col gap-px">
        {domain.groups.map((group) => (
          <div key={group.label ?? ''} className="flex flex-col gap-px">
            {group.label && (
              <p className="px-[9px] pt-3.5 pb-1 text-[11.5px] font-semibold text-faint">
                {group.label}
              </p>
            )}
            {group.items.map((item) => (
              <Link
                key={item.to}
                to={item.to}
                activeOptions={{ exact: item.to === domain.home }}
                className="flex items-center gap-2.5 rounded-lg px-[9px] py-[7px] transition-colors hover:text-sidebar-accent-foreground"
                activeProps={{
                  className:
                    'bg-sidebar-accent font-semibold text-sidebar-accent-foreground [&>svg]:text-sidebar-primary',
                }}
              >
                <item.icon className="size-4" aria-hidden />
                {item.label}
              </Link>
            ))}
          </div>
        ))}
      </nav>
      <div className="mt-auto flex flex-col gap-1 pt-4">
        <ThemeSwitch className="mx-[5px] self-start" />
        <button
          type="button"
          onClick={openSearch}
          className="flex items-center gap-2.5 rounded-lg px-[9px] py-[7px] text-left transition-colors hover:text-sidebar-accent-foreground"
        >
          <Search className="size-4" aria-hidden />
          Search
          <kbd className="ml-auto rounded border px-1 text-[10.5px] font-semibold">Ctrl K</kbd>
        </button>
      </div>
    </aside>
  );
}

export function DomainMark({ domain }: { domain: Domain }) {
  return (
    <b
      className="grid size-[22px] shrink-0 place-items-center rounded-full bg-sidebar-primary text-xs text-sidebar-primary-foreground"
      aria-hidden
    >
      {domain.mark}
    </b>
  );
}

/** The hub's domains; only built ones are listed. Switching goes to that domain's first page. */
function DomainSwitcher({ domain }: { domain: Domain }) {
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);
  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <button
          type="button"
          aria-label={`Domain: ${domain.name}`}
          className="mb-2.5 flex items-center gap-[9px] rounded-lg px-2 py-1.5 text-left font-semibold text-sidebar-accent-foreground hover:bg-sidebar-accent"
        >
          <DomainMark domain={domain} />
          {domain.name}
          <ChevronDown className="ml-auto size-4 text-faint" aria-hidden />
        </button>
      </PopoverTrigger>
      <PopoverContent align="start" className="w-52 p-1.5 shadow-pop">
        {DOMAINS.map((option) => (
          <button
            key={option.name}
            type="button"
            onClick={() => {
              setOpen(false);
              navigate({ to: option.home });
            }}
            className="flex w-full items-center gap-2.5 rounded-lg px-2.5 py-2 text-left text-sm font-medium hover:bg-accent"
          >
            <DomainMark domain={option} />
            {option.name}
            {option.name === domain.name && (
              <Check className="ml-auto size-4 text-primary" aria-hidden />
            )}
          </button>
        ))}
      </PopoverContent>
    </Popover>
  );
}

/** The phone's navigation: the domain's main pages, then More for the rest. */
function TabBar({ domain }: { domain: Domain }) {
  const pathname = useRouterState({ select: (state) => state.location.pathname });
  const items = navItems(domain);
  const tabs = domain.tabs.flatMap((to) => items.filter((item) => item.to === to));
  const inTabs = tabs.some((tab) =>
    tab.to === domain.home ? pathname === tab.to : pathname.startsWith(tab.to),
  );
  const tabClass =
    'tap-area flex flex-col items-center gap-[3px] [--tap-x:0px] [--tap-y:4px] text-[10.5px] font-medium text-faint [&>svg]:size-[22px]';
  return (
    <nav
      aria-label="Tabs"
      className="fixed inset-x-0 bottom-0 z-30 grid border-t bg-background/92 px-1.5 pt-2 pb-[calc(0.625rem+env(safe-area-inset-bottom))] backdrop-blur-md md:hidden"
      style={{ gridTemplateColumns: `repeat(${tabs.length + 1}, minmax(0, 1fr))` }}
    >
      {tabs.map((tab) => (
        <Link
          key={tab.to}
          to={tab.to}
          activeOptions={{ exact: tab.to === domain.home }}
          className={tabClass}
          activeProps={{ className: 'text-primary' }}
        >
          <tab.icon aria-hidden />
          {tab.label}
        </Link>
      ))}
      <Link
        to={domain.more}
        className={cn(tabClass, !inTabs && 'text-primary')}
        aria-current={!inTabs ? 'page' : undefined}
      >
        <Ellipsis aria-hidden />
        More
      </Link>
    </nav>
  );
}

/** Mine or Household: which accounts the page's sums count. */
function ViewSwitch() {
  const { view, setView } = useView();
  return (
    <Segmented
      label="View"
      value={view}
      onChange={setView}
      options={(['personal', 'household'] satisfies View[]).map((option) => ({
        value: option,
        label: VIEW_LABELS[option],
        title: VIEW_NOTES[option],
      }))}
    />
  );
}

/** Search on the phone, where there's no Ctrl K: last in the header's top row, before any actions. */
function PhoneSearch() {
  const openSearch = useOpenSearch();
  return (
    <button
      type="button"
      aria-label="Search"
      onClick={openSearch}
      className="tap-area -mr-1.5 grid size-9 shrink-0 place-items-center rounded-full text-muted-foreground md:hidden"
    >
      <Search className="size-5" aria-hidden />
    </button>
  );
}

/**
 * Every page's header: its title, how fresh the data is, and on pages that sum money
 * (`showsView`) the Mine / Household switch, then the page's own actions. `leading` comes
 * before the title: a drill-down's back button and chip.
 */
export function PageHeader({
  title,
  leading,
  actions,
  showsView,
}: {
  title: string;
  leading?: ReactNode; // before the title: a back button, a chip
  actions?: ReactNode;
  showsView?: boolean;
}) {
  const domain = useCurrentDomain();
  return (
    // Installed on the iPhone the status bar sits over the page: the header pads for the notch.
    <header className="sticky top-0 z-20 -mx-4 mb-5 flex min-h-[58px] flex-wrap items-center gap-x-3 gap-y-2 bg-background/88 px-4 pt-[calc(0.625rem+env(safe-area-inset-top))] pb-2.5 backdrop-blur-md md:-mx-7 md:border-b md:px-7">
      {leading && <div className="-mr-0.5 flex items-center gap-2">{leading}</div>}
      <h1 className="min-w-0 truncate text-2xl font-bold tracking-[-0.02em] md:text-lg md:tracking-normal">
        {title}
      </h1>
      <div className="flex-1" />
      {domain === FINANCE && <SyncFreshness className="hidden md:flex" />}
      {/* Health's at every width: one watch, and the phone is where Today is read. */}
      {domain === HEALTH && <HealthFreshness />}
      {showsView && <ViewSwitch />}
      <PhoneSearch />
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </header>
  );
}
