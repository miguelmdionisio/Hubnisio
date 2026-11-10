import {
  ChartLine,
  ChartPie,
  Heart,
  Landmark,
  LayoutGrid,
  List,
  type LucideIcon,
  Moon,
  Plug,
  Repeat,
  Store,
  Sun,
  Tag,
  Target,
  TrendingUp,
  User,
  Watch,
  Workflow,
  Zap,
} from 'lucide-react';

export type Path =
  | '/'
  | '/finance/spending'
  | '/finance/transactions'
  | '/finance/budgets'
  | '/finance/recurring'
  | '/finance/investments'
  | '/finance/categories'
  | '/finance/merchants'
  | '/finance/rules'
  | '/finance/accounts'
  | '/finance/connections'
  | '/finance/more'
  | '/health'
  | '/health/activities'
  | '/health/training'
  | '/health/performance'
  | '/health/recovery'
  | '/health/sleep'
  | '/health/body'
  | '/health/garmin'
  | '/health/more';

export type NavItem = { label: string; to: Path; icon: LucideIcon };

/**
 * One domain of the hub (docs/design/navigation.md, B1): its mark, its pages in the sidebar's
 * groups, and the pages the phone's tab bar shows before More. A new domain is a new entry here.
 */
export type Domain = {
  /** Set as `data-domain` on the page: the domain's accent follows it (index.css). */
  id: 'finance' | 'health';
  name: string;
  mark: string;
  home: Path;
  groups: { label?: string; items: NavItem[] }[];
  tabs: Path[];
  more: Path;
};

export const FINANCE: Domain = {
  id: 'finance',
  name: 'Finance',
  mark: '€',
  home: '/',
  groups: [
    {
      items: [
        { label: 'Overview', to: '/', icon: LayoutGrid },
        { label: 'Spending', to: '/finance/spending', icon: ChartPie },
        { label: 'Transactions', to: '/finance/transactions', icon: List },
        { label: 'Budgets', to: '/finance/budgets', icon: Target },
        { label: 'Recurring', to: '/finance/recurring', icon: Repeat },
        { label: 'Investments', to: '/finance/investments', icon: ChartLine },
      ],
    },
    {
      label: 'Organise',
      items: [
        { label: 'Categories', to: '/finance/categories', icon: Tag },
        { label: 'Merchants', to: '/finance/merchants', icon: Store },
        { label: 'Rules', to: '/finance/rules', icon: Workflow },
      ],
    },
    {
      label: 'Sources',
      items: [
        { label: 'Accounts', to: '/finance/accounts', icon: Landmark },
        { label: 'Bank connections', to: '/finance/connections', icon: Plug },
      ],
    },
  ],
  tabs: ['/', '/finance/spending', '/finance/transactions', '/finance/budgets'],
  more: '/finance/more',
};

export const HEALTH: Domain = {
  id: 'health',
  name: 'Health',
  mark: 'H',
  home: '/health',
  groups: [
    {
      items: [
        { label: 'Today', to: '/health', icon: Sun },
        { label: 'Activities', to: '/health/activities', icon: List },
      ],
    },
    {
      label: 'Analyse',
      items: [
        { label: 'Training', to: '/health/training', icon: TrendingUp },
        { label: 'Performance', to: '/health/performance', icon: Zap },
        { label: 'Recovery', to: '/health/recovery', icon: Heart },
        { label: 'Sleep', to: '/health/sleep', icon: Moon },
        { label: 'Body', to: '/health/body', icon: User },
      ],
    },
    {
      label: 'Sources',
      items: [{ label: 'Garmin', to: '/health/garmin', icon: Watch }],
    },
  ],
  tabs: ['/health', '/health/activities', '/health/sleep', '/health/recovery'],
  more: '/health/more',
};

export const DOMAINS: Domain[] = [FINANCE, HEALTH];

/** The domain a URL belongs to: Health lives under /health, everything else is Finance. */
export function domainForPath(pathname: string): Domain {
  return pathname === '/health' || pathname.startsWith('/health/') ? HEALTH : FINANCE;
}

export function navItems(domain: Domain): NavItem[] {
  return domain.groups.flatMap((group) => group.items);
}
