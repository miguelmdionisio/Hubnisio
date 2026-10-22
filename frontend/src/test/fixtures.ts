import type { AccountOut, CategoryGroupOut, TransactionOut } from '@/api/types.gen';

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
