import {
  ChartLine,
  Landmark,
  LayoutGrid,
  List,
  type LucideIcon,
  Plug,
  Repeat,
  Store,
  Tag,
  Target,
  Workflow,
} from 'lucide-react';

export type Path =
  | '/'
  | '/finance/transactions'
  | '/finance/budgets'
  | '/finance/recurring'
  | '/finance/investments'
  | '/finance/categories'
  | '/finance/merchants'
  | '/finance/rules'
  | '/finance/accounts'
  | '/finance/connections'
  | '/finance/more';

export type NavItem = { label: string; to: Path; icon: LucideIcon };

/**
 * One domain of the hub (docs/design/navigation.md, B1): its mark, its pages in the sidebar's
 * groups, and the pages the phone's tab bar shows before More. A new domain is a new entry here.
 */
export type Domain = {
  name: string;
  mark: string;
  home: Path;
  groups: { label?: string; items: NavItem[] }[];
  tabs: Path[];
  more: Path;
};

export const FINANCE: Domain = {
  name: 'Finance',
  mark: '€',
  home: '/',
  groups: [
    {
      items: [
        { label: 'Overview', to: '/', icon: LayoutGrid },
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
  // Spending joins the tabs, after Overview, when its page exists (M7 F3).
  tabs: ['/', '/finance/transactions', '/finance/budgets'],
  more: '/finance/more',
};

export const DOMAINS: Domain[] = [FINANCE];

export function navItems(domain: Domain): NavItem[] {
  return domain.groups.flatMap((group) => group.items);
}
