import type {
  AccountOut,
  BudgetOut,
  BudgetsOut,
  CashFlow,
  CategoryGroupOut,
  CounterpartyOut,
  NetWorthOut,
  OverallBudgetOut,
  RecurringOut,
  RuleOut,
  Spending,
  SpendingGroup,
  TransactionOut,
  UpcomingPayment,
} from '@/api/types.gen';

export const account: AccountOut = {
  id: 'a1',
  name: 'Conta à Ordem',
  institution_name: 'Banco BPI',
  iban_masked: 'PT50 •••• 0154',
  currency: 'EUR',
  cash_account_type: 'CACC',
  visibility: 'shared',
  include_in_net_worth: true,
  is_owner: true,
  hidden_at: null,
  transaction_count: 0,
  balance: null,
};

export function transaction(id: string, overrides: Partial<TransactionOut> = {}): TransactionOut {
  return {
    id,
    account_id: 'a1',
    status: 'booked',
    occurred_on: '2026-10-14',
    booking_date: '2026-10-14',
    value_date: null,
    amount: '-42.1700',
    currency: 'EUR',
    original_amount: null,
    original_currency: null,
    counterparty_name: null,
    description: null,
    reference: null,
    mcc: null,
    bank_code: null,
    kind: 'expense',
    kind_source: null,
    category: null,
    counterparty: null,
    transfer: null,
    note: null,
    tags: [],
    rule_tags: [],
    ...overrides,
  };
}

export const categories: CategoryGroupOut[] = [
  {
    id: 'g-food',
    name: 'Food',
    kind: 'expense',
    position: 0,
    archived: false,
    transactions: 0,
    children: [
      {
        id: 'c-groceries',
        name: 'Groceries',
        kind: 'expense',
        position: 0,
        archived: false,
        transactions: 3,
      },
      {
        id: 'c-old',
        name: 'Old stuff',
        kind: 'expense',
        position: 1,
        archived: true,
        transactions: 0,
      },
    ],
  },
];

export function merchant(
  id: string,
  name: string,
  overrides: Partial<CounterpartyOut> = {},
): CounterpartyOut {
  return {
    id,
    name,
    default_category_id: null,
    transactions: 0,
    aliases: [name.toLowerCase()],
    ...overrides,
  };
}

export function rule(id: string, name: string, overrides: Partial<RuleOut> = {}): RuleOut {
  return {
    id,
    name,
    position: 0,
    enabled: true,
    match: 'all',
    conditions: [{ field: 'description', op: 'contains', value: 'continente' }],
    actions: [{ type: 'set_category', category_id: 'c-groceries' }],
    stop_processing: false,
    ...overrides,
  };
}

/** A budget with nothing spent yet; override what a test cares about. */
export function budget(
  categoryId: string,
  name: string,
  overrides: Partial<BudgetOut> = {},
): BudgetOut {
  return {
    category_id: categoryId,
    name,
    group_id: null,
    rollover: false,
    overspend: 'forgive',
    starts_on: '2026-01-01',
    limit: '100.00',
    carried_in: '0.00',
    available: '100.00',
    spent: '0.00',
    remaining: '100.00',
    children: [],
    ...overrides,
  };
}

/** The overall budget with nothing spent yet; override what a test cares about. */
export function overallBudget(overrides: Partial<OverallBudgetOut> = {}): OverallBudgetOut {
  return {
    rollover: false,
    overspend: 'forgive',
    starts_on: '2026-01-01',
    limit: '2000.00',
    carried_in: '0.00',
    available: '2000.00',
    spent: '0.00',
    remaining: '2000.00',
    ...overrides,
  };
}

export function budgetsOut(budgets: BudgetOut[], overrides: Partial<BudgetsOut> = {}): BudgetsOut {
  return {
    month: '2026-10-01',
    overall: null,
    budgets,
    total_limit: '0.00',
    total_available: '0.00',
    total_spent: '0.00',
    unbudgeted: '0.00',
    uncategorized: '0.00',
    unconverted: 0,
    ...overrides,
  };
}

/** A monthly 9.99 payment, detected but not yet reviewed; override what a test cares about. */
export function recurring(
  id: string,
  name: string,
  overrides: Partial<RecurringOut> = {},
): RecurringOut {
  return {
    id,
    account_id: 'a1',
    account_name: 'Conta à Ordem',
    name,
    counterparty_id: null,
    cadence: 'monthly',
    kind: 'expense',
    expected_amount: '-9.99',
    currency: 'EUR',
    amount_varies: false,
    occurrences: 6,
    first_seen_on: '2026-04-05',
    last_seen_on: '2026-09-05',
    next_expected_on: '2026-10-05',
    previous_amount: null,
    amount_changed_on: null,
    status: 'active',
    review: 'suggested',
    ...overrides,
  };
}

/** Net worth from (date, amount) pairs, oldest first; the total is the last amount. */
export function netWorth(
  points: [string, string][],
  overrides: Partial<NetWorthOut> = {},
): NetWorthOut {
  return {
    total: points.at(-1)?.[1] ?? '0.00',
    points: points.map(([on, amount]) => ({ on, amount })),
    accounts: [],
    unconverted: 0,
    ...overrides,
  };
}

export function spendingGroup(id: string, name: string, amounts: string[]): SpendingGroup {
  return { id, name, amounts, categories: [] };
}

export function spending(
  months: string[],
  groups: SpendingGroup[],
  uncategorized: string[],
  overrides: Partial<Spending> = {},
): Spending {
  return { months, groups, uncategorized, unconverted: 0, ...overrides };
}

/** Cash flow from (month, income, spending) rows; net is income minus spending. */
export function cashFlow(
  rows: [string, string, string][],
  overrides: Partial<CashFlow> = {},
): CashFlow {
  return {
    months: rows.map(([month, income, spent]) => ({
      month,
      income,
      spending: spent,
      net: (Number(income) - Number(spent)).toFixed(2),
    })),
    unconverted: 0,
    ...overrides,
  };
}

export function upcomingPayment(
  seriesId: string,
  name: string,
  on: string,
  amount: string,
  overrides: Partial<UpcomingPayment> = {},
): UpcomingPayment {
  return {
    series_id: seriesId,
    name,
    on,
    kind: 'expense',
    amount,
    currency: 'EUR',
    amount_eur: amount,
    ...overrides,
  };
}
